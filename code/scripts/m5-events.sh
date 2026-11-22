#!/usr/bin/env bash
# M5: produce the events of the observability table and keep, for each one, what every
# source saw: passive capture at the router (client side), client TLS keys (to check the
# capture decrypted), client qlog (curl/ngtcp2 or aioquic), and the new lines in the
# server's access.log and error.log (level info, as an operator would run it; the debug log
# is not used here). nginx 1.31.8 has no qlog output.
#   E1 failed handshake (client does not trust the certificate)   h3, h2
#   E2 Retry (quic_retry on)                                       h3
#   E4 stream reset (one of two parallel transfers cancelled)      h3, h2
#   E6 rejected 0-RTT (ticket from a server instance that no longer exists)  h3
# E3 (address change) and E5 (connection close with an error code) reuse the M4 captures.
# Output: results/m5/<event>-<proto>/
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.m3.yml:docker-compose.m4.yml} LAB_NET=10.20
source scripts/lib.sh
R="docker compose exec -T router"
LOGS=../results/m3/server-logs
CURL="curl -s --http3-only"

server_mode() {  # plain | retry  (recreate, not reload: see m4-zerortt.sh)
  rm -f server/m4-extra/*.conf
  [ "$1" = retry ] && echo "quic_retry on;" > server/m4-extra/retry.conf
  docker compose up -d --force-recreate server client >/dev/null 2>&1; sleep 2
}
cleanup() { clear_netem; $R pkill -INT tcpdump 2>/dev/null || true; rm -f server/m4-extra/*.conf; }
trap cleanup EXIT

# ev NAME PROTO CMD...  : run CMD in the client with capture, keys, qlog and log snapshots
ev() {
  local name=$1 proto=$2; shift 2
  local O=/results/m5/$name-$proto H=../results/m5/$name-$proto
  $R rm -rf $O; mkdir -p "$H/qlog"
  local a e; a=$(wc -l < $LOGS/access.log); e=$(wc -l < $LOGS/error.log)
  docker compose exec -d router tcpdump -i "$RIF_CLIENT" -s 0 -U -w $O/capture.pcap "host $LAB_NET.1.10 and port 443"
  sleep 1
  docker compose exec -T -e SSLKEYLOGFILE=$O/keys.log -e QLOGDIR=$O/qlog -e O=$O client sh -c "$*" 2>&1 | tee "$H/client.txt" || true
  sleep 1.5; $R pkill -INT tcpdump || true; sleep 0.5
  tail -n +$((a + 1)) $LOGS/access.log > "$H/access.txt"
  tail -n +$((e + 1)) $LOGS/error.log  > "$H/error.txt"
  echo "== $name-$proto: $(wc -l < "$H/access.txt") access lines, $(wc -l < "$H/error.txt") error lines"
}

server_mode plain
set_netem 50 0

# E1: no --cacert, so the lab certificate is not trusted and the client aborts the handshake
ev e1-failed-handshake h3 "$CURL -o /dev/null -w 'exit=%{exitcode} %{errormsg}\n' https://server.lab/small.html?m5=e1"
ev e1-failed-handshake h2 "curl -s --http2 -o /dev/null -w 'exit=%{exitcode} %{errormsg}\n' https://server.lab/small.html?m5=e1"

# E4: two transfers on one connection; big.bin is cancelled after 1.5 s (8 Mbit/s, so it
# cannot finish), obj/1.txt completes
RATE=8mbit LIMIT=100 set_netem 50 0
for p in h3 h2; do
  f=--http2; [ $p = h3 ] && f=--http3-only
  w="-w '%{url} code=%{http_code} exit=%{exitcode} new_conns=%{num_connects}\n'"
  ev e4-stream-reset $p "curl -s --cacert /certs/ca.crt $f -Z -o /dev/null --max-time 1.5 $w https://server.lab/big.bin?m5=e4 \
     --next -s --cacert /certs/ca.crt $f -o /dev/null $w https://server.lab/obj/1.txt?m5=e4"
done
set_netem 50 0

# E6: ticket saved, server recreated (new ticket keys), 0-RTT attempt with the old ticket
Z="python3 /scripts/m4_zerortt.py"
docker compose exec -T client $Z "https://server.lab/small.html?m5=e6-ticket" --save-ticket /results/m5-ticket.bin >/dev/null
server_mode plain
ev e6-rejected-0rtt h3 "$Z https://server.lab/small.html?m5=e6 --ticket /results/m5-ticket.bin --zero-rtt --keylog \$O/keys.log --qlog \$O/qlog"
$R rm -f /results/m5-ticket.bin

# E2: Retry
server_mode retry
set_netem 50 0
ev e2-retry h3 "$CURL --cacert /certs/ca.crt -o /dev/null -w 'exit=%{exitcode} code=%{http_code}\n' https://server.lab/small.html?m5=e2"
server_mode plain
