#!/usr/bin/env bash
# M7: build the submission archive TP1_group10.zip.
#   - results/SHA256SUMS: hash of every file of the full results (~800 MB, not shipped)
#   - a small selection of results/ (see SUBSET below)
#   - the files of this repository that git does not ignore: README.md, code/, docs/
#   - the two report PDFs: REPORT1 and REPORT2 (paths can be overridden)
# Usage (from anywhere): code/scripts/package.sh [output dir]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUTDIR=${1:-$REPO/..}
NAME=TP1_group10
REPORT1=${REPORT1:-$REPO/../${NAME}_report_1.pdf}
REPORT2=${REPORT2:-$REPO/../report_2/report_2.pdf}
cd "$REPO/code"
export COMPOSE_FILE=docker-compose.m3.yml
R="docker compose exec -T router"

# small artefacts only; paths relative to results/
SUBSET="m1 m2 m3/h2.pcap m3/h3.pcap m3/h2-keys.log m3/h3-keys.log m3/qlog-h3
  m3/server-logs/access.log m3/server-logs/error.log
  m4/curl-results.txt m4/rebind-events.txt m4/zerortt-plain m4/zerortt-retry
  m4/zerortt-tooearly m4/zerortt-summary.txt m5 m6"
EXCLUDE="--exclude=m5/e4-stream-reset-h2/capture.pcap --exclude=m5/e4-stream-reset-h3/capture.pcap
  --exclude=*.pcap.tmp --exclude=m6/pc-check.pcap --exclude=m6/pc-keys.log"

SUBSET=$(echo $SUBSET); EXCLUDE=$(echo $EXCLUDE)   # one line each, for sh -c
docker compose up -d router >/dev/null 2>&1
echo "hashing the full results..."
$R sh -c 'cd /results && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS'
echo "  $($R sh -c 'wc -l < /results/SHA256SUMS') files, $($R sh -c 'du -sh /results | cut -f1')"

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
D=$STAGE/$NAME; mkdir -p "$D/results"
# tracked files plus new files that are not ignored (certs, test content and .venv are ignored)
( cd "$REPO" && git ls-files -z -co --exclude-standard README.md code docs | xargs -0 -I{} cp --parents {} "$D/" )
# shellcheck disable=SC2086
$R sh -c "cd /results && tar -cf - $EXCLUDE SHA256SUMS $SUBSET 2>/dev/null" | tar -xf - -C "$D/results"

for pdf in "$REPORT1:${NAME}_report_1.pdf" "$REPORT2:${NAME}_report_2.pdf"; do
  src=${pdf%%:*}; dst=${pdf#*:}
  if [ -f "$src" ]; then cp "$src" "$D/$dst"; else echo "WARNING: $src not found, $dst missing from the archive"; fi
done

rm -f "$OUTDIR/$NAME.zip"
( cd "$STAGE" && python3 -m zipfile -c "$OUTDIR/$NAME.zip" "$NAME" )
echo "wrote $OUTDIR/$NAME.zip ($(du -h "$OUTDIR/$NAME.zip" | cut -f1))"
( cd "$STAGE" && find "$NAME" -maxdepth 1 | sort )
