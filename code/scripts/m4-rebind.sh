#!/usr/bin/env bash
# M4a: NAT rebinding. The router source-NATs the client (10.20.1.10) to
# 10.20.2.254:40001 on the server side. In the middle of a download (8 Mbit/s bottleneck)
# of big.bin the NAT mapping is changed to port 40002 and the conntrack entry is
# deleted, as a home NAT does when a mapping times out. Run once over HTTP/3
# (should survive, with path validation) and once over HTTP/2 (TCP, should break).
# Captures both router interfaces; client TLS keys and qlog go to results/m4/rebind-<proto>/.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.m3.yml:docker-compose.m4.yml} LAB_NET=10.20
source scripts/lib.sh
R="docker compose exec -T router"
REBIND_AT=${REBIND_AT:-4}   # seconds into the transfer; "none" = baseline without rebinding
REPS=${REPS:-1}

nat_port() {  # (re)create our NAT table with one source port
  $R sh -c "nft delete table ip lab 2>/dev/null; nft -f - <<NFT
table ip lab {
  chain post {
    type nat hook postrouting priority srcnat; policy accept;
    oifname \"$RIF_SERVER\" ip saddr $LAB_NET.1.10 meta l4proto { tcp, udp } th dport 443 snat to $LAB_NET.2.254:$1
  }
}
NFT"
}
cleanup() { clear_netem; $R sh -c "nft delete table ip lab; pkill -INT tcpdump" 2>/dev/null || true; }
trap cleanup EXIT
# 8 Mbit/s: 10 MiB takes ~11 s of continuous sending. Queue of 100 packets (~150 ms at
# 8 Mbit/s): with the default 2000 the queue holds ~3 s of data and the server's
# PATH_CHALLENGE waits behind it, which measures the lab buffer, not QUIC.
RATE=8mbit LIMIT=100 set_netem 50 0

for rep in $(seq ${REP0:-1} $((${REP0:-1}+REPS-1))); do for proto in ${PROTOS:-h3 h2}; do
  flag=--http2; [ $proto = h3 ] && flag=--http3-only
  tag=$proto-$REBIND_AT-$rep; [ "$REBIND_AT" = none ] && tag=$proto-base-$rep
  OUT=/results/m4/rebind-$tag
  $R sh -c "rm -rf $OUT; mkdir -p $OUT/qlog"
  nat_port 40001
  $R conntrack -F >/dev/null 2>&1 || true
  docker compose exec -d router tcpdump -i "$RIF_CLIENT" -s 0 -U -w $OUT/client-side.pcap "host $LAB_NET.1.10 and port 443"
  docker compose exec -d router tcpdump -i "$RIF_SERVER" -s 0 -U -w $OUT/server-side.pcap "host $LAB_NET.2.10 and port 443"
  sleep 1
  docker compose exec -T -e SSLKEYLOGFILE=$OUT/keys.log -e QLOGDIR=$OUT/qlog client \
    curl -s --cacert /certs/ca.crt $flag --max-time 40 -o /dev/null \
    -w "$tag result: http=%{http_version} code=%{http_code} bytes=%{size_download} time=%{time_total}s exit=%{exitcode} err=%{errormsg}\n" \
    https://server.lab/big.bin > >(tee -a ../results/m4/curl-results.txt) &
  cpid=$!
  if [ "$REBIND_AT" != none ]; then
    sleep "$REBIND_AT"
    nat_port 40002
    $R conntrack -D -s $LAB_NET.1.10 >/dev/null 2>&1
    echo "$(date +%T.%N) $tag rebinding 40001 -> 40002" >> ../results/m4/rebind-events.txt
  fi
  wait $cpid || true
  sleep 1
  $R pkill -INT tcpdump || true
  sleep 1
done; done
tail -n 2 ../results/m3/server-logs/access.log
