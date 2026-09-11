#!/usr/bin/env python3
"""Can this agent audit its own readership?

Readership telemetry lives behind an account. This script tests, non-interactively,
whether the agent holding the repo's push credential can also read that repo's
traffic (views / clones / referrers), and whether the platform's public surfaces
disclose anything without the credential. Every branch is recorded as an outcome,
including the failures - the failures are the finding.
"""
import json, os, subprocess, sys, urllib.request, urllib.error, datetime

OUT = "data/readership_probe.json"
REPO = "Atheistam/agentgates"
res = {
    "probed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "repo": REPO,
    "credential_fill": {},
    "api": {},
    "public": {},
}


def run(cmd, inp=None, t=15):
    try:
        p = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=t)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", ""
    except Exception as e:
        return "ERROR", "", str(e)


# 1. Can we get the credential at all, without a human at the keyboard?
rc, out, err = run(["git", "credential", "fill"], inp="protocol=https\nhost=github.com\n\n")
res["credential_fill"] = {
    "rc": rc,
    "fields": sorted(
        [l.split("=", 1)[0] for l in out.strip().splitlines() if "=" in l]
    ),
    "stderr_tail": err.strip()[-200:],
    "outcome": "obtained" if rc == 0 and "password=" in out else ("timeout" if rc == "TIMEOUT" else "refused"),
}
token = None
for line in out.splitlines():
    if line.startswith("password="):
        token = line.split("=", 1)[1].strip()

# 2. If we have one, ask the API. Record HTTP status verbatim, not a guess.
def api(path):
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentgates-readership-probe",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = json.loads(r.read().decode())
            return {"status": r.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:
        return {"status": "EXC", "error": str(e)[:200]}


if token:
    for name, path in [
        ("views", f"repos/{REPO}/traffic/views"),
        ("clones", f"repos/{REPO}/traffic/clones"),
        ("referrers", f"repos/{REPO}/traffic/popular/referrers"),
        ("paths", f"repos/{REPO}/traffic/popular/paths"),
    ]:
        r = api(path)
        d = {"http_status": r["status"], "count": None, "uniques": None, "detail": None}
        if r["status"] == 200:
            b = r["body"]
            if isinstance(b, list):
                d["detail"] = b
            else:
                d["count"] = b.get("count")
                d["uniques"] = b.get("uniques")
                d["detail"] = b.get("views") or b.get("clones")
        else:
            d["detail"] = r.get("error")
        res["api"][name] = d
else:
    res["api"] = {"skipped": "no credential obtainable without a human at the keyboard"}

# 3. What does the platform say publicly, with no credential? (unauthenticated)
pub = api(f"repos/{REPO}")
res["public"]["repo"] = {
    "http_status": pub["status"],
    "stargazers": pub["body"].get("stargazers_count") if pub["status"] == 200 else None,
    "forks": pub["body"].get("forks_count") if pub["status"] == 200 else None,
    "watchers": pub["body"].get("subscribers_count") if pub["status"] == 200 else None,
    "error": pub.get("error"),
}

# 4. The only legible instrument: a page-view badge with no account behind it.
# Read it repeatedly and record what the reads do to it. hits.sh counts requests
# to the badge image, so an audit that fetches the badge is itself a page load.
import re
import time


def read_counter():
    req = urllib.request.Request(
        "https://hits.sh/agentgates.surge.sh.svg?style=flat&label=page%20loads",
        headers={"User-Agent": "agentgates-readership-probe", "Accept": "image/svg+xml,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            svg = r.read().decode("utf-8", "replace")
    except Exception as e:
        return {"http_status": "EXC", "error": str(e)[:200], "value": None}
    m = re.search(r'aria-label="[^"]*?([0-9][0-9,]*)', svg) or re.search(r'>([0-9][0-9,]*)<', svg)
    return {"http_status": 200, "value": int(m.group(1).replace(",", "")) if m else None}


prev = None
if os.path.exists(OUT):
    try:
        prev = (json.load(open(OUT)).get("counter") or {}).get("values", [None])[-1]
    except Exception:
        prev = None
reads = []
for i in range(3):
    reads.append(read_counter())
    if i < 2:
        time.sleep(2)
vals = [r["value"] for r in reads]
res["counter"] = {
    "endpoint": "https://hits.sh/agentgates.surge.sh.svg?style=flat&label=page%20loads",
    "readable": all(r["http_status"] == 200 for r in reads),
    "values": vals,
    "previous_probe_last_value": prev,
    "delta_since_previous_probe": (vals[-1] - prev) if (prev is not None and vals[-1] is not None) else None,
    "delta_note": "The delta cannot be read as readers. Every fetch of this badge - including "
                  "this probe's own three reads and any verification fetch of the page - is a "
                  "page load by the counter's definition.",
    "increment_per_read": [b - a for a, b in zip(vals, vals[1:]) if None not in (a, b)],
    "self_defeating": (len(set(v for v in vals if v is not None)) > 1),
}

with open(OUT, "w") as f:
    json.dump(res, f, indent=2)
print(json.dumps(res, indent=2)[:4000])
