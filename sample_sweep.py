#!/usr/bin/env python3
"""Watch the release counter instead of sampling it from hours away.

Run 40 found a counter that moves within minutes, and measured it twice: a deliberate
download still uncounted 5.5 minutes after it was made, and one counted 11.4 minutes after.
Two reads fourteen hours apart said "fifteen hours of latency" and were wrong; two reads
fifteen minutes apart bound the sweep at "somewhere between five and twelve minutes", which
is a bound and not a period. Reading faster is the only way to get the period.

So this script watches. It polls the number on a short interval, writes down the moment it
changes, and makes deliberate downloads at known moments - each with the clock read beside
the request rather than after the poll window closes - so every increase can be attributed
to the download that caused it, and any increase that is larger than this project's own
downloads is called out by name at the moment it is first seen.

Why it exists at all: every claim this project has published about this counter so far came
from reads spaced hours apart, and the gap between two reads is a property of the reader.
This instrument now reads at the speed of the thing it is measuring.

    python3 sample_sweep.py --label campaign1                  # 40 min, a download every 5
    python3 sample_sweep.py --dry-run --minutes 5              # watch only, touch nothing

Nothing here guesses. A cycle that cannot read the number records the error and continues:
a campaign that dies on one 502 has measured nothing.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

import probe_counter as pc

SAMPLES = os.path.join(pc.DATA, "sweep_samples.json")


def utc():
    """The project's timestamp, and the only one any arithmetic is allowed to use."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_count(token):
    """The number, or an error to write down. Never an exception."""
    rel, err = pc.ensure_release(token)
    if err:
        return None, err
    for a in rel.get("assets") or []:
        if a.get("name") == pc.ASSET_NAME:
            return a.get("download_count"), None
    return None, "%s is not among the release's assets" % pc.ASSET_NAME


def deliberate_download(token, label, count_before):
    """One download, with the moment taken from the clock beside the request.

    Run 39's ledger recorded the moment its poll window closed, thirty seconds later, and
    every latency computed from that ledger was wrong by half a minute until run 40 went
    back and corrected it. The moment is therefore read here, before the request leaves,
    and it is the value the arithmetic uses - `recorded_at` is kept only to show what the
    clock beside the poll would have said."""
    rel, err = pc.ensure_release(token)
    if err:
        return {"at": utc(), "error": "no url: %s" % err}
    url = None
    for a in rel.get("assets") or []:
        if a.get("name") == pc.ASSET_NAME:
            url = a.get("download_url")
    if not url:
        return {"at": utc(), "error": "no download_url for %s" % pc.ASSET_NAME}

    at = utc()
    status, _ = pc.get(url, ua=pc.UA_BROWSER, timeout=60)
    recorded_at = utc()
    after, _err = read_count(token)
    entry = {"at": at, "recorded_at": recorded_at, "http": status,
             "count_before": count_before, "count_after": after}

    # The same ledger probe_counter reads, appended to and never rewritten: an instrument
    # that keeps two private counts of the same downloads is two instruments disagreeing.
    state = pc.load(pc.STORE, {})
    led = pc.i2_ledger(state)
    led.append({"asset": pc.ASSET_NAME, "at": at, "http": status,
                "recorded_at": recorded_at,
                "note": ("sweep campaign %s: deliberate download inside a watched window, "
                         "count before %s" % (label, count_before))})
    state["i2_ledger"] = led
    with open(pc.STORE, "w") as f:
        json.dump(state, f, indent=2)
    return entry


def _write(label, campaign):
    """Merge this campaign into data/sweep_samples.json under its label, atomically enough:
    written to a temporary file and moved into place, so a reader never sees half a row."""
    existing = pc.load(SAMPLES, {})
    existing[label] = campaign
    tmp = SAMPLES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, SAMPLES)
    return SAMPLES


