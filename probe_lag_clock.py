#!/usr/bin/env python3
"""Read the two download counts at the two moments that tell two stories apart.

What is known: three deliberate downloads at 2026-09-12T20:05:41Z, 20:08:03Z and
20:10:41Z were all acknowledged by the read at 2026-09-13T11:01:41Z, with latencies of
14.93 h, 14.89 h and 14.85 h. Two different machines produce that same pattern:

  A. a fixed delay of about fifteen hours after each download
  B. one refresh a day, which happened to fall at about 11:01Z

Two further deliberate downloads of the scripted asset were made after that read -
11:01:53Z and 11:07:31Z - and neither can appear in a count that has not refreshed since.
So the count of that asset is 4 now, and:

  A. it reaches 6 by about 2026-09-14T02:07Z
  B. it stays at 4 until about 2026-09-14T11:01Z, then reaches 6

Read it at both moments, write the readings down, and let the next run say which happened.
This script makes no claim of its own: it is a clock with a clipboard, and it runs whether
or not anybody is awake to watch it.

Usage: probe_lag_clock.py [--label NAME] [--expect "the prediction this read tests"]
Writes one JSON object per line to data/logs/i2_lag_clock.jsonl
"""
import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

REPO = "Atheistam/agentgates"
TAG = "readership-bundle"
SCRIPTED_ASSET = "agentgates-dataset.json"
BROWSER_ASSET = "agentgates-probe-browser.json"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "logs", "i2_lag_clock.jsonl")
UA = "agentgates-lag-clock/1.0 (+https://agentgates.surge.sh; reads a public number)"

# The downloads that were waiting for a refresh when the two predictions were written.
FIRST_ANCHOR = datetime(2026, 9, 13, 11, 1, 53, tzinfo=timezone.utc)
LAST_ANCHOR = datetime(2026, 9, 13, 11, 7, 31, tzinfo=timezone.utc)
COUNT_BEFORE = 4
COUNT_AFTER = 6
BATCH_MOMENT = datetime(2026, 9, 14, 11, 1, 0, tzinfo=timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def counts():
    """The public release, read without a token: anybody can do this."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/tags/%s" % (REPO, TAG),
        headers={"Accept": "application/vnd.github+json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        rel = json.loads(r.read().decode())
    return {a["name"]: a.get("download_count") for a in rel.get("assets", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="unlabelled")
    ap.add_argument("--expect", default="",
                    help="the prediction this reading is here to test")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    t = now_utc()
    row = {"at": now_iso(), "label": a.label, "expect": a.expect,
           "deliberate_downloads_waiting": ["2026-09-13T11:01:53Z", "2026-09-13T11:07:31Z"],
           "count_before_they_were_made": COUNT_BEFORE}
    try:
        c = counts()
        row["counts"] = c
        row["http"] = 200
        s = c.get(SCRIPTED_ASSET)
        h_fixed = (t - FIRST_ANCHOR).total_seconds() / 3600.0
        past_batch = t >= BATCH_MOMENT
        row["hours_since_first_waiting_download"] = round(h_fixed, 2)
        row["hours_since_last_waiting_download"] = round(
            (t - LAST_ANCHOR).total_seconds() / 3600.0, 2)
        if s is None:
            row["reading"] = "no count for the scripted asset: %r" % (c,)
        elif s > COUNT_BEFORE:
            if h_fixed < 14.85:
                row["reading"] = ("the count moved to %s only %.2f h after the first waiting "
                                  "download, faster than any latency measured so far: a third "
                                  "possibility, not yet a conclusion" % (s, h_fixed))
            else:
                row["reading"] = ("the count moved to %s: a fixed delay of about fifteen hours "
                                  "fits, and a single daily refresh was not needed to explain "
                                  "it" % s)
        elif s == COUNT_BEFORE:
            if not past_batch and h_fixed >= 15.05:
                row["reading"] = ("still %s %.2f h after the first waiting download: a fixed "
                                  "delay of about fifteen hours would have moved it by now, so "
                                  "this favours one refresh a day - and date the refresh at "
                                  "about 11:01Z tomorrow" % (s, h_fixed))
            elif not past_batch:
                row["reading"] = ("still %s after %.2f h: inside the lag window, so this "
                                  "reading says nothing yet" % (s, h_fixed))
            else:
                row["reading"] = ("still %s at or past the expected refresh moment: neither "
                                  "story fits; the counter may have stopped, or the "
                                  "release may have been republished" % s)
        else:
            row["reading"] = ("the count is below the %d downloads made before it was read: "
                              "the counter has lost counts, which no latency explains"
                              % COUNT_BEFORE)
    except Exception as e:
        row["http"] = None
        row["error"] = str(e)[:200]
        row["reading"] = "the read failed; a failed read is not a zero"
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row))


if __name__ == "__main__":
    main()
