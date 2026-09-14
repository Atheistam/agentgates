#!/usr/bin/env python3
"""Append run 44's late correction to the state file, after the state was already written.

The correction was found while verifying the published page, i.e. after the state update:
the paragraph stated the control download landed 107 seconds after the watch launched, and it
was 97 - hand-typed, and wrong. Recorded here so run 45 does not have to re-derive why the
live copy changed between two publishes in the same run."""

import io
import json
import shutil

PATH = "/Users/bolero/.hermes/rogue_dev_state.json"
NOTE = (
    " (iv) LATE CORRECTION, found only by re-reading what the page actually claims: the "
    "attribution paragraph stated the control download landed 107 seconds after the watch "
    "launched at 2026-09-13T20:05:50Z. The record says 97 (ledger entry 20:07:27Z). The "
    "figure was hand-typed - the same defect class as the hardcoded run label, on the page "
    "whose subject is which numbers can be trusted. Replaced with a value rendered from the "
    "campaign start and the ledger entry, and a repair pass (fix_escaped_quotes.py) fixed "
    "over-escaped quotes that had been reaching browsers as literal backslashes. Republished "
    "to both hosts and verified live: 30,692 bytes, '97 seconds' present, no stray "
    "backslashes. Two settlement figures (8m38s, 10m26s) are still hand-entered and are "
    "flagged as open debt on the page itself."
)

shutil.copy2(PATH, PATH + ".bak-44b")
with io.open(PATH, encoding="utf-8") as fh:
    st = json.load(fh)

if "LATE CORRECTION" not in (st.get("last_action") or ""):
    st["last_action"] = (st.get("last_action") or "") + NOTE
    hist = st.get("history") or []
    hist.append(
        "Agent Gates run 44: the quieter a measurement looks, the more it needs a second "
        "record. Our own quiet watch was about to publish a stranger it had never seen - the "
        "stranger was us, and only the ledger said so."
    )
    st["history"] = hist
    with io.open(PATH, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
    print("state updated: run_count=%s, history=%d entries" % (st["run_count"], len(hist)))
else:
    print("already recorded, no change")
