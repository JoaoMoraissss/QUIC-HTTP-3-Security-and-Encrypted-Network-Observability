#!/usr/bin/env bash
# Writes the exact software versions used in the lab to versions.txt
cd "$(dirname "$0")/.."
{
  echo "# generated $(date -I) by scripts/versions.sh"
  echo "host kernel: $(uname -r)"; echo "docker: $(docker version -f '{{.Server.Version}}')"
  docker compose exec -T server nginx -v 2>&1
  docker compose exec -T server sh -c 'nginx -V 2>&1 | grep -o "built with OpenSSL [0-9.]*"'
  docker compose exec -T client curl -V | head -1
  docker compose exec -T client python -c 'import aioquic; print("aioquic", aioquic.__version__)'
  docker compose exec -T router tshark -v | head -1
  docker compose exec -T router tcpdump --version 2>&1 | head -1
  docker compose exec -T router tc -V
} > versions.txt
cat versions.txt
