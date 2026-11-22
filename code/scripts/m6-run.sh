#!/usr/bin/env bash
# M6: robustness of aioquic 1.0.0 / 1.2.0 / 1.8.0 (local servers only, docker-compose.m6.yml).
#   1. malformed and misplaced frames (m6_attack.py case all), then a fresh-client probe;
#   2. CRYPTO flood and PATH_CHALLENGE flood (no ACKs) for SECS seconds each, with the
#      server restarted before each flood; server RSS and CPU sampled every second from the
#      host's /proc, and a legitimate client probing every 5 s.
# Output: results/m6/ (cases-<srv>.txt, flood-<kind>-<srv>.{csv,log,probe.txt,server.log})
set -euo pipefail
export LC_NUMERIC=C
cd "$(dirname "$0")/.."
export COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.m3.yml:docker-compose.m6.yml}
SECS=${SECS:-60}
SERVERS=${SERVERS:-aq100:10.20.2.20 aq120:10.20.2.21 aq180:10.20.2.22}
O=../results/m6; mkdir -p $O
A="docker compose exec -T client python3 /scripts/m6_attack.py"
HZ=$(getconf CLK_TCK)

sample() {  # $1 = container, $2 = csv; RSS (MB) and CPU (% of one core) every second
  local pid prev now t0 cpu
  pid=$(docker inspect -f '{{.State.Pid}}' "$(docker compose ps -q "$1")")
  t0=$(date +%s.%N); prev=$(awk '{print $14+$15}' /proc/$pid/stat)
  echo "t,rss_mb,cpu_pct" > "$2"
  while [ -r /proc/$pid/status ]; do
    sleep 1
    now=$(awk '{print $14+$15}' /proc/$pid/stat 2>/dev/null) || break
    cpu=$(( (now - prev) * 100 / HZ )); prev=$now
    awk -v t="$(date +%s.%N)" -v t0="$t0" -v c="$cpu" '/VmRSS/{printf "%.0f,%.1f,%d\n", t-t0, $2/1024, c}' /proc/$pid/status >> "$2" 2>/dev/null || break
  done
}

for s in $SERVERS; do
  srv=${s%%:*}; ip=${s#*:}
  docker compose restart "$srv" >/dev/null; sleep 2
  echo "######## $srv: malformed frames"
  $A "$ip" case all | tee "$O/cases-$srv.txt"
  $A "$ip" probe | tee -a "$O/cases-$srv.txt"

  for kind in crypto pathchallenge; do
    docker compose restart "$srv" >/dev/null; sleep 2
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "######## $srv: $kind flood, ${SECS}s"
    sample "$srv" "$O/flood-$kind-$srv.csv" & spid=$!
    ( for i in $(seq 0 5 $((${SECS%.*} + 10))); do
        printf 't=%3ds ' "$i"; $A "$ip" probe || echo "probe error"; sleep 5
      done > "$O/flood-$kind-$srv.probe.txt" ) & ppid=$!
    $A "$ip" flood "$kind" "$SECS" 2>&1 | tee "$O/flood-$kind-$srv.log" || true
    sleep 10; kill $spid $ppid 2>/dev/null || true; wait 2>/dev/null || true
    docker compose logs --no-log-prefix --since "$since" "$srv" > "$O/flood-$kind-$srv.server.log" 2>&1 || true
    state=$(docker inspect -f '{{.State.Status}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' "$(docker compose ps -aq "$srv")")
    peak=$(awk -F, 'NR>1 && $2>m {m=$2} END{print m+0}' "$O/flood-$kind-$srv.csv")
    fails=$(grep -c FAIL "$O/flood-$kind-$srv.probe.txt" || true)
    echo "SUMMARY $srv $kind: peak_rss=${peak}MB probes_failed=$fails/$(wc -l < "$O/flood-$kind-$srv.probe.txt") container=$state" | tee -a $O/summary.txt
    docker compose up -d "$srv" >/dev/null 2>&1   # bring it back if it died
  done
done