def summarise(campaign):
    """What the campaign can and cannot say, printed plainly at the end.

    The counts beyond this project's own downloads are the only ones that mean a reader -
    which is why every download made here is subtracted by moment, not by total."""
    rows = [r for r in campaign["rows"] if "count" in r]
    starts = campaign["rows"][0].get("count") if campaign["rows"] else None
    ends = rows[-1]["count"] if rows else None
    own = [d for d in campaign["downloads"] if not d.get("error")]
    gaps = [r["gap_s"] for r in rows if r.get("gap_s")]
    print("campaign %s  %s -> %s" % (campaign["campaign"], campaign["started_at"],
                                     campaign["ended_at"]))
    print("count %s -> %s   change %s   own deliberate downloads %d"
          % (starts, ends, (ends - starts) if (ends is not None and starts is not None) else "?",
             len(own)))
    if starts is not None and ends is not None:
        print("increase minus own downloads: %d" % (ends - starts - len(own)))
    print("reads %d, of which %d changed the count (%d errors), gaps recorded %d"
          % (campaign.get("polls", 0), len(rows),
             len(campaign["rows"]) - len(rows), len(gaps)))
    print("every sweep moment (gap to the previous one):")
    for r in rows:
        g = ("%7.1f s = %5.2f min" % (r["gap_s"], r["gap_s"] / 60.0)) if r.get("gap_s") else "first read"
        print("   %s  count %-3s %s" % (r["at"], r["count"], g))
    print("observed sweep gaps (s): %s" % (sorted(gaps) or "none - the number did not move"))
    # One assignment pass, because the counter reports a total and not a list. A sweep that lifts
    # the count by one cannot have counted two downloads, which the first version of this table
    # quietly assumed - it credited the same +1 to two different downloads. Each sweep is now
    # credited with the OLDEST downloads available to it: an assumption, the sensible one for a
    # queue, and stated rather than hidden.
    pending = list(own)
    assigned = {}
    for r in rows[1:]:
        if r.get("delta") is None or r["delta"] <= 0:
            continue
        available = [d for d in pending if d["at"] <= r["at"]]
        carried = sorted(available, key=lambda d: d["at"])[:r["delta"]]
        for d in carried:
            assigned[d["at"]] = r["at"]
            pending.remove(d)
        if available:
            newest = max(available, key=lambda d: d["at"])
            age = (pc.iso_epoch(r["at"]) or 0) - (pc.iso_epoch(newest["at"]) or 0)
            print("sweep %s carried %d download(s) of this project's: the newest download "
                  "available to it was %d s old, so that one sat uncounted no longer than that"
                  % (r["at"], len(carried), age))
    for d in own:
        if assigned.get(d["at"]):
            lat = (pc.iso_epoch(assigned[d["at"]]) or 0) - (pc.iso_epoch(d["at"]) or 0)
            print("   download %s -> counted at %s  (%d s = %.1f min)"
                  % (d["at"], assigned[d["at"]], lat, lat / 60.0))
        else:
            print("   download %s -> not counted at any of the %d reads in this campaign"
                  % (d["at"], campaign.get("polls", 0)))
    if assigned:
        worst = max((pc.iso_epoch(v) or 0) - (pc.iso_epoch(k) or 0) for k, v in assigned.items())
        print("longest wait this campaign can prove for a download of its own: %d s = %.1f min "
              "(a floor on how wide the sweep is, and no evidence at all about its period)"
              % (worst, worst / 60.0))
    # What this campaign can say about downloads that were not this project's own.
    #
    # The first version of this block said "at least one download by someone else" whenever a
    # sweep carried more downloads than had been made since the previous sweep, and it was wrong
    # within half an hour of being written. A sweep that carries two downloads made before the
    # previous sweep is a counter with a queue, not a stranger. The only surplus a campaign can
    # honestly show is the whole window's increase minus the downloads this project made inside
    # that window; and even that is a surplus only if the ledger is complete.
    base_at = campaign["rows"][0].get("at") if campaign["rows"] else None
    in_window = [d for d in own if base_at and d["at"] > base_at]
    if starts is not None and ends is not None and base_at:
        surplus = (ends - starts) - len(in_window)
        print("in-window increase %d; this project's downloads made after the baseline read %d"
              % (ends - starts, len(in_window)))
        if surplus > 0:
            print("SURPLUS %d: the number rose by more than this project downloaded inside the "
                  "window. Just that surplus is a candidate for someone else, and it stays a "
                  "candidate until a second campaign shows it again." % surplus)
        else:
            print("no surplus: every count the sweep moved inside this window is accounted for by "
                  "a download this project made and logged. No stranger can be claimed here, and "
                  "the fact that sweeps arrive carrying two downloads at once implies none - it "
                  "implies a queue.")
    for d in pending:
        print("uncounted at the campaign's last read: the download made at %s (%d s before the "
              "campaign ended)" % (d["at"], (pc.iso_epoch(campaign["ended_at"]) or 0)
                                   - (pc.iso_epoch(d["at"]) or 0)))
    print("dry run: %s (no deliberate download was made)" % campaign["dry_run"])


