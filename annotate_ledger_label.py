#!/usr/bin/env python3
"""Correct a run label in the ledger without rewriting what it originally said.

probe_counter.py carried `RUN = 40` as a hand-bumped constant from run 40 to run 43, so
the entry that actually decided a movement - the positive control download of
2026-09-13T20:07:27Z, which moved the counter 12 -> 13 and is the only movement
campaign4-long has - is labelled "run 40". The run that made it was run 43.

The fix belongs in the code (done: RUN now reads the environment, then the state file).
The record itself is not rewritten: overwriting a wrong label would destroy the evidence
that the label was wrong, which is the only thing that makes the ledger worth reading. The
original `note` stays exactly as written; the correction is added beside it.

Idempotent. Run: python3 annotate_ledger_label.py
"""

import json
import os
import sys

import probe_counter as pc

TARGET_AT = "2026-09-13T20:07:27Z"
WRITTEN_AS = "run 40"
ACTUALLY = "run 43"

CORRECTION = (
    "the run label above was wrong as written: probe_counter.py carried a hand-bumped "
    "RUN constant that stopped at 40, so the entry made by run 43 says run 40. The run "
    "number is one field among many and it is the one a reader uses to find the run that "
    "produced this download; a stale label there is a defect, not a cosmetic one. Fixed "
    "in code by run 44 (RUN now reads the environment, then the agent's state file); the "
    "original label is preserved here rather than overwritten."
)


def main():
    st = pc.load(pc.STORE, {})
    led = st.get("i2_ledger")
    if not isinstance(led, list):
        print("no ledger in %s" % pc.STORE)
        return 1

    hits = 0
    for e in led:
        if not isinstance(e, dict):
            continue
        note = str(e.get("note") or "")
        if WRITTEN_AS not in note:
            continue
        if e.get("at") == TARGET_AT:
            e.setdefault("run_label_as_written", WRITTEN_AS)
            e["run_label_corrected"] = ACTUALLY
            e["correction"] = CORRECTION
            hits += 1

    if not hits:
        print("nothing to correct (already annotated, or the entry is gone)")
        return 0

    # Back up before writing: this file is the project's only record of who downloaded
    # what, and a read-modify-write is the one operation that can erase it.
    backup = pc.STORE + ".bak-annotate"
    with open(pc.STORE) as fh:
        original = fh.read()
    with open(backup, "w") as fh:
        fh.write(original)

    tmp = pc.STORE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2, sort_keys=True)
    os.replace(tmp, pc.STORE)

    print("annotated %d entr(ies); backup at %s" % (hits, os.path.basename(backup)))
    for e in led:
        if e.get("at") == TARGET_AT:
            print("  at=%s note=%r corrected=%s"
                  % (e.get("at"), e.get("note"), e.get("run_label_corrected")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
