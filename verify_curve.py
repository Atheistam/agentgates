#!/usr/bin/env python3
"""The shape of one row of the write re-read curve, in one place.

Run 41 lost a measurement to a harness that had no argument parser: asking it for help ran
a full pass and overwrote the file holding the previous pass. Recovering it from git was
possible, but the fix is not "remember to use git" - it is that a pass must append a row to
a curve instead of replacing a snapshot.

Both the one-off seeding script (migrate_run41_verify_passes.py) and the live instrument
(probe_write_verify.py) build their rows here, so the two cannot drift into different
schemas for the same curve.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def pass_row(p, label=None, source=None):
    """Reduce a full pass to the smallest honest row: the counts, the verdicts, the sizes.

    Keeps per-service verdicts and served byte counts - the two things that let a reader
    see not just that eleven writes survived but which ones, and whether the bytes moved.
    """
    svc = p.get("services") or {}
    per = {}
    bytes_ = {}
    for name in sorted(svc):
        per[name] = svc[name].get("verdict")
        if svc[name].get("served_bytes") is not None:
            bytes_[name] = svc[name]["served_bytes"]
    age = p.get("age_hours")
    s = p.get("summary") or {}
    return {
        "label": label or ("T+%.2f h" % age if age is not None else "T+? h"),
        "verified_at": p.get("verified_at"),
        "age_hours": age,
        "source": source,
        "written": s.get("written"),
        "still_there": s.get("still_there"),
        "pass": s.get("pass"),
        "fail": s.get("fail"),
        "expired_as_declared": s.get("expired_as_declared"),
        "not_written": s.get("not_written"),
        "per_service": per,
        "served_bytes": bytes_,
    }


def merge_passes(previous_pass, new_pass, source=None, new_label=None):
    """Previous curve rows plus a row for `new_pass`, earliest first, no duplicates.

    `previous_pass` is the pass that was sitting at the top level of the file before this
    one ran; if it was not already recorded as a row, it becomes one. That is the whole
    point: whatever was here before this run is still here after it.
    """
    rows = list((previous_pass or {}).get("passes") or [])
    seen = {r.get("verified_at") for r in rows}
    if previous_pass and previous_pass.get("verified_at") not in seen:
        rows.append(pass_row(previous_pass, source="previous pass, recorded when it was displaced"))
        seen.add(previous_pass.get("verified_at"))
    if new_pass and new_pass.get("verified_at") not in seen:
        rows.append(pass_row(new_pass, label=new_label, source=source or "this pass"))
    rows.sort(key=lambda r: r.get("age_hours") if r.get("age_hours") is not None else 0)
    return rows


def read_committed(rev, path="data/write_verify.json", cwd=None):
    """A pass as it was committed, for seeding a curve with measurements that predate it."""
    import subprocess
    blob = subprocess.run(["git", "show", "%s:%s" % (rev, path)],
                          cwd=cwd or HERE, capture_output=True, text=True, check=True).stdout
    return json.loads(blob)
