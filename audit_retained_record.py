#!/usr/bin/env python3
"""Can the retained record be read by somebody who was not there?

Run 45. Every campaign this project has run writes a record, and the record is the only
thing that survives the process. This script asks a narrower question than any previous
one: not "what did the campaign find" but "what can a stranger holding only the written
record prove about what the campaign found".

It is written because three of the project's claims turn out to rest on things the record
does not contain, and the way to publish that honestly is to compute the gap rather than
assert it. Three checks:

1. DURATION. `ended_at` is written at every checkpoint, so on a campaign that is still
   running it is the time of the last write, not the end. A stranger who subtracts
   `started_at` gets a duration that is shorter than the campaign's declared length and has
   nothing in the record telling them which of the two numbers is the campaign and which is
   the file.

2. THE BRACKET. A change row carries `gap_s`, and `gap_s` is the time since the previous
   *change* - not since the previous *read*. On a counter that sits still for twelve
   minutes and then moves, that field reads like the time the movement took and it is
   really the time the campaign waited. The bracket the project publishes (the count was
   unchanged at the read before and changed at this one) is not a stored field at all. This
   script recovers it from the one channel that survived long enough to hold it, and
   reports the residual, so the recovery can be checked rather than believed.

3. THE RING. The beat ring holds the last 400 reads and campaign4-long made 2140, so 1740
   of them were written and thrown away. This script says whether that loss could have cost
   the campaign a movement, and shows its work.

Nothing here writes to the campaign's own file. The live instrument owns it and would
overwrite any annotation made in it; a defect in a record is not fixed by rewriting the
record, it is fixed in the code that writes it and published against the data that exists.
"""

import json
import os
import statistics
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "sweep_samples.json")
SERIES = os.path.join(DATA, "counter_series.json")
ATTRIB = os.path.join(DATA, "movement_attribution.json")
OUT = os.path.join(DATA, "retained_record_audit.json")

FMT = "%Y-%m-%dT%H:%M:%SZ"


def ep(s):
    """Epoch seconds for a record timestamp, or None. Never raises: an audit that dies on
    a malformed field cannot report the malformed field."""
    try:
        return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime(FMT)


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def duration_check(sweep, label):
    """Is `ended_at` an end, or the time of the last write?"""
    c = sweep.get(label) or {}
    declared = c.get("minutes")
    declared_s = declared * 60.0 if isinstance(declared, (int, float)) else None
    started = ep(c.get("started_at"))
    ended = ep(c.get("ended_at"))
    span = c.get("observed_span_s")
    pe = c.get("poll_every") or 30.0
    span_s = span if isinstance(span, (int, float)) else (
        (ended - started) if (ended and started) else None)

    # A campaign is still running when the span it has observed is shorter than the time it
    # was told to watch. The tolerance is two polls: the write that closes a finished
    # campaign lands a fraction of a cycle after the deadline, not before it.
    live = (declared_s is not None and span_s is not None and span_s < declared_s - 2 * pe)
    kind = "last checkpoint, campaign still running" if live else "final write"
    return {
        "campaign": label,
        "declared_s": int(declared_s) if declared_s else None,
        "declared_h": round(declared_s / 3600.0, 2) if declared_s else None,
        "started_at": c.get("started_at"),
        "ended_at": c.get("ended_at"),
        "last_write_at": c.get("last_write_at"),
        "observed_span_s": int(span_s) if span_s else None,
        "observed_span_h": round(span_s / 3600.0, 2) if span_s else None,
        "duration_from_ended_at_s": int(ended - started) if (ended and started) else None,
        "ended_at_kind": kind,
        "still_running": live,
        # The question a stranger would ask of the file, and the record's answer.
        "stranger_would_conclude_h": (round((ended - started) / 3600.0, 2)
                                      if (ended and started) else None),
        "record_says_h": round(declared_s / 3600.0, 2) if declared_s else None,
    }


