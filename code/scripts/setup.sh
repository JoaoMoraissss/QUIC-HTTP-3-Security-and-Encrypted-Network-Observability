#!/usr/bin/env bash
# Generates the lab CA, the server certificate and the test content.
# Run once from code/ before "docker compose up".
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p certs server/www/obj ../results/server-logs
if [ ! -f certs/server.crt ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 365 \
    -subj "/CN=QUIC Lab CA" -keyout certs/ca.key -out certs/ca.crt
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -subj "/CN=server.lab" -keyout certs/server.key -out certs/server.csr
  openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key \
    -CAcreateserial -days 365 -out certs/server.crt \
    -extfile <(printf "subjectAltName=DNS:server.lab\nextendedKeyUsage=serverAuth")
  chmod 644 certs/server.key   # nginx in the container reads it as another user
fi

# workloads: one small page, one 10 MB object, fifty small objects
head -c 1024 /dev/urandom | base64 -w 76 > server/www/small.html
[ -f server/www/big.bin ] || head -c 10485760 /dev/urandom > server/www/big.bin
for i in $(seq 1 50); do head -c 2048 /dev/urandom | base64 -w 76 > server/www/obj/$i.txt; done
echo "certificates and content ready"
