#!/usr/bin/env bash
# M1 validation: fetch the same URL over HTTP/2 and HTTP/3 through the router,
# capture on the router and check in the capture that each protocol was used.
# Run from code/ with the lab up.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=/results/m1
docker compose exec -T router sh -c "mkdir -p $OUT && rm -f $OUT/*"
docker compose exec -T client sh -c "mkdir -p $OUT/qlog"

# capture on the client-side interface of the router (what a passive observer sees)
docker compose exec -d router tcpdump -i eth0 -s 0 -U -w $OUT/m1.pcap 'host 10.10.1.10 and port 443'
sleep 1

for proto in http2 http3-only; do
  docker compose exec -T -e SSLKEYLOGFILE=$OUT/keys.log -e QLOGDIR=$OUT/qlog client \
    curl -s -o /dev/null --cacert /certs/ca.crt --$proto \
    -w "$proto: version=%{http_version} code=%{http_code} size=%{size_download} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n" \
    https://server.lab/small.html
done
sleep 1
docker compose exec -T router pkill tcpdump || true
sleep 1

echo "--- encrypted view (observer): transport and SNI"
docker compose exec -T router tshark -r $OUT/m1.pcap -q -z conv,tcp -z conv,udp 2>/dev/null | grep -E '<->' || true
docker compose exec -T router tshark -r $OUT/m1.pcap -Y 'tls.handshake.type==1' \
  -T fields -e frame.protocols -e tls.handshake.extensions_server_name -e tls.handshake.extensions_alpn_str 2>/dev/null | sort -u

echo "--- decrypted view (with the client's TLS keys): HTTP requests"
docker compose exec -T router tshark -r $OUT/m1.pcap -o tls.keylog_file:$OUT/keys.log \
  -Y 'http2.headers.path or http3.headers.path' \
  -T fields -e frame.protocols -e http2.headers.path -e http3.headers.path 2>/dev/null | sort -u

echo "--- server log"
tail -n 2 ../results/server-logs/access.log
echo "--- qlog files"; ls ../results/m1/qlog