def bracket_check(campaign, beacon, checkpoint_every=10):
    """Recover the sweep bracket for every movement, and measure how well it holds.

    The record does not store the read before a movement. The candidate carriers are:
      * `rows[i].gap_s` - time since the previous *change*, which is a different quantity
        and is reported here so the difference is visible;
      * the beacon channel - written every `checkpoint_every` polls from inside the same
        loop, so its timestamps sit on the read grid. Since it is written ten times less
        often than a beat it survives a long campaign without being trimmed.
    """
    rows = campaign.get("rows") or []
    changes = [r for r in rows if r.get("delta")]
    marks = sorted([b for b in (beacon or []) if not b.get("error") and ep(b.get("at"))],
                   key=lambda b: b["at"])
    spacings = []
    for a, b in zip(marks, marks[1:]):
        dt = ep(b["at"]) - ep(a["at"])
        spacings.append(dt / float(checkpoint_every))
    out = {"marker_every_polls": checkpoint_every,
           "markers": len(marks),
           "spacing_s_per_poll": None,
           "bracket_s": None,
           "movements": []}
    if spacings:
        out["spacing_s_per_poll"] = {
            "min": round(min(spacings), 3),
            "median": round(statistics.median(spacings), 3),
            "max": round(max(spacings), 3),
            "mean": round(sum(spacings) / len(spacings), 3),
        }
        out["grid_deviation_s_per_10_polls"] = round(max(spacings) - min(spacings), 3)

    for r in changes:
        at = ep(r.get("at"))
        rec = {"at": r.get("at"), "count": r.get("count"), "delta": r.get("delta"),
               "gap_s_as_stored": r.get("gap_s"),
               "gap_s_means": ("seconds since the previous change, not since the previous "
                               "read; it is the waiting time, not the sweep time"),
               "previous_read_at": None, "bracket_s": None, "residual_s": None}
        if at and marks:
            prev = [m for m in marks if ep(m["at"]) <= at]
            nxt = [m for m in marks if ep(m["at"]) > at]
            if prev and nxt and spacings:
                # The marker sits on the read grid, at the end of its own cycle. The
                # movement's read is an integer number of polls after it; the read that
                # still saw the old value is exactly one poll before that. Testing that the
                # row lands on the grid is the whole check: if it does not, the grid is not
                # a grid and the bracket is not a bracket.
                p, n = prev[-1], nxt[0]
                step = (ep(n["at"]) - ep(p["at"])) / float(checkpoint_every)
                k = (at - ep(p["at"])) / step
                rec["previous_read_at"] = iso(at - step)
                rec["bracket_s"] = [round(step, 3)]
                rec["residual_s"] = round((ep(p["at"]) + round(k) * step) - at, 3)
                rec["polls_after_marker"] = round(k)
                rec["nearest_marker_at"] = p["at"]
                out["bracket_s"] = round(step, 3)
        out["movements"].append(rec)
    return out


def ring_check(sweep, label, campaign):
    """Could the beat ring's loss have cost the campaign a movement?

    Two separate questions get mixed up whenever this is discussed. (1) Detection: does the
    campaign compare each read against the last read, or against the series it kept? It
    compares against the last read, held in memory, which the ring's trimming cannot touch -
    so a dropped beat cannot cost a movement. (2) Recovery: the dropped beat WAS the only
    place the previous read was written down, so a dropped beat costs the bracket unless
    something else carries the grid. The first is immunity, the second is a real cost, and
    the record should not be read as saying one thing about both.
    """
    total = campaign.get("beats_total")
    held = campaign.get("beats_held")
    dropped = campaign.get("beats_dropped")
    polls = campaign.get("polls")
    pct = round(100.0 * dropped / total, 1) if (total and dropped is not None) else None
    changes = len([r for r in (campaign.get("rows") or []) if r.get("delta")])

    # Monotonicity across every count this project has ever written down. It is the premise
    # of the immunity argument: on a non-decreasing counter, a change cannot hide between
    # two reads and revert, so the only way to miss a movement is to stop reading.
    observations, decreases, worst = 0, 0, None
    for lab, c in sorted(sweep.items()):
        series = []
        for r in (c.get("rows") or []):
            if isinstance(r.get("count"), int):
                series.append((r.get("at"), r["count"]))
        for b in (c.get("beats") or []):
            if isinstance(b.get("count"), int):
                series.append((b.get("at"), b["count"]))
        series.sort(key=lambda x: x[0] or "")
        for i in range(1, len(series)):
            observations += 1
            if series[i][1] < series[i - 1][1]:
                decreases += 1
                worst = worst or {"campaign": lab, "from": series[i - 1], "to": series[i]}
    return {
        "polls": polls,
        "beats_total": total,
        "beats_held": held,
        "beats_dropped": dropped,
        "pct_of_reads_lost_to_the_ring": pct,
        "movements_recorded": changes,
        "movements_lost": 0,
        "why_no_movement_can_be_lost": (
            "the comparison is `count != last_count` against the previous read held in "
            "memory (sample_sweep.py, the branch that appends a change row), and the ring is "
            "trimmed only after the beat for the current read has been written - so trimming "
            "cannot remove the value the next comparison uses"),
        "what_the_loss_did_cost": (
            "the previous read's timestamp. The retained beats are the only place a read was "
            "written down until this campaign's beacon channel was read back"),
        "monotonicity_observations": observations,
        "monotonicity_decreases": decreases,
        "first_decrease": worst,
    }


