#!/usr/bin/env bash
# M4b: 0-RTT and replay, with aioquic as client (the lab's curl cannot keep
# sessions between runs). RTT 50 ms, no loss. For each server mode
# (MODES="plain retry tooearly": nothing / `quic_retry on` / 425 Too Early for any
# request that arrived in early data, RFC 8470):
#   1. time to response for a full handshake, a resumed 1-RTT handshake and 0-RTT (REPS each);
#   2. for each delay d in REPLAY_DELAYS, a new "victim" 0-RTT request with a unique URL is
#      captured at the router; its first flight (after the Retry, if any) is extracted and
#      resent once, d seconds later, from the victim's address and port;
#   3. the access log shows whether the victim URL was executed a second time.
# VICTIMS=n repeats step 2 with n different victims per delay (each one a new connection
# with its own connection IDs). TAG=-x writes to zerortt-<mode>-x/ and zerortt-summary-x.txt,
# so a new campaign does not overwrite an earlier one.
# One victim per delay: the half-open connection that a replay creates in nginx (60 s
# handshake timeout) would swallow later copies with the same connection ID.
# Output: results/m4/zerortt-<mode>/ (pcap, keys, flight hex, timings) and a summary line.
set -euo pipefail
export LC_NUMERIC=C   # printf with decimal points
cd "$(dirname "$0")/.."
export COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.m3.yml:docker-compose.m4.yml} LAB_NET=10.20
source scripts/lib.sh
R="docker compose exec -T router"; C="docker compose exec -T client"
REPS=${REPS:-5}; REPLAY_DELAYS=${REPLAY_DELAYS:-1 5 8 12 15 30 70}; VICTIMS=${VICTIMS:-1}; TAG=${TAG:-}
ACCESS=../results/m3/server-logs/access.log
Z="python3 /scripts/m4_zerortt.py"

server_mode() {  # plain | retry | tooearly
  # Recreate the server instead of `nginx -s reload`: after a reload the old worker stays
  # alive while it holds the half-open connections created by replays, and with reuseport
  # it keeps receiving part of the new connections, which it no longer serves.
  # The client lives in the server's PID namespace, so it is recreated too.
  rm -f server/m4-extra/*.conf
  case $1 in
    retry)    echo "quic_retry on;" > server/m4-extra/retry.conf ;;
    tooearly) echo 'if ($ssl_early_data = "1") { return 425; }' > server/m4-extra/tooearly.conf ;;
  esac
  docker compose up -d --force-recreate server client >/dev/null 2>&1; sleep 2
  $R sh -c ": > /results/m3/server-logs/debug.log"   # one debug log per mode (it grows fast)
}
cleanup() { clear_netem; $R pkill -INT tcpdump 2>/dev/null || true; rm -f server/m4-extra/*.conf; }
trap cleanup EXIT
set_netem 50 0

for mode in ${MODES:-plain retry tooearly}; do
  OUT=/results/m4/zerortt-$mode$TAG; HOUT=../results/m4/zerortt-$mode$TAG
  $R rm -rf $OUT; mkdir -p "$HOUT"   # created by the host user, so tee can write here
  server_mode $mode
  K="--keylog $OUT/keys.log"

  # 1. timings
  for i in $(seq 1 "$REPS"); do
    $C $Z "https://server.lab/small.html?m4=$mode-full-$i" --save-ticket /tmp/t.bin $K | sed "s/^/full    /"
    $C $Z "https://server.lab/small.html?m4=$mode-1rtt-$i" --ticket /tmp/t.bin --save-ticket /tmp/t.bin $K | sed "s/^/resumed /"
    $C $Z "https://server.lab/small.html?m4=$mode-0rtt-$i" --ticket /tmp/t.bin --save-ticket /tmp/t.bin --zero-rtt $K | sed "s/^/0rtt    /"
  done | tee "$HOUT/timings.txt"

  # 2-3. VICTIMS victims per replay delay
  : > "$HOUT/replays.txt"
  for d in $REPLAY_DELAYS; do for v in $(seq 1 "$VICTIMS"); do
    id=$d-$v; pc=$OUT/victim-$id.pcap
    docker compose exec -d router tcpdump -i "$RIF_CLIENT" -s 0 -U -w $pc "host $LAB_NET.1.10 and udp port 443"
    sleep 1
    # fresh ticket for every victim, so the ticket age at the replay is about d
    $C $Z "https://server.lab/small.html?m4=$mode-ticket-$id" --save-ticket /tmp/t.bin >/dev/null
    url="/small.html?replay=$mode-$id-$(date +%s)"
    $C $Z "https://server.lab$url" --ticket /tmp/t.bin --zero-rtt $K | sed "s/^/victim $d s #$v: /" >> "$HOUT/timings.txt"
    t0=$(date +%s.%N)
    sleep 0.3; $R pkill -INT tcpdump || true
    sport=$(grep -F "\"GET $url " $ACCESS | tail -1 | awk '{split($2,a,":"); print a[2]}')
    [ -n "$sport" ] || { echo "victim $id: request not in the access log"; exit 1; }
    # first flight: client datagrams before the first server reply, or after the Retry
    # (long packet type 3) if the server sent one
    $R tshark -r $pc -Y "udp.port==$sport" \
       -T fields -E separator=/t -e ip.src -e quic.long.packet_type -e udp.payload 2>/dev/null |
      awk -F'\t' -v c="$LAB_NET.1.10" -v hf="$HOUT/flight-$id.hex" -v tf="$HOUT/flight-$id.txt" '
        BEGIN { collecting = 1 }
        $1 != c { if ($2 ~ /(^|,)3(,|$)/) { n = 0; collecting = 1 } else if (n) collecting = 0; next }
        collecting { n++; pay[n] = $3; typ[n] = $2 }
        END { for (i = 1; i <= n; i++) { print pay[i] > hf; print "datagram " i ": long packet types " typ[i] " (0=Initial 1=0-RTT), " length(pay[i])/2 " bytes" > tf } }'
    sleep "$(awk -v t0="$t0" -v d="$d" -v now="$(date +%s.%N)" 'BEGIN{x=t0+d-now; print (x>0?x:0)}')"
    tr=$(awk -v t0="$t0" -v now="$(date +%s.%N)" 'BEGIN{printf "%.1f", now-t0}')
    $C python3 /scripts/m4_replay.py $OUT/flight-$id.hex --src $LAB_NET.1.10 --sport "$sport" --count 1 >/dev/null
    sleep 1.5
    n=$(grep -c -F "\"GET $url HTTP/3.0\" 200 " $ACCESS || true)
    st=$(grep -F "\"GET $url " $ACCESS | awk '{print $6}' | paste -sd,)
    echo "replay d=$d #$v +${tr}s ($(paste -sd' ' "$HOUT/flight-$id.txt" | grep -o 'types [0-9,]*' | paste -sd'|')): served (200) $n time(s), statuses $st" | tee -a "$HOUT/replays.txt"
  done; done
  echo "SUMMARY mode=$mode: $(paste -sd';' "$HOUT/replays.txt")" >> ../results/m4/zerortt-summary$TAG.txt
done
