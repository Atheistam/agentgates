#!/usr/bin/env python3
"""Tell the search engines, and record whether we were actually believed.

WHY
    The distribution-surface census (data/distribution_surfaces.json) found that
    IndexNow accepted an anonymous submission and answered HTTP 202 - while the key
    file it requires at the domain root answered 404. That is this project's own
    thesis turned on itself: a 202 that means nothing, because the accepting party
    never checked. This script closes the loop:

      1. host the key file it asks for,
      2. confirm the key file is publicly readable BEFORE submitting,
      3. submit, and
      4. write down the status, the key-file status and the URL count together.

    A submission nobody can attribute is logged as such. The point is not to have
    submitted; it is to know whether the submission could have been honoured.

URLS
    The URL list is read out of the published sitemap.xml rather than kept here, so
    there is exactly one list of what this site claims to publish.

    python3 distribute.py            # verify key file, submit, log
    python3 distribute.py --dry-run  # show what would be submitted
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DATA = os.path.join(HERE, "data")
KEYFILE = os.path.join(DATA, "indexnow_key.txt")
LOG = os.path.join(DATA, "indexnow_submissions.json")
SITE = "https://agentgates.surge.sh"
HOST = "agentgates.surge.sh"
ENDPOINT = "https://api.indexnow.org/indexnow"
UA = "AgentGatesBot/1.0 (+%s; measurement)" % SITE


def key() -> str:
    """The IndexNow key, minted once and then kept.

    The key must stay hosted for as long as the submission is claimed to be valid,
    so it is persisted rather than regenerated per run.
    """
    if os.path.exists(KEYFILE):
        k = open(KEYFILE).read().strip()
        if k:
            return k
    k = secrets.token_hex(16)  # 32 hex chars, the format IndexNow asks for
    with open(KEYFILE, "w") as f:
        f.write(k + "\n")
    return k


def head(url: str, timeout: int = 20):
    """GET just enough to report a status; never raise."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, type(e).__name__


def sitemap_urls() -> list[str]:
    path = os.path.join(WEB, "sitemap.xml")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if "<loc>" in line:
            out.append(line.split("<loc>", 1)[1].split("</loc>", 1)[0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    k = key()
    key_path = os.path.join(WEB, k + ".txt")
    if not os.path.exists(key_path):
        with open(key_path, "w") as f:
            f.write(k + "\n")
    key_url = "%s/%s.txt" % (SITE, k)

    urls = sitemap_urls()
    print("IndexNow key: %s" % key_url)
    print("URLs from sitemap.xml: %d" % len(urls))
    for u in urls:
        print("  %s" % u)

    if args.dry_run:
        return 0

    served, body = head(key_url)
    print("key file served: HTTP %s %s" % (served, body.strip()[:40]))

    if not urls:
        print("no sitemap.xml - nothing to submit")
        return 1

    payload = json.dumps({
        "host": HOST,
        "key": k,
        "keyLocation": key_url,
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
    status, note = 0, ""
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status = r.status
            note = r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        note = e.read(400).decode("utf-8", "replace")
    except Exception as e:
        note = type(e).__name__

    # A 202 is only worth reporting next to the key-file status that makes it
    # honourable. Taken alone it is the kind of number this project exists to
    # discredit.
    honoured = status in (200, 202) and served == 200
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": ENDPOINT,
        "http_status": status,
        "response": note.strip()[:200],
        "key_location": key_url,
        "key_file_status": served,
        "urls_submitted": len(urls),
        "attributable": honoured,
    }
    log = []
    if os.path.exists(LOG):
        try:
            log = json.load(open(LOG))
        except Exception:
            log = []
    log.append(rec)
    with open(LOG, "w") as f:
        json.dump(log, f, indent=2)
        f.write("\n")

    print("submit: HTTP %s (%s)" % (status, note.strip()[:80] or "no body"))
    print("attributable submission: %s" % ("yes" if honoured else "NO"))
    print("logged to %s (entry %d)" % (os.path.relpath(LOG, HERE), len(log)))
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    raise SystemExit(main())