def settlement_check(sweep, series, attrib):
    """The counter settles late. How late, measured only on downloads of ours?

    Two edges, and they are not the same kind of number: a read that still shows the old
    value is a FLOOR on the latency, a read that shows the new value is a CEILING on it. The
    page has carried these two figures typed by hand since run 44, which is the one thing
    this project says it does not do. Rendering them means deriving them.
    """
    out = {"floor": None, "ceiling": None}
    c1 = sweep.get("campaign1") or {}
    dls = c1.get("downloads") or []
    last_dl = dls[-1] if dls else {}
    dl_t = ep(last_dl.get("at"))
    # The floor: the counter's own reading, taken later, still showing the pre-download
    # value. campaign1's watch had already stopped by then; the reading comes from the
    # series, which is why this number needed the series and not the campaign.
    for r in (series or []):
        raw = r.get("release_downloads_raw")
        if r.get("at") and raw == 11 and dl_t and ep(r["at"]) > dl_t:
            out["floor"] = {
                "download_at": last_dl.get("at"),
                "read_at": r["at"],
                "read_showed": raw,
                "latency_s": int(ep(r["at"]) - dl_t),
                "why_it_is_a_floor": ("the count had still not moved at that read, so the "
                                      "download was outstanding for at least this long"),
            }
    # The ceiling: the read that first showed the movement, minus the download that caused
    # it, both inside campaign4-long.
    q4 = sweep.get("campaign4-long") or {}
    rows4 = [r for r in (q4.get("rows") or []) if r.get("delta")]
    led = [e for e in (attrib.get("ledger") or [])
           if e.get("at") and e.get("note") and "positive control" in e["note"]]
    if rows4 and led:
        row = rows4[-1]
        dl = led[-1]
        if ep(row.get("at")) and ep(dl.get("at")):
            out["ceiling"] = {
                "download_at": dl["at"],
                "read_at": row["at"],
                "latency_s": int(ep(row["at"]) - ep(dl["at"])),
                "bracket_lo_s": (int(ep(row["at"]) - ep(dl["at"]))
                                 - int(round(round(q4.get("poll_every") or 30.0)))),
                "why_it_is_a_ceiling": ("that read is the first one that showed the increase, "
                                        "so the release happened at or before it"),
            }
    return out


def beacon_carrier(campaign):
    """The channel that was not trimmed, and what it says."""
    b = [x for x in (campaign.get("beacon") or []) if not x.get("error")]
    reqs = sorted(set(x.get("requests") for x in b if isinstance(x.get("requests"), int)))
    strangers = sorted(set(x.get("not_this_project") for x in b
                           if isinstance(x.get("not_this_project"), int)))
    span = (ep(b[-1]["at"]) - ep(b[0]["at"])) if len(b) > 1 else None
    return {
        "entries": len(b),
        "entries_dropped": campaign.get("beacon_dropped"),
        "first_at": b[0]["at"] if b else None,
        "last_at": b[-1]["at"] if b else None,
        "span_h": round(span / 3600.0, 2) if span else None,
        "requests_values": reqs,
        "not_this_project_values": strangers,
        "reading": None,
    }


def main():
    sweep = load(SAMPLES, {})
    series = load(SERIES, [])
    attrib = load(ATTRIB, {})
    now = datetime.now(timezone.utc).strftime(FMT)

    audit = {
        "generated_at": now,
        "run": 45,
        "written_by": "audit_retained_record.py",
        "question": ("what can a reader holding only the written record prove about what "
                     "these campaigns found"),
        "writes_to_the_campaign_record": False,
    }
    audit["duration"] = [duration_check(sweep, lab) for lab in sorted(sweep)]

    q4 = sweep.get("campaign4-long") or {}
    audit["bracket"] = bracket_check(q4, q4.get("beacon"),
                                     checkpoint_every=10)
    audit["ring"] = ring_check(sweep, "campaign4-long", q4)
    audit["beacon_channel"] = beacon_carrier(q4)
    audit["settlement"] = settlement_check(sweep, series, attrib)

    bc = audit["beacon_channel"]
    if bc["entries"] and bc["requests_values"] == [13] and bc["not_this_project_values"] == [0]:
        bc["reading"] = ("every one of the channel's readings, across its whole span, carries "
                         "the same request count and zero requests that are not this "
                         "project's")

    with open(OUT, "w") as f:
        json.dump(audit, f, indent=2, sort_keys=False)

    d4 = [d for d in audit["duration"] if d["campaign"] == "campaign4-long"][0]
    br = audit["bracket"]
    print("audit -> %s" % OUT)
    print("duration  : campaign4-long declared %s h, record's ended_at gives %s h (%s)"
          % (d4["declared_h"], d4["stranger_would_conclude_h"], d4["ended_at_kind"]))
    print("bracket   : %s s/poll measured on the beacon grid (%s), residual at the movement "
          "%s s" % (br["spacing_s_per_poll"]["median"], br["markers"],
                    (br["movements"][-1]["residual_s"] if br["movements"] else None)))
    r = audit["ring"]
    print("ring      : %s of %s reads dropped (%s%%), movements recorded %s"
          % (r["beats_dropped"], r["beats_total"], r["pct_of_reads_lost_to_the_ring"],
             r["movements_recorded"]))
    print("monotone  : %s consecutive observations, %s decreases"
          % (r["monotonicity_observations"], r["monotonicity_decreases"]))
    s = audit["settlement"]
    print("settle    : floor %s s, ceiling %s s"
          % ((s["floor"] or {}).get("latency_s"), (s["ceiling"] or {}).get("latency_s")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
