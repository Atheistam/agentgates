#!/usr/bin/env python3
"""One-time correction of the deliberate-download ledger, plus its missing entry.

Two errors are fixed, and both are recorded in the state file rather than quietly repaired:

1. Run 39's pending records carried the moment its poll window closed - 30 seconds after
   the download - and run 40's first pass copied those as download times. Every latency
   published from them was half a minute long. The four old entries are rewritten to the
   download moment, with the value they were taken from kept as `recorded_at`.

2. The deliberate download made at 11:01:53Z was not in the ledger, because the ledger did
   not exist until minutes later in the same run. It was found in the pending record and
   added. Without it the ledger says this project made five downloads while its own state
   file says six, and an instrument that cannot reconcile its own arithmetic is decoration.

Run once:
    python3 migrate_run40_ledger.py            # report only
    python3 migrate_run40_ledger.py --apply
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "beacon_endpoint.json")
WINDOW_S = 30
# The pending records were written before they carried the asset they watched. They watched
# the scripted asset: the control downloads that one.
SCRIPTED = "agentgates-dataset.json"

CORRECTED = {
    "2026-09-12T20:06:11Z": ("2026-09-12T20:05:41Z",
                             "run 39 positive control; latency 14.93 h to the read at "
                             "2026-09-13T11:01:41Z"),
    "2026-09-12T20:08:33Z": ("2026-09-12T20:08:03Z",
                             "run 39 positive control (second instrument run); latency 14.89 h"),
    "2026-09-12T20:11:11Z": ("2026-09-12T20:10:41Z",
                             "run 39 positive control (third instrument run); latency 14.85 h"),
}
MISSING = {
    "asset": "agentgates-dataset.json", "at": "2026-09-13T11:01:53Z", "http": 200,
    "recorded_at": "2026-09-13T11:02:23Z", "ua": "agentgates-counter/1.0",
    "note": ("run 40 positive control, first instrument run. Not in the ledger when it was "
             "made: the ledger was added minutes later in the same run. Recovered from the "
             "pending record and corrected by 30 s."),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    with open(STATE) as f:
        st = json.load(f)
    led = st.get("i2_ledger") or []
    print("ledger entries before: %d" % len(led))
    changes = []
    for e in led:
        at = e.get("at")
        if at in CORRECTED:
            new_at, note = CORRECTED[at]
            changes.append("  %s -> %s (%s)" % (at, new_at, e.get("note", "")[:40]))
            e["recorded_at"] = e.get("recorded_at") or at
            e["at"] = new_at
            e["note"] = note
            e["time_basis"] = "download moment; the pending record's own value is in recorded_at"
    if not any(e.get("at") == MISSING["at"] for e in led):
        led.append(dict(MISSING))
        changes.append("  added the download at %s, which the ledger was missing" % MISSING["at"])
    led_at = [(e.get("at"), e.get("asset")) for e in st["i2_ledger"] if e.get("at")]
    for p in st.get("i2_pending", []):
        if p.get("download_attempted_at"):
            p["recorded_at"] = p["download_attempted_at"]
        if p.get("recorded_at"):
            derived = shift(p["recorded_at"])
            # Where the ledger heard the clock next to the download itself, its time wins:
            # the reconstructed value is a subtraction that assumes the poll window's length,
            # and this one closed after 33 s, not 30. Three seconds is small, and publishing
            # a latency that is wrong by three seconds is exactly how the half-minute error
            # in run 40's first pass began.
            near = [a for a, _ in led_at
                    if abs(_gap(a, derived)) < 120
                    and _asset_of(st, a) == (p.get("asset") or SCRIPTED)]
            if near:
                p["derived_downloaded_at"] = derived
                p["downloaded_at"] = min(near, key=lambda a: abs(_gap(a, derived)))
                p["time_basis"] = ("the ledger's own timestamp for this download, taken next "
                                   "to the download call; the reconstruction was %s" % derived)
            else:
                p["downloaded_at"] = derived
                p["time_basis"] = ("download moment = poll-window close minus the %.0f s "
                                   "window" % WINDOW_S)
            if p.get("downloaded_at") not in (derived, None):
                changes.append("  pending %s -> downloaded_at %s (ledger's own value; "
                               "reconstruction gave %s)" % (p["recorded_at"],
                                                            p["downloaded_at"], derived))
            else:
                changes.append("  pending %s -> downloaded_at %s"
                               % (p["recorded_at"], p["downloaded_at"]))
    st["i2_ledger"] = sorted(led, key=lambda e: (e.get("at") or e.get("at_before") or ""))
    st["i2_ledger_migration"] = {
        "at": "2026-09-13T11:2xZ (run 40)",
        "corrections": len(changes), "detail": changes,
        "why": ("a count belongs to an asset and a latency belongs to a moment; without both, "
                "a download total cannot be attributed to anybody"),
        "cut": ("downloads younger than %.2f h at the moment of a read cannot be in a count "
                "that has not refreshed since, and are excluded rather than guessed"
                % st.get("i2_lag_hours_min", 14.85)),
    }
    print("changes:")
    for c in changes:
        print(c)
    print("ledger entries after: %d" % len(st["i2_ledger"]))
    for e in st["i2_ledger"]:
        print("  %s  %-28s %s" % (e.get("at") or "before " + str(e.get("at_before")),
                                  e.get("asset"), (e.get("note") or "")[:60]))
    if a.apply:
        with open(STATE, "w") as f:
            json.dump(st, f, indent=1, sort_keys=True)
        print("applied to %s" % STATE)
    else:
        print("dry run; pass --apply to write")


def _gap(a, b):
    """Seconds between two UTC strings - the only kind of number this file needs."""
    import calendar
    import time
    f = "%Y-%m-%dT%H:%M:%SZ"
    return calendar.timegm(time.strptime(a, f)) - calendar.timegm(time.strptime(b, f))


def _asset_of(state, at):
    for e in state["i2_ledger"]:
        if e.get("at") == at:
            return e.get("asset")
    return None


def shift(iso):
    """The window close, minus the window. timegm, not mktime: the string is UTC and
    mktime() reads wall-clock local time, which silently put a two hour error into the
    first pass of this migration - the same class of mistake as the one it exists to fix."""
    import calendar
    import time
    t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(calendar.timegm(t) - WINDOW_S))


if __name__ == "__main__":
    main()
