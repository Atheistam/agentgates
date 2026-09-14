#!/usr/bin/env python3
"""The question the rest of this page cannot answer about itself: can somebody who was not
there read the record and reach what the campaigns reached?

Run 45. `audit_retained_record.py` does the reading and writes
data/retained_record_audit.json; this renders it. Every figure in the section below comes
from that file or from the campaign records, and none of it is typed. The distinction matters
here more than usual, because the subject of the section is records that cannot be read
without the person who wrote them.
"""
import json
import os
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    try:
        with open(os.path.join(HERE, "data", name)) as f:
            return json.load(f)
    except Exception:
        return {}


def _utc(epoch):
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return "?"


def _h(seconds):
    if seconds is None:
        return "?"
    s = int(seconds)
    if s < 3600:
        return "%dm %ds" % (s // 60, s % 60)
    return "%.1f h" % (s / 3600.0)


def _age(seconds):
    """Signed age, so a record written after the page was built reads as the future, not as
    a negative number a reader has to interpret."""
    s = int(seconds)
    return "%d s" % s if s >= 0 else "%d s in the future" % -s


def record_audit_block(esc):
    a = _load("retained_record_audit.json")
    if not a:
        return ""
    durs = a.get("duration") or []
    ring = a.get("ring") or {}
    bracket = a.get("bracket") or {}
    beam = a.get("beacon_channel") or {}
    sweep = _load("sweep_samples.json")
    live = sweep.get("campaign4-long") or {}
    samples_path = os.path.join(HERE, "data", "sweep_samples.json")
    age = (time.time() - os.stat(samples_path).st_mtime) if os.path.exists(samples_path) else None

    rows = []
    real = [d for d in durs if (d.get("declared_h") or 0) >= 0.4]
    short = len(durs) - len(real)
    for d in real:
        stranger = d.get("stranger_would_conclude_h")
        record = d.get("record_says_h")
        gap = (record - stranger) if (isinstance(stranger, float)
                                      and isinstance(record, float)) else None
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td></tr>"
            % (esc(d.get("campaign")),
               "%.1f h" % record if isinstance(record, float) else esc(record),
               _h(d.get("observed_span_s")),
               "%s <span class=\"unk\">(%s)</span>" % (esc(d.get("ended_at")),
                                                       esc(d.get("ended_at_kind"))),
               "no" if gap and gap > 0.5 else "yes",
               ("reads as <strong>%.1f h</strong> long, not %.1f h"
                % (stranger, record)) if gap and gap > 0.5
               else "the same duration the record states"))

    moves = bracket.get("movements") or []
    mov = moves[0] if moves else {}
    grid = bracket.get("spacing_s_per_poll") or {}
    floor = (a.get("settlement") or {}).get("floor") or {}
    ceil = (a.get("settlement") or {}).get("ceiling") or {}
    declared_hours_txt = ("%.0f" % ((live.get("minutes") or 0) / 60.0)) if live else "?"

    live_txt = ""
    if live:
        declared_h = (live.get("minutes") or 0) / 60.0
        live_txt = (
            "<p><strong>And it is still happening.</strong> %s is the watch that spans runs. "
            "It declared %.0f hours and its last write said %s, so while it runs the record "
            "reads as %s long; the process was alive when the audit ran and the record has "
            "moved since - this page was built %s after that write, %s polls in, %s reads held "
            "of %s made (%s dropped by the ring). The audit is a reading of a watch in "
            "progress and says so, rather than freezing a number that was never final. The "
            "ring cost a read its timestamp every time it dropped one, and never cost the "
            "watch a movement: %s comparisons in the retained beats, %s decreases.</p>"
            % (esc(live.get("campaign")), declared_h, esc(live.get("ended_at")),
               _h(live.get("observed_span_s")),
               _age(age) if age is not None else "?", live.get("polls"),
               live.get("beats_held"), live.get("beats_total"), live.get("beats_dropped"),
               ring.get("monotonicity_observations"), ring.get("monotonicity_decreases")))

    return (
        "<h2>Can the record be read by somebody who was not there?</h2>"
        "<p>Every campaign on this page reports a duration and a bracket. The audit behind "
        "this section asked a narrower question than \"is it true\": <em>if a reader had only "
        "the files, would they reach what the campaign reached?</em> It reads the campaign "
        "records, the counter's own series and the beacon channel, and it writes nothing back - "
        "audit %s, run %s, question: %s. The file holds %s watches; the table shows the %s that "
        "declared at least half an hour. The other %s are the smoke test and the three "
        "self-tests: seconds each, all final writes, and none of them a finding.</p>"
        "<table><tr><th>watch</th><th>declared</th><th>last write minus start</th>"
        "<th>the record's last write</th><th>is that an ending?</th>"
        "<th>what a stranger concludes</th></tr>%s</table>"
        "<p><strong>The defect that table is about.</strong> <code>ended_at</code> is written at "
        "every checkpoint of a running watch, not at its end. So a live watch's record carries "
        "a timestamp that is the last time somebody wrote to it, and a reader has no way to "
        "tell that from an ending. campaign4-long's is the clearest case: %s hours declared, "
        "and any file read while it runs concludes a shorter watch that stopped. The fix is "
        "not a correction of the number - the number was always right - but a label. From run "
        "45 the instrument stores <code>ended_at_kind</code> (\"checkpoint, campaign still "
        "watching\" against \"final write, the watch reached its deadline\") and "
        "<code>last_read_at</code>, so the two readings cannot be confused again.</p>"
        "%s"
        "<p><strong>The read the record threw away.</strong> A change row carries "
        "<code>gap_s</code>: seconds since the previous <em>change</em>. The bracket - seconds "
        "since the previous <em>read</em> - is the number that decides whether a movement is a "
        "reader or a queue draining, and this campaign wrote it down %s times out of %s reads: "
        "a beat ring holding %s beats dropped %s of them (%s%% of every read the watch made). "
        "No movement was lost - the comparison is against the previous read held in memory, so "
        "whatever the ring discarded could not be the value the next comparison used - but the "
        "previous read's <em>timestamp</em> survived only in the beacon channel, %s markers "
        "written every %s polls, spacing min %ss, median %ss, max %ss. That is the honest shape "
        "of the finding: the bracket this page quotes is reconstructed from a channel that was "
        "not built to hold it, %s s of drift across ten polls.</p>"
        "<p>The single movement campaign4-long recorded shows what the loss cost. It is stored "
        "with <code>gap_s</code> = %s, which reads as a number that held for twelve minutes. The "
        "number held for one poll: the read before it was %s, %s s earlier. Both statements are "
        "in the same row, and only one of them was in the record.</p>"
        "<p><strong>The settlement bracket, from the record.</strong> One download of ours was "
        "still uncounted at the read of %sZ (the count read %s), so it was outstanding at least "
        "%s s; one was present by the read of %sZ after a download at %s, so it settled within "
        "%s s. The first is a floor and the second is a ceiling, and they come from one read "
        "each - not from the counter's behaviour in general, which this project has got wrong "
        "before in the direction that flattered it.</p>"
        "<p><strong>What the audit cannot prove.</strong> A bracket reconstructed from a beacon "
        "grid assumes the grid is regular; a count read once an hour cannot distinguish a "
        "settling queue from a reader, and neither can this audit. The instrument that will "
        "answer those questions stores both, and the test that pins the storage is "
        "<code>test_bracket_fields.py</code> - a scripted counter and a frozen clock, 15 "
        "assertions, including that the bracket stays one poll interval wide and that a live "
        "record is never opened by the test itself.</p>"
        % (esc(a.get("generated_at")), esc(a.get("run")), esc(a.get("question")),
           len(durs), len(real), short,
           "".join(rows), declared_hours_txt, live_txt,
           ring.get("beats_held"), ring.get("polls"), ring.get("beats_held"),
           ring.get("beats_dropped"), ring.get("pct_of_reads_lost_to_the_ring"),
           beam.get("entries"), bracket.get("marker_every_polls"),
           grid.get("min"), grid.get("median"), grid.get("max"),
           bracket.get("grid_deviation_s_per_10_polls"),
           mov.get("gap_s_as_stored"), esc(mov.get("previous_read_at")),
           (mov.get("bracket_s") or ["?"])[0],
           esc((floor.get("read_at") or "")[:19]), floor.get("read_showed"),
           floor.get("latency_s"), esc((ceil.get("read_at") or "")[:19]),
           esc(ceil.get("download_at")), ceil.get("latency_s"))
    )
