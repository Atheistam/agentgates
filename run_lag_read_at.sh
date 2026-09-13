#!/bin/bash
# Sleep until an absolute UTC moment, then read the download counts and write them down.
#
#   run_lag_read_at.sh 2026-09-14T02:20:00Z fixed_delay_due "what this read is testing"
#
# Started detached, this keeps measuring while nobody is awake to run it. Every reading is
# appended to data/logs/i2_lag_clock.jsonl with the moment it was actually taken, so the run
# that comes after can decide from evidence instead of describing an intention.
set -u
cd "$(dirname "$0")"
until_iso="$1"; label="$2"; expect="${3:-}"
S=$(python3 - "$until_iso" <<'PY'
import sys
from datetime import datetime, timezone
t = datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
print(max(0, int((t - datetime.now(timezone.utc)).total_seconds())))
PY
)
mkdir -p data/logs
echo "[$(date -u +%FT%TZ)] armed for $label at $until_iso (${S}s)" >> data/logs/lag_reads.out
sleep "$S"
{
  echo "--- $label at $(date -u +%FT%TZ) ---"
  python3 probe_lag_clock.py --label "$label" --expect "$expect" 2>&1
} >> data/logs/lag_reads.out
