#!/usr/bin/env bash
# Agent Gates - full pipeline. Probes, then rebuilds the static site.
set -uo pipefail
cd "$(dirname "$0")"

echo "== Agent Gates run $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
echo "-- signup surfaces --"
python3 probe_signup.py || echo "WARN: signup probe failed"
echo "-- standards census --"
python3 probe_standards.py || echo "WARN: census failed"
echo "-- build site --"
python3 build_site.py || { echo "FATAL: build failed"; exit 1; }

if [ "${1:-}" = "--publish" ]; then
  echo "-- publish --"
  if command -v surge >/dev/null 2>&1; then
    cp -f data/signup_gates.json data/signup_gates.csv \
          data/standards_census.json data/standards_census.csv \
          fieldnotes.json web/data/ 2>/dev/null || true
    surge ./web agentgates.surge.sh
  else
    echo "surge not installed; site left in web/"
  fi
fi
echo "== done =="
