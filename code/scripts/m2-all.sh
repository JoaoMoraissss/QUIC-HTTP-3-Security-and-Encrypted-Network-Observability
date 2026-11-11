#!/usr/bin/env bash
# Runs the whole M2 campaign in order. Resumable (completed conditions are skipped).
# Log: results/m2/campaign.log
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== $(date) buffer experiment";  ./scripts/m2-buffer.sh 10
echo "== $(date) small + multi grid"; ./scripts/m2-run.sh m2/raw-small-multi.csv 20 "10 50 100 200" "0 0.5 1 2 5" small,multi
echo "== $(date) big grid";           ./scripts/m2-run.sh m2/raw-big.csv 10 "10 50 100 200" "0 0.5 1 2" big
echo "== $(date) M2 campaign finished"
