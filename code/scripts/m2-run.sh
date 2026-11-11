#!/usr/bin/env bash
# M2: runs the performance grid. For each (RTT, loss) it sets netem on the router
# and calls m2_runner.py in the client. Results are appended to $OUT (CSV).
# Usage: scripts/m2-run.sh [out.csv] [runs] [rtts] [losses] [workloads]
# Already completed conditions in the CSV are skipped, so it can be resumed.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib.sh
OUT=${1:-m2/raw.csv}; RUNS=${2:-20}
RTTS=${3:-"10 50 100 200"}; LOSSES=${4:-"0 0.5 1 2 5"}; WL=${5:-small,big,multi}
mkdir -p "../results/$(dirname "$OUT")"
trap clear_netem EXIT

done_cond() {  # true if this condition already has all rows
  [ -f "../results/$OUT" ] || return 1
  local n; n=$(awk -F, -v r="$1" -v l="$2" 'NR>1 && $1+0==r+0 && $2+0==l+0' "../results/$OUT" | wc -l)
  local nwl; nwl=$(tr ',' '\n' <<<"$WL" | wc -l)
  [ "$n" -ge $(( RUNS * nwl * 2 )) ]
}

for rtt in $RTTS; do
  for loss in $LOSSES; do
    if done_cond "$rtt" "$loss"; then echo "skip rtt=$rtt loss=$loss"; continue; fi
    set_netem "$rtt" "$loss"
    start=$(date +%s)
    docker compose exec -T client python /scripts/m2_runner.py \
      --rtt "$rtt" --loss "$loss" --runs "$RUNS" --workloads "$WL" --out "/results/$OUT"
    echo "$(date +%H:%M) rtt=$rtt loss=$loss done in $(( $(date +%s) - start ))s"
  done
done
