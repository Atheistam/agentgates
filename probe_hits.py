#!/usr/bin/env python3
"""Agent Gates - read the page-load counters and append to a series.

The census found that a clone count and a page-load count are different facts,
and that only one of them means a person looked at anything. hits.sh is the only
readership instrument this project has that a visitor triggers by merely loading
a page, so it is read on a schedule and kept as a time series rather than quoted
once and forgotten.

Appends one row per host to data/hits_series.json. Never rewrites history.
"""
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SERIES = os.path.join(DATA, "hits_series.json")

HOSTS = [
    ("surge", "https://hits.sh/agentgates.surge.sh.svg?style=flat&label=page%20loads"),
    ("github-pages", "https://hits.sh/atheistam.github.io/agentgates.svg"),
]

NUM = re.compile(r"aria-label=\"[^\"]*?: (\d+)\"")


def read(url):
    req = urllib.request.Request(url, headers={"User-Agent": "agentgates-census/1.0 (+%s)"
                                               % "https://agentgates.surge.sh"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    m = NUM.search(body)
    return int(m.group(1)) if m else None


def main():
    try:
        series = json.load(open(SERIES))
    except Exception:
        series = []
    row: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, url in HOSTS:
        try:
            row[name] = read(url)
        except Exception as e:
            row[name] = None
            row["error_%s" % name] = str(e)[:120]
    prev = series[-1] if series else {}
    series.append(row)
    json.dump(series, open(SERIES, "w"), indent=2)
    delta = ""
    if prev:
        d = [(k, row.get(k), prev.get(k)) for k in ("surge", "github-pages")
             if isinstance(row.get(k), int) and isinstance(prev.get(k), int)]
        delta = " (" + ", ".join("%s %+d" % (k, v - p) for k, v, p in d) + ")" if d else ""
    print(json.dumps(row, sort_keys=True) + delta)
    print("series rows: %d -> %s" % (len(series), SERIES))


if __name__ == "__main__":
    main()
