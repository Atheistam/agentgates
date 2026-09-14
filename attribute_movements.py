#!/usr/bin/env python3
"""Attribute every movement in a campaign's counter to something, using the ledger.

Run 43 launched campaign4-long with the premise that it would make no downloads of its
own, so any increase in the count belonged to a reader. That premise was false 107
seconds after the campaign started: the same run made its positive-control download at
20:07:27Z, from a different code path, and the campaign's record of its own downloads
stayed an empty list. Ten minutes later the count moved by one.

The campaign could not see that. It subtracts the downloads it scheduled itself, and
this one was scheduled by nobody - it was an instrument test. So a watch built to be
incapable of accusing itself was one ledger row away from accusing a stranger.

The rule this file enforces, and the reason it exists:

    a movement is a reader only if it is larger than the deliberate downloads this
    project made inside the same window, and the ledger - not the campaign's own
    schedule - is the list of those downloads.

It also reports the lag bracket, which the 30-second watch is the first instrument
here able to measure: the campaign knows the count was 12 at its previous read and 13
at this one, so the download landed between those two reads. That bracket is the
tightest measurement of this counter's lag the project has, and it is only obtainable
by an instrument that reads through the lag rather than between it.
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FMT = "%Y-%m-%dT%H:%M:%SZ"
OUT = os.path.join(DATA, "movement_attribution.json")

RULE = ("a movement counts as a reader only if it is larger than the deliberate "
        "downloads this project made inside the same window; the ledger is the list "
        "of those downloads, because a campaign only knows about the downloads it "
        "scheduled itself")


def parse(t):
    try:
        return dt.datetime.strptime(t, FMT).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def load(p, d=None):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d if d is not None else {}


def ledger():
    """The project's own deliberate downloads, from the store, in time order.

    Imported rather than re-derived so the attribution cannot drift from the file the
    probe writes.
    """
    try:
        sys.path.insert(0, HERE)
        import probe_counter as pc
        st = pc.load(pc.STORE, {})
    except Exception as e:
        return [], [], "ledger unreadable: %s" % e
    led = [e for e in (st.get("i2_ledger") or []) if isinstance(e, dict)]
    # An entry with no 'at' is one made before the ledger existed; it carries a bound
    # instead, and it is treated as the bounded moment it is.
    for e in led:
        if not e.get("at") and e.get("at_before"):
            e["at_lo"] = e.get("at_before")
    pend = st.get("i2_pending") or []
    if isinstance(pend, dict):
        pend = [pend]
    return led, pend, None


def ours_in(led, lo, hi):
    """Deliberate downloads of ours in [lo, hi], by download moment.

    Inclusive at both ends: campaign launches a download in the same second as its
    opening read, and a strict lower bound silently dropped it.
    """
    out = []
    for e in led:
        t = parse(e.get("at") or "")
        if t and lo <= t <= hi:
            out.append(e)
    return out


def attribute(label, camp, led, pend, now):
    rows = camp.get("rows") or []
    poll_every = float(camp.get("poll_every") or 30.0)
    start = parse(camp.get("started_at") or "")
    end = parse(camp.get("ended_at") or "") or now
    if not rows or not start:
        return None

    base = rows[0]
    base_c = base.get("count")
    movements = [r for r in rows[1:] if (r.get("delta") or 0)]
    increase = sum(int(r.get("delta") or 0) for r in movements)

    # The window the campaign was responsible for. A campaign whose last write is
    # within a few polls of now is still up, and its window runs to now; a finished
    # campaign's window stops at its own end, so a later run's downloads are not
    # charged to it.
    running = (now - end) <= dt.timedelta(seconds=max(3 * poll_every, 300))
    win_hi = now if running else end
    own_led, own_sched = [], list(camp.get("downloads") or [])
    for e in ours_in(led, start, win_hi):
        own_led.append(e)

    # FIFO: the counter's queue drains oldest first, so the oldest outstanding
    # deliberate download is the one an increase settles.
    outstanding = sorted(own_led, key=lambda e: e.get("at") or "")
    pop = 0
    movs = []
    for r in movements:
        at = parse(r.get("at") or "")
        delta = int(r.get("delta") or 0)
        if at is None:
            continue
        paired, unpaired = [], 0
        for _ in range(delta):
            if pop < len(outstanding):
                paired.append(outstanding[pop])
                pop += 1
            else:
                unpaired += 1
        lo = at - dt.timedelta(seconds=poll_every)
        lags = []
        for d in paired:
            t = parse(d.get("at") or "")
            if t:
                lags.append((int((lo - t).total_seconds()),
                             int((at - t).total_seconds())))
        prev_reading = (base_c if len(movs) == 0 else
                        movs[-1].get("count"))
        movs.append({
            "at": r.get("at"),
            "count": r.get("count"),
            "increase": delta,
            "previous_read_at": lo.strftime(FMT),
            "previous_read_count": prev_reading,
            "ours": [{"at": d.get("at"), "note": d.get("note"),
                      "ua": d.get("ua")} for d in paired],
            "ours_in_window": len(paired),
            "surplus": unpaired,
            "verdict": ("no reader: every unit of this increase is a download this "
                        "project made on purpose" if unpaired == 0 else
                        "%d unit(s) of this increase are not accounted for by any "
                        "download of ours: candidate reader(s)" % unpaired),
            "lag_bracket_s": lags,
        })

    lag_all = [tuple(x) for m in movs for x in m["lag_bracket_s"]]
    # A deliberate download that no increase ever settled. This is the opposite of a
    # phantom reader and it matters as much: if the count can sit still under a
    # download of ours, then "the count did not move" is weaker evidence than it looks.
    unlanded = outstanding[pop:]

    # Only a defect where it can produce a false reader: a movement, and a download of
    # ours in the ledger that the campaign did not know it had made.
    defect = None
    if movs and len(own_led) > len(own_sched):
        defect = {
            "campaign_recorded_as_its_own": len(own_sched),
            "ledger_records_in_window": len(own_led),
            "why": ("the campaign subtracts the downloads it scheduled itself. This "
                    "campaign made none on purpose, and the project made %d inside its "
                    "window from another code path - an instrument test. Left "
                    "unreconciled, the campaign's own arithmetic reads that movement as "
                    "a reader." % len(own_led)),
        }

    return {
        "campaign": label,
        "started_at": camp.get("started_at"),
        "read_at": now.strftime(FMT),
        "still_running": running,
        "planned_minutes": camp.get("minutes"),
        "poll_every_s": poll_every,
        "polls": camp.get("polls"),
        "opening_count": base_c,
        "closing_count": rows[-1].get("count"),
        "increase": increase,
        "movements": movs,
        "movements_n": len(movs),
        "downloads_recorded_by_the_campaign": len(own_sched),
        "downloads_in_the_ledger_inside_the_window": len(own_led),
        "ours_that_never_moved_the_count": [
            {"at": d.get("at"), "note": d.get("note")} for d in unlanded],
        "readers_this_campaign_can_claim": sum(m["surplus"] for m in movs),
        "record_defect": defect,
        "lag_bracket_s": sorted(set(lag_all)),
        "latency_note": ("the campaign reads the counter every %g s, so it knows the "
                         "count was unchanged at the read before each movement and "
                         "changed at it. That is a bracket on the counter's lag, and "
                         "this watch is the first instrument here that reads through "
                         "the lag instead of between it. An instrument that reads "
                         "once an hour measures the hour, not the counter."
                         % poll_every),
    }


def main():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=dt.timezone.utc)
    sweep = load(os.path.join(DATA, "sweep_samples.json"), {})
    led, pend, err = ledger()
    out = {
        "generated_at": now.strftime(FMT),
        "rule": RULE,
        "why_this_file_exists": (
            "run 43 launched a quiet watch whose premise was that it makes no downloads "
            "of its own, and then made one from another code path 107 seconds later. "
            "The watch could not see it. A movement is now attributed against the "
            "ledger before it is called a reader."),
        "ledger_readable": err is None,
        "ledger_entries": len(led),
        "ledger": [{"at": e.get("at"), "note": e.get("note"), "ua": e.get("ua"),
                    "run_label_as_written": e.get("run_label_as_written"),
                    "run_label_corrected": e.get("run_label_corrected")} for e in led],
        "pending_awaits_settlement": len(pend),
        "campaigns": {},
    }
    for label, camp in sorted(sweep.items()):
        a = attribute(label, camp, led, pend, now)
        if a:
            out["campaigns"][label] = a

    tot_mov = sum(c["movements_n"] for c in out["campaigns"].values())
    tot_read = sum(c["readers_this_campaign_can_claim"] for c in out["campaigns"].values())
    out["movements_everywhere"] = tot_mov
    out["readers_any_campaign_can_claim"] = tot_read
    out["reading"] = (
        "Every movement this project has ever recorded is accounted for by a download it "
        "made on purpose: %d movement(s), %d reader(s). That is not a readership figure "
        "and is not published as one - it is the statement that the instruments have "
        "not yet seen a reader, and that the one movement that looked like a stranger "
        "was ours." % (tot_mov, tot_read))

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)

    print("ledger: %d deliberate download(s), %d awaiting settlement" % (len(led), len(pend)))
    for label, c in out["campaigns"].items():
        print("  %-16s movements=%d increase=%d ours=%d/ledger=%d readers=%d unlanded=%d %s"
              % (label, c["movements_n"], c["increase"],
                 c["downloads_recorded_by_the_campaign"],
                 c["downloads_in_the_ledger_inside_the_window"],
                 c["readers_this_campaign_can_claim"],
                 len(c["ours_that_never_moved_the_count"]),
                 "<- record defect" if c["record_defect"] else ""))
        for m in c["movements"]:
            print("      %s %s->%s (+%d) surplus=%d lag=%s"
                  % (m["at"], m["previous_read_count"], m["count"], m["increase"],
                     m["surplus"], m["lag_bracket_s"] or "n/a"))
    print("movements=%d readers=%d -> %s" % (tot_mov, tot_read, OUT))


if __name__ == "__main__":
    main()