def main():
    ap = argparse.ArgumentParser(description="Watch the release counter and time its sweeps.")
    ap.add_argument("--minutes", type=float, default=40.0,
                    help="how long to watch (default 40)")
    ap.add_argument("--poll-every", type=float, default=30.0,
                    help="seconds between reads of the count (default 30)")
    ap.add_argument("--download-every", type=float, default=300.0,
                    help="seconds between deliberate downloads (default 300). 0 = never "
                         "download: a quiet baseline. That is the only configuration that can "
                         "answer whether anyone else downloads this asset, because with no "
                         "downloads of this project's own, every count that moves belongs to "
                         "somebody else. The first campaign could not answer it: its own "
                         "downloads were indistinguishable from a stranger's.")
    ap.add_argument("--label", default="campaign",
                    help="name this campaign; it becomes the key in data/sweep_samples.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="watch only: make no download and append nothing to the ledger")
    ap.add_argument("--resummarise", metavar="LABEL",
                    help="print the summary of a stored campaign again, without collecting "
                         "anything. Written when the first summary of a finished campaign was "
                         "found to contain a claim the ledger does not support: a stored campaign "
                         "should be re-readable with the reading code fixed.")
    args = ap.parse_args()
    if args.resummarise:
        stored = pc.load(SAMPLES, {}).get(args.resummarise)
        if not stored:
            print("no stored campaign labelled %s in %s" % (args.resummarise, SAMPLES))
            return 2
        print("re-summarised from %s (nothing was collected, nothing was downloaded)" % SAMPLES)
        summarise(stored)
        return 0

    token = pc.gh_token()
    if not token:
        print("no token from the git credential helper: the release API will rate-limit "
              "at 60 reads an hour, which this campaign would exceed. Raising the poll "
              "interval to 90 s.")
        args.poll_every = max(args.poll_every, 90.0)

    campaign = {"campaign": args.label, "started_at": utc(), "ended_at": None,
                "minutes": args.minutes, "poll_every": args.poll_every,
                "download_every": args.download_every, "dry_run": bool(args.dry_run),
                "rows": [], "downloads": []}
    print("watching the counter for %s minutes, one read every %s s, %s"
          % (args.minutes, args.poll_every,
             "no downloads at all (quiet baseline)" if args.download_every <= 0
             else ("no downloads (dry run)" if args.dry_run
                   else "a deliberate download every %s s" % args.download_every)))

    started = time.time()
    deadline = started + args.minutes * 60.0
    next_download = started
    last_count = None
    last_change = None
    campaign["polls"] = 0

    while time.time() < deadline:
        cycle = time.time()
        campaign["polls"] += 1
        # The number is read first and the download made second, in that order, every
        # cycle. The first campaign learned this the hard way: it downloaded before it had
        # ever read the count, so its first download carries no `count_before` and cannot
        # be attributed to a change - one download spent, no measurement bought.
        count, err = read_count(token)
        if (not args.dry_run) and args.download_every > 0 and cycle >= next_download:
            d = deliberate_download(token, args.label, count if not err else last_count)
            campaign["downloads"].append(d)
            next_download = cycle + args.download_every
            print("  %s" % json.dumps(d))
        if err:
            campaign["rows"].append({"at": utc(), "error": err})
            print("  %s read failed: %s" % (utc(), err))
        elif count != last_count:
            row = {"at": utc(), "count": count,
                   "delta": (count - last_count) if last_count is not None else None}
            if last_change:
                row["gap_s"] = (pc.iso_epoch(row["at"]) or 0) - (pc.iso_epoch(last_change) or 0)
            campaign["rows"].append(row)
            print("  %s count %s (+%s) after %s s"
                  % (row["at"], count, row["delta"], row.get("gap_s", "?")))
            last_count, last_change = count, row["at"]
            # Written as it happens, not at the end. The first campaign held thirty minutes of
            # observations in memory and would have lost all of them to a crash or a killed
            # process - a watcher whose memory is only at its end is not a watcher.
            campaign["ended_at"] = utc()
            _write(args.label, campaign)
        elif not campaign["rows"]:
            campaign["rows"].append({"at": utc(), "count": count, "delta": None,
                                     "gap_s": None})
        # Checkpoint even when nothing happens. The change-triggered write above is enough
        # for a campaign that finds movement, and useless for a campaign whose finding is
        # that there was none: a quiet baseline that is killed before its deadline would
        # leave behind exactly zero evidence of the quiet it observed. So every tenth poll
        # writes what has been seen so far.
        if campaign["polls"] % 10 == 0:
            campaign["ended_at"] = utc()
            _write(args.label, campaign)
        time.sleep(max(0.0, args.poll_every - (time.time() - cycle)))

    campaign["ended_at"] = utc()
    _write(args.label, campaign)
    print("")
    summarise(campaign)
    print("")
    print("written to %s" % SAMPLES)


if __name__ == "__main__":
    main()
