#!/bin/bash
# Poll CDS every 10 min: collect Atlas + ERA5 jobs until nothing is left in "submitted".
cd "$(dirname "$0")/.."
while true; do
  uv run python scripts/fetch_atlas.py collect 2>&1 | grep -E "downloaded|failed|rejected|\{" | tail -3
  uv run python scripts/fetch_era5.py collect 2>&1 | grep -E "compacted|downloaded|failed|rejected|Error|\{" | tail -6
  left=$(python3 -c "import json;import glob;print(sum(1 for f in glob.glob('data/state/*_jobs.json') for j in json.load(open(f)).values() if j['status']=='submitted'))")
  echo "$(date -u +%H:%M) submitted-left=$left"
  [ "$left" = "0" ] && break
  sleep 600
done
