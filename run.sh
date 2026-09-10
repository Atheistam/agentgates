#!/usr/bin/env bash
# Agent Gates - full pipeline. Probes, validates, rebuilds the static site,
# and (with --publish) pushes to both public hosts.
set -uo pipefail
cd "$(dirname "$0")"

echo "== Agent Gates run $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
echo "-- signup surfaces --"
python3 probe_signup.py || echo "WARN: signup probe failed"
echo "-- standards census (content-validated inline) --"
python3 probe_standards.py || echo "WARN: census failed"
echo "-- counter-check the census flag URLs --"
python3 validate_census.py || echo "WARN: cross-check failed"
echo "-- build site --"
python3 build_site.py || { echo "FATAL: build failed"; exit 1; }

if [ "${1:-}" = "--publish" ]; then
  echo "-- publish: surge --"
  if command -v surge >/dev/null 2>&1; then
    surge ./web agentgates.surge.sh | tail -3
  else
    echo "surge not installed; site left in web/"
  fi
  echo "-- publish: GitHub Pages --"
  rm -rf docs && cp -r web docs && rm -f docs/CNAME
  git add -A
  if git diff --cached --quiet; then
    echo "no changes to commit"
  else
    git -c user.name="Atheistam" -c user.email="vagopopulo@gmail.com" \
        commit -q -m "data refresh $(date -u +%Y-%m-%dT%H:%M:%SZ)" && \
        git push -q origin main && echo "pushed"
  fi
fi
echo "== done =="
