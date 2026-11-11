#!/usr/bin/env bash
# M3: one HTTP/2 and one HTTP/3 connection, each with two requests on the same
# connection, captured at the router (client side) with RTT 50 ms and no loss.
# Saves pcap, TLS key log (client) and qlog (HTTP/3) per protocol in results/m3/.
# Runs on the second lab copy so it does not disturb M2.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=docker-compose.m3.yml LAB_NET=10.20
source scripts/lib.sh
OUT=/results/m3
trap clear_netem EXIT
set_netem 50 0

for proto in h2 h3; do
  flag=--http2; [ $proto = h3 ] && flag=--http3-only
  docker compose exec -T router sh -c "rm -f $OUT/$proto.pcap $OUT/$proto-keys.log; mkdir -p $OUT/qlog-$proto"
  docker compose exec -d router tcpdump -i "$RIF_CLIENT" -s 0 -U -w $OUT/$proto.pcap "host $LAB_NET.1.10 and port 443"
  sleep 1
  docker compose exec -T -e SSLKEYLOGFILE=$OUT/$proto-keys.log -e QLOGDIR=$OUT/qlog-$proto client \
    curl -s --cacert /certs/ca.crt $flag -o /dev/null -o /dev/null \
    -w "$proto %{http_version} %{http_code} %{url} connects=%{num_connects}\n" \
    https://server.lab/small.html https://server.lab/obj/1.txt
  sleep 1
  docker compose exec -T router pkill -INT tcpdump || true
  sleep 1
done
tail -n 4 ../results/m3/server-logs/access.log
ls -la ../results/m3
