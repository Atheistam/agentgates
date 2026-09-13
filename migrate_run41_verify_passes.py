#!/usr/bin/env python3
"""Give the write re-read a memory, and seed it with the passes that already happened.

The problem this fixes, found the hard way in run 41: probe_write_verify.py has no argument
parser, so `python3 probe_write_verify.py --help` does not print help - it runs a full
re-read pass and overwrites data/write_verify.json in place. The pass it overwrote was the
T+5.85 h one, the only record of what eleven anonymous writes looked like six hours after
they were made. Nothing was actually lost here (it is in git, commit 1327a67, and was
recovered from there), but an instrument whose only output is a single in-place file has no
memory, and an instrument with no memory cannot publish a curve - only a snapshot.

So: every pass from now on lands both at the top level of write_verify.json (the latest
pass, which is what the site reads) and inside its `passes` list (the curve). This script
seeds that list with the two passes that predate it, taken from the commits that hold them,
so the curve starts at T+2.97 h instead of starting at run 41.

    python3 migrate_run41_verify_passes.py           # report what it would do
    python3 migrate_run41_verify_passes.py --apply   # write data/write_verify.json
"""
import argparse
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "write_verify.json")
WEB = os.path.join(HERE, "web", "data", "write_verify.json")

# Which commit holds which pass. Named explicitly rather than searched, because a pass
# belongs to the commit that published it and "the newest commit that touched this file"
# is a property of git, not of the measurement.
SOURCES = [
    ("621bd71", "run 38: class-aware re-verification"),
    ("1327a67", "run 39: two readership counters, each with its own controls"),
]


def from_commit(rev):
    blob = subprocess.run(["git", "show", "%s:data/write_verify.json" % rev],
                          cwd=HERE, capture_output=True, text=True, check=True).stdout
    return json.loads(blob)


def pass_row(p, label, source):
    """One row of the curve: what the pass found, per service, in the smallest honest form."""
    svc = p.get("services") or {}
    per = {}
    bytes_ = {}
    for name in sorted(svc):
        per[name] = svc[name].get("verdict")
        if svc[name].get("served_bytes") is not None:
            bytes_[name] = svc[name]["served_bytes"]
    row = {
        "label": label,
        "verified_at": p.get("verified_at"),
        "age_hours": p.get("age_hours"),
        "source": source,
        "written": (p.get("summary") or {}).get("written"),
        "still_there": (p.get("summary") or {}).get("still_there"),
        "pass": (p.get("summary") or {}).get("pass"),
        "fail": (p.get("summary") or {}).get("fail"),
        "expired_as_declared": (p.get("summary") or {}).get("expired_as_declared"),
        "not_written": (p.get("summary") or {}).get("not_written"),
        "per_service": per,
        "served_bytes": bytes_,
    }
    return row


def main():
    ap = argparse.ArgumentParser(
        description="Seed data/write_verify.json with a `passes` curve instead of a snapshot.")
    ap.add_argument("--apply", action="store_true", help="write the file")
    args = ap.parse_args()

    current = json.load(open(OUT))
    existing = current.get("passes") or []
    have = {r.get("verified_at") for r in existing}

    rows = list(existing)
    for rev, what in SOURCES:
        p = from_commit(rev)
        if p.get("verified_at") in have:
            continue
        rows.append(pass_row(p, "T+%.2f h" % (p.get("age_hours") or -1), "%s (%s)" % (rev, what)))
    # The pass sitting at the top level of the file right now. It is not in git because it
    # has not been committed yet - and it is the one this run's accident produced.
    if current.get("verified_at") not in {r.get("verified_at") for r in rows}:
        rows.append(pass_row(current, "T+%.2f h" % (current.get("age_hours") or -1),
                             "working tree (pass produced by an unintended invocation)"))
    rows.sort(key=lambda r: r.get("age_hours") if r.get("age_hours") is not None else 0)

    print("curve rows: %d" % len(rows))
    for r in rows:
        print("  %-12s %s  age %6.2f h   pass %s fail %s expired %s   [%s]"
              % (r["label"], r["verified_at"], r["age_hours"] or -1, r["pass"], r["fail"],
                 r["expired_as_declared"], r["source"]))

    current["passes"] = rows
    current["passes_note"] = (
        "one row per re-read of the anonymous writes, earliest first. The top level of this "
        "file is always the LATEST pass; this list is the curve, and a pass can no longer "
        "erase the pass before it. Rows recovered from the commits named in `source`.")
    if not args.apply:
        print("\ndry run: nothing written (pass --apply)")
        return 0
    with open(OUT, "w") as f:
        json.dump(current, f, indent=1, sort_keys=True)
    print("\nwrote %s" % OUT)
    try:
        os.makedirs(os.path.dirname(WEB), exist_ok=True)
        with open(WEB, "w") as f:
            json.dump(current, f, indent=1, sort_keys=True)
        print("mirrored to %s" % WEB)
    except Exception as e:  # noqa: BLE001
        print("WARN: could not mirror into web/data: %s" % e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
