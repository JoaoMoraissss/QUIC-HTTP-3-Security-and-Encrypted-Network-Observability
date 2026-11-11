#!/usr/bin/env bash
# M3: writes the observer view (pcap only) and the endpoint view (pcap + client TLS keys)
# of both captures to results/m3/*.txt. Note that Wireshark decrypts QUIC Initial
# packets even without keys: their keys derive from the client's first DCID (RFC 9001 §5.2).
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=docker-compose.m3.yml
T() { docker compose exec -T router tshark "$@" 2>/dev/null; }
D=/results/m3
T -r $D/h2.pcap -T fields -E header=y -E separator=';' -e frame.number -e frame.time_relative -e ip.src \
  -e frame.len -e tcp.flags.str -e tcp.seq -e tcp.ack -e tcp.len -e tls.record.content_type -e tls.record.length \
  -e tls.handshake.type -e tls.handshake.extensions_server_name -e tls.handshake.extensions_alpn_str > ../results/m3/h2-observer.txt
T -r $D/h2.pcap -o tls.keylog_file:$D/h2-keys.log -T fields -E header=y -E separator=';' -e frame.number -e ip.src \
  -e tls.handshake.type -e http2.type -e http2.streamid -e http2.headers.path -e http2.headers.status > ../results/m3/h2-endpoint.txt
T -r $D/h3.pcap -o tls.keylog_file: -T fields -E header=y -E separator=';' -e frame.number -e frame.time_relative -e ip.src \
  -e frame.len -e quic.header_form -e quic.long.packet_type -e quic.version -e quic.dcid -e quic.scid -e quic.spin_bit \
  -e tls.handshake.type -e tls.handshake.extensions_server_name -e tls.handshake.extensions_alpn_str > ../results/m3/h3-observer.txt
T -r $D/h3.pcap -o tls.keylog_file:$D/h3-keys.log -T fields -E header=y -E separator=';' -e frame.number -e ip.src \
  -e quic.long.packet_type -e quic.packet_number -e quic.frame_type -e tls.handshake.type -e quic.stream.stream_id \
  -e http3.frame_type -e http3.headers.path -e http3.headers.status -e quic.cc.error_code > ../results/m3/h3-endpoint.txt
wc -l ../results/m3/*.txt
