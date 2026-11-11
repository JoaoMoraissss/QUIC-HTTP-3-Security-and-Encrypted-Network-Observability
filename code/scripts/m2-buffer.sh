#!/usr/bin/env bash
# M2 side experiment: 10 MB object without loss, nginx http3_stream_buffer_size
# at its default (64k) and at the lab value (4m). HTTP/2 is measured too as reference.
# Usage: scripts/m2-buffer.sh [runs]
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS=${1:-10}
set_buf() {
  docker compose exec -T server sh -c \
    "sed -i 's/http3_stream_buffer_size [0-9a-z]*;/http3_stream_buffer_size $1;/' /etc/nginx/nginx.conf && nginx -s reload"
  sleep 2
}
trap 'set_buf 4m' EXIT
for b in 64k 4m; do
  set_buf "$b"
  ./scripts/m2-run.sh "m2/buffer-$b.csv" "$RUNS" "10 50 100 200" "0" big
done
