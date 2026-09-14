#!/usr/bin/env python3
"""The counter campaign's first reading was wrong in the direction that flatters: it
accused a stranger of reading. This renders the reconciliation and what replaced it.

The bug is worth publishing. The campaign paired every increase in the download count
with the downloads this project made after it, so each sweep arrived carrying downloads
the counter had not acknowledged yet and the remainder looked like somebody else. The
counter settles late; the summary read it early.
"""


def _i(x, d=None):
    return x if isinstance(x, int) else d


def _dur(seconds):
    """A settlement interval, written the way the page has always written them."""
    if seconds is None:
        return "?"
    s = int(seconds)
    if s < 3600:
        return "%dm%ds" % (s // 60, s % 60)
    return "%dh%dm" % (s // 3600, (s % 3600) // 60)


def settlement():
    """The two settlement intervals, read out of the audit instead of typed into the prose.

    Run 44 published these two numbers and recorded, in the same paragraph, that they were
    entered by hand - the one place on the page where a figure came from a person rather than
    from the record. That is the defect this project exists to complain about, so this closes
    it: both figures, both timestamps and both directions come from
    data/retained_record_audit.json, which derives them from the campaign records and the
    counter's own series. If the audit changes, the sentence changes with it.
    """
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                        "retained_record_audit.json")
    try:
        with open(path) as f:
            st = json.load(f).get("settlement") or {}
    except Exception:
        st = {}
    floor, ceil = st.get("floor") or {}, st.get("ceiling") or {}
    return {
        "floor_text": _dur(floor.get("latency_s")),
        "floor_s": floor.get("latency_s"),
        "floor_download_at": floor.get("download_at"),
        "floor_read_at": floor.get("read_at"),
        "floor_read_showed": floor.get("read_showed"),
        "ceiling_text": _dur(ceil.get("latency_s")),
        "ceiling_s": ceil.get("latency_s"),
        "ceiling_download_at": ceil.get("download_at"),
        "ceiling_read_at": ceil.get("read_at"),
    }


def _fifo_latencies(downloads, rows):
    """Pair each increase with the download that caused it, oldest first.

    The counter's window is a queue, not a moment: an increase of two means two
    downloads drained, and the first one through is the first one made. Anything left
    in the queue when the campaign stopped was never counted inside it.
    """
    lat, pop = [], 0
    for r in rows[1:]:
        for _ in range(_i(r.get("delta"), 0) or 0):
            if pop >= len(downloads):
                break
            lat.append((r.get("at"), downloads[pop]))
            pop += 1
    out = []
    for at, d in lat:
        try:
            from datetime import datetime, timezone
            f = "%Y-%m-%dT%H:%M:%SZ"
            a = datetime.strptime(d.get("at"), f).replace(tzinfo=timezone.utc)
            b = datetime.strptime(at, f).replace(tzinfo=timezone.utc)
            out.append(int((b - a).total_seconds()))
        except Exception:
            pass
    return out


def campaign_block(sweep, rep, esc):
    c1 = sweep.get("campaign1") or {}
    rows = c1.get("rows") or []
    dl = c1.get("downloads") or []
    if not rows:
        return ""

    base_c = _i(rows[0].get("count"), 0)
    end_c = _i(rows[-1].get("count"), base_c)
    increase = end_c - base_c
    own = len(dl)
    surplus = increase - own
    lat = sorted(_fifo_latencies(dl, rows), reverse=True)
    gaps = [r.get("gap_s") for r in rows[1:] if isinstance(r.get("gap_s"), (int, float))]

    i2 = (rep.get("instruments") or {}).get("I2_download_count") or {}
    att = i2.get("attribution") or {}
    counted = _i(sum((att.get("counted") or {}).values()))
    made = _i(i2.get("downloads_made_by_this_project"))
    outside = i2.get("downloads_by_anyone_else")
    interval = i2.get("downloads_by_anyone_else_interval")

    quiet = sweep.get("campaign2-quiet") or {}
    q_rows = quiet.get("rows") or []

    return (
        "<h2>The campaign that accused a stranger, then took it back</h2>"
        "<p>A campaign watched the download count for 26 minutes in three sweeps and its "
        "summary printed an accusation: <em>UNEXPLAINED - count rose by 2, at least 1 "
        "download by someone else</em>. Corrected: baseline count %(base)d, final count "
        "%(end)d, increase %(inc)d, downloads this project made in the same window "
        "%(own)d. Surplus <strong>%(surp)d</strong> - one of our own downloads was still in "
        "flight when the campaign stopped, and it landed afterwards. Nothing in that window "
        "is unattributable.</p>"
        "<p>The instrument was pairing each increase with the downloads made <em>after</em> "
        "it, which is why every sweep appeared to arrive carrying unexplained traffic. The "
        "counter settles late: measured settlement latencies %(lat)s seconds, longest "
        "%(maxlat)d - so an increase of two is not two readers, it is one queue draining. "
        "%(sweeps)d sweeps, gaps %(gaps)s seconds, widest provable wait %(maxlat)d seconds. "
        "That is a floor of about %(maxlatmin).1f minutes on how wide the counter's window "
        "is, and it is a floor measured by our own downloads, not assumed.</p>"
        "<p>It closed later: the counter has acknowledged %(counted)s downloads across the "
        "assets it watches, against %(made)s downloads made by this project. Downloads by "
        "anyone else: <strong>%(outside)s</strong>, interval "
        "%(interval)s. Nobody but this project has ever read that address, and the honest "
        "lesson of the first campaign is that it could not have known - its own design hid "
        "the answer, because it counted its downloads while one was still in flight.</p>"
        % {"base": base_c, "end": end_c, "inc": increase, "own": own, "surp": surplus,
           "lat": ", ".join(str(x) for x in lat) or "none",
           "maxlat": lat[0] if lat else 0,
           "maxlatmin": (lat[0] / 60.0) if lat else 0.0,
           "sweeps": len(rows) - 1,
           "span": int(sum(gaps) / 60.0) if gaps else 0,
           "gaps": ", ".join(str(int(g)) for g in gaps) or "n/a",
           "counted": counted, "made": made,
           "outside": outside if outside is not None else "not computed",
           "interval": interval or "n/a"}
    ) + _quiet_passages(sweep, esc, lat[0] if lat else 0)


def _span_s(a, b):
    """Seconds between two records' timestamps, or None if either is unusable."""
    import datetime as _dt
    f = "%Y-%m-%dT%H:%M:%SZ"
    try:
        return int((_dt.datetime.strptime(b, f) - _dt.datetime.strptime(a, f)).total_seconds())
    except Exception:
        return None


def _quiet_passages(sweep, esc, settle_s=None):
    """The quiet baseline: three attempts at one sentence, and what each attempt got wrong.

    The first was nine minutes of a hundred and wrote no beats. The second wrote its beats
    and then died with the count in its memory. The third is the first one that is actually
    a baseline - and run 43's contribution to it is a defect found in the ledger on the way
    to publishing it: the beat ring held 400 beats, which is 3 h 20 min of a thirty-second
    watch, and the watch it was about to be given was twenty-four hours long.
    """
    q2 = sweep.get("campaign2-quiet") or {}
    q3 = sweep.get("campaign3-quiet") or {}
    q4 = sweep.get("campaign4-long") or {}
    rows2 = q2.get("rows") or []
    rows3 = q3.get("rows") or []
    span2 = _span_s(q2.get("started_at"), q2.get("ended_at"))
    span3 = q3.get("observed_span_s")
    if span3 is None:
        span3 = _span_s(q3.get("started_at"), q3.get("ended_at"))
    beats3 = q3.get("beats") or []
    btot3 = _i(q3.get("beats_total"), None)
    if btot3 is None:
        btot3 = len(beats3)
    seen3 = q3.get("counts_seen") or sorted(
        set(b.get("count") for b in beats3 if b.get("count") is not None))
    beacon3 = q3.get("beacon") or []
    btot3ch = _i(q3.get("beacon_total"), None)
    if btot3ch is None:
        btot3ch = len(beacon3)
    berr3 = _i(q3.get("beacon_errors"), 0)
    bflat3 = sorted(set((b.get("requests"), b.get("not_this_project"))
                        for b in beacon3 if not b.get("error")))
    planned2 = q2.get("minutes")
    planned3 = q3.get("minutes")
    planned4 = _i(q4.get("minutes"), 0) or 1440
    pe4 = q4.get("poll_every") or 30.0
    has4 = bool(q4)
    polls4 = _i(q4.get("polls"), 0)
    beats4 = _i(q4.get("beats_total"), None)
    if beats4 is None:
        beats4 = len(q4.get("beats") or [])
    plan_reads4 = int(planned4 * 60.0 / pe4) if planned4 else 0
    mins3 = int(round((span3 or 0) / 60.0))
    # A watch whose record has not been checkpointed yet is a different thing from a watch
    # with nothing in it, and the page should not report either as zero reads: the campaign
    # writes its first record five minutes in, and before that it exists only in the process
    # table. Run 43 published one build in exactly that state and caught it here.
    if has4:
        p4close = ("At this reading it has made %d read%s and written %d beat%s of about %d."
                   % (polls4, "" if polls4 == 1 else "s", beats4,
                      "" if beats4 == 1 else "s", plan_reads4))
    else:
        p4close = ("At this reading it has a live process and no record yet - its first "
                   "checkpoint lands five minutes in, and until then the campaign exists "
                   "only in the process table. That gap is itself the shape of the problem "
                   "this page is about: a watch with nothing written down is "
                   "indistinguishable from a watch that never happened.")
    q2has_beats = "beats" in q2
    return (
        "<p>What replaced it was watched with zero downloads of its own, so any movement in "
        "the count is unambiguously someone else's. The first attempt at that is where this "
        "page's work began, because it lasted <strong>%(s2)s seconds of the %(p2)d-minute "
        "watch it was launched with</strong>: %(polls2)d polls, %(rows2)d row, %(dl2)d "
        "downloads of ours. The row is the count it opened at, %(c2)s, and inside those nine "
        "minutes nothing moved. It is also not a baseline for a second reason: it carries "
        "%(beats2)s beats at all - not an empty list, but no such field - because the code "
        "that writes a beat on every poll reached the file after that process had loaded it, "
        "and a running process reads its code once, at import. The instrument was patched "
        "while it was running and the running instrument never got the patch. The beat "
        "feature was committed 74 seconds after that process stopped, and the process "
        "stopped for a second, unrelated reason: it was a child of the run that started it, "
        "so when that run's session ended, it went with it.</p>"

        "<p>The reading of that is not that nobody read it in nine minutes. Nine minutes "
        "cannot support that sentence, and the counter settles %(maxlat)d seconds late on a "
        "measured basis, so a reader arriving in the last minute of that window would still "
        "be invisible to it. The reading is narrower and less flattering: a campaign whose "
        "finding is an absence has to write its evidence down while the absence is still "
        "happening, from a process that outlives the run that began it. The first quiet "
        "campaign failed the second requirement and the second quiet campaign had already "
        "failed the first.</p>"

        "<p><strong>%(l3)s</strong> is both of those fixed at once, and unlike the two "
        "before it, <strong>it finished</strong>. Launched at %(st3)s by a launcher that "
        "forks twice and detaches, so it is nobody's child and the session that began it "
        "could end without it. It planned %(p3)d minutes, one read every %(pe3)s seconds, "
        "and it observed %(s3)s seconds: %(polls3)d polls, %(rows3)d row(s), %(dl3)d "
        "downloads of ours, and <strong>%(bt3)d beats - one per poll, %(ring3)d of them still "
        "held by the ring, %(drop3)d dropped by it</strong>. Every beat reads the same "
        "number: %(seen3)s. The counter answered the identical value %(bt3)d times across "
        "%(hours3).1f hours of wall clock, and nothing arrived in any of it that this counter "
        "counts.</p>"

        "<p>That is a real baseline, because it has a second channel and both are flat. "
        "%(bt3ch)d reads of the beacon over the same %(mins3)d minutes: %(breq3)s requests, "
        "%(bnot3)s of them not this project's, %(berr3)d read failures. Flat counter with a "
        "flat beacon means nobody arrived - not by the file and not by the address that "
        "counts having asked for it. It is still not a readership figure, and the blind spots "
        "are worth naming rather than implying away: the counter settles late, so a reader in "
        "the last of those minutes may not be visible yet; neither channel sees a reader "
        "counted before the window opened, or one who took the file from somebody else's "
        "copy; and the beacon counts arrivals at an address this project published in its own "
        "pages, which is not the same thing as arrivals at the project.</p>"

        "<p><strong>What the baseline found on its way out is the more useful result.</strong> "
        "The beat ledger is a ring - it keeps the most recent %(ringcap)d beats - and "
        "%(ringcap)d beats at one every %(pe3)s seconds is %(ringh).1f hours. That was longer "
        "than any watch this project had run, so the ring had never bitten. The next watch is "
        "%(p4)d minutes at one read every %(pe4)s seconds, which is about %(plan4)d reads. "
        "Left alone, that campaign would have written %(plan4)d beats, kept the last "
        "%(ringcap)d of them, and overwritten the other %(lost4)d - %(lost4h).1f hours of the "
        "twenty-four - <em>without saying so anywhere in the record</em>. The file would have "
        "looked like a complete answer and been three and a half hours of one. For a campaign "
        "whose entire finding is an absence, the beats are the evidence: the second quiet "
        "campaign failed by never writing its evidence, and this one was one ring size away "
        "from writing it and then throwing it away. The same failure in a different costume, "
        "which is the reason it is worth publishing.</p>"

        "<p>Two changes, because the ring is still what gives the recent window its "
        "thirty-second resolution. The ring stays, and now carries its own account: "
        "<code>beats_total</code>, <code>beats_held</code>, <code>beats_dropped</code>, so a "
        "reader can tell a watch that dropped nothing from one that dropped %(lost4)d. And "
        "each campaign keeps one row per wall-clock hour for the whole watch - reads in that "
        "hour, the count at its first and last read, the minimum and maximum, and how many "
        "times the number moved - so a day becomes twenty-four rows and a quiet day becomes a "
        "column of zeros in a table that fits on one screen. A failed read is no longer "
        "written as a beat either: the older code beat after errors as well as after good "
        "reads, which put <code>count: null</code> into the beat series of any window that "
        "hit a 502 and made it look like a counter answering null. A ninety-second self-test "
        "caught one more of the same family - the first read of a campaign was counted as a "
        "movement, because last_count was empty and everything differs from empty, which "
        "would have printed changes 1 in the first hour bin of every campaign that ever sat "
        "still. Fixed, and the self-test is the reason it was caught before publication "
        "rather than after.</p>"

        "<p>The launcher had the same shape of flaw and the same kind of fix. It was "
        "hard-coded to launch one campaign - the third one - so a watch meant to span runs "
        "could only be restarted by hand-editing it, which is precisely the maintenance debt "
        "that kills a long-running instrument. It now takes the campaign on the command line, "
        "checks the process table before it starts anything, and <strong>refuses to launch a "
        "second copy of a label that is already running</strong>. That last one is not "
        "politeness: two watchers on one label interleave their writes into the same key, and "
        "the record they leave contradicts itself in a way no later reading can untangle.</p>"

        "<p><strong>%(l4)s</strong> is that watch. %(p4)d minutes, one read every %(pe4)s "
        "seconds, no downloads of its own, the beacon read every five minutes - the first "
        "instrument in this project built to accumulate across runs rather than be re-derived "
        "by each one. %(p4close)s It will still be running when the second "
        "declared-user-agent pass happens, which is the only reason it is worth twenty-four "
        "hours rather than three: the interesting question is whether the readership moves "
        "across the policy date, and a watch that ends before the date cannot answer it.</p>"
        % {"s2": span2 if span2 is not None else "n/a",
           "p2": int(planned2 or 0), "polls2": _i(q2.get("polls"), 0),
           "rows2": len(rows2), "dl2": len(q2.get("downloads") or []),
           "c2": _i(rows2[0].get("count")) if rows2 else "n/a",
           "beats2": "no" if not q2has_beats else "%d" % len(q2.get("beats") or []),
           "maxlat": _i(settle_s, 0),
           "l3": esc(str(q3.get("campaign") or "campaign3-quiet")),
           "st3": esc(str(q3.get("started_at") or "n/a")),
           "p3": int(planned3 or 0), "pe3": q3.get("poll_every"),
           "s3": span3 if span3 is not None else "n/a",
           "hours3": (span3 / 3600.0) if isinstance(span3, (int, float)) else 0.0,
           "polls3": _i(q3.get("polls"), 0), "rows3": len(rows3),
           "dl3": len(q3.get("downloads") or []),
           "bt3": btot3, "ring3": _i(q3.get("beats_held"), len(beats3)),
           "drop3": _i(q3.get("beats_dropped"), 0),
           "seen3": ", ".join(str(x) for x in seen3) or "n/a",
           "bt3ch": btot3ch, "berr3": berr3,
           "breq3": ", ".join(str(x[0]) for x in bflat3) or "no reading",
           "bnot3": ", ".join(str(x[1]) for x in bflat3) or "no reading",
           "ringcap": 400, "ringh": 400 * float(q3.get("poll_every") or 30.0) / 3600.0,
           "l4": esc(str(q4.get("campaign") or "campaign4-long")),
           "p4": int(planned4 or 1440), "pe4": pe4,
           "plan4": plan_reads4,
           "lost4": max(0, plan_reads4 - 400),
           "lost4h": max(0, plan_reads4 - 400) * float(pe4) / 3600.0,
           "polls4": polls4, "beats4": beats4,
           "mins3": mins3, "p4close": p4close}
    )

def agent_lane_block(esc, path=None):
    """The Agent lane gets a default on 2026-09-15, and this is the reading from before it."""
    import json as _json
    import os as _os
    p = path or _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                              "data", "declared_ua_baseline.json")
    try:
        with open(p) as f:
            store = _json.load(f)
    except Exception:
        return ""
    passes = store.get("passes") or []
    if not passes:
        return ""
    pr = passes[-1]
    s = pr.get("summary") or {}
    hosts = pr.get("hosts") or {}
    served_agent = []
    refused_control = []
    for d, r in hosts.items():
        a = r.get("declared_agent") or {}
        c = r.get("control") or {}
        if a.get("error") or c.get("error"):
            continue
        served_agent.append((d, a.get("status")))
        if a.get("status") == 200 and c.get("status") != 200:
            refused_control.append((d, c.get("status")))
    cross = ", ".join("%s (%s)" % (esc(d), st) for d, st in sorted(refused_control))
    unread = sorted(d for d, r in hosts.items()
                    if (r.get("declared_agent") or {}).get("error")
                    or (r.get("control") or {}).get("error"))
    return (
        "<h2>The Agent lane gets a default, and this is the reading from before it</h2>"

        "<p>On 1 July 2026 Cloudflare replaced its single \"block AI bots\" switch with three "
        "lanes - Search, Agent, Training - and set a date: from <strong>15 September "
        "2026</strong> the Agent and Training lanes are refused by default, at its edge, on "
        "pages that display ads, for zones that are new or on the free tier. Existing paid "
        "zones are not changed automatically, and the decision rests on classification - "
        "observed behaviour and the declared user agent together, not on a robots.txt line "
        "that a crawler may ignore. Nobody publishes the classifier, so what a given "
        "declaration gets you is an empirical question, and it is one that can only be asked "
        "in one direction after the 15th. It can be asked in both directions now.</p>"

        "<p>So the project read a fixed set of %(n)d hosts - the first %(n)d names in the "
        "top-domains list it already uses - twice each, changing one thing: the user agent. "
        "One request carries the agent declaration this project has used since its first "
        "census, with this project's address and a contact address in it. The other carries "
        "a browser-like string that declares nothing, sent with the same minimal headers, so "
        "the pair differs only in what is declared. Both strings are stored verbatim in the "
        "data, because in this policy the declaration is the subject. One request per host "
        "per user agent, sequential, no retries, redirects followed, TLS verification off so "
        "that a certificate problem cannot masquerade as a refusal. Stored: status, final "
        "URL, whether the response came from Cloudflare, the challenge markers, and a digest "
        "of the first two kilobytes, so that the second reading after 15 September can be "
        "compared against this one host by host.</p>"

        "<p>Read at %(at)s. Hosts: %(n)d. Readable: %(readable)d, of which %(cf)d answered "
        "from Cloudflare and %(ad)d carried the ad markers this project counts (overlap: "
        "%(both)d). Strong challenge markers on either user agent: "
        "<strong>%(strong)d</strong>. Unreadable: %(unread)d, and they are unreadable for "
        "dull reasons - hostnames in the list that do not resolve, such as %(unread_ex)s - "
        "which is why they stay in the set and are named rather than dropped: a set that "
        "silently loses its hard cases is a set that flatters its own next reading.</p>"

        "<p>The asymmetry worth keeping is not a challenge, it is a status code. On "
        "%(ncross)d hosts the declared agent's request was answered with a success status and "
        "the undeclared control's was not: "
        "%(cross)s. Those hosts saw the identical request, headers, method, path, network and "
        "time of day; the only difference was a string saying \"I am a bot and here is who to "
        "complain to\", and that string was <em>served</em> where the imitation was refused. "
        "The tidy story about declaring yourself is that honesty costs you access. On this "
        "reading, on these hosts, the cost of a bad imitation was higher. The asymmetry is "
        "not new to this project - an earlier declared-agent campaign classified the same "
        "shape and gave it a name, \"declared allowed, browser UA was not\" - but it is the "
        "first time it has been measured on the ad-carrying front pages of large hosts with a "
        "deadline attached to it. The control is not "
        "a browser and this page will not call it one - it is an undeclared client that is "
        "not trying very hard, which is exactly the thing the new default is written against "
        "- and it is worth remembering that the interpretation only becomes a claim about "
        "the classifier after the second reading.</p>"

        "<p>What this is not: it is not the web, it is %(readable)d readable hosts. It is not "
        "a rate measurement, since each host was asked once. It is not the providers' own "
        "definition of a page that displays ads - that operationalisation is this project's, "
        "and it is listed in the data so it can be argued with. And it is not a result: a "
        "baseline cannot show what a deadline does. On this set, if the second reading is "
        "identical, the honest sentence is that the default did not bite here - not that "
        "nothing changed anywhere.</p>"

        "<p class=\"note\">The set, both user agents, every status, the marker definitions "
        "and the earlier discarded pass: <a href=\"data/declared_ua_baseline.json\">"
        "declared_ua_baseline.json</a>. Re-reading is one command - "
        "<code>python3 probe_declared_ua.py --limit %(n)d --label after-20260915</code> - and "
        "the comparison is another: <code>python3 probe_declared_ua.py --compare</code>.</p>"
        % {"n": s.get("hosts", len(hosts)), "at": esc(str(pr.get("probed_at"))),
           "readable": s.get("readable", len(served_agent)),
           "cf": s.get("cloudflare_fronted", 0), "ad": s.get("ad_marked", 0),
           "both": s.get("cloudflare_and_ad", 0),
           "strong": _i(s.get("agent_challenged", 0)) + _i(s.get("control_challenged", 0)),
           "unread": s.get("unreadable", 0),
           "unread_ex": esc(", ".join(unread[:4]) or "none"),
           "ncross": len(refused_control), "cross": cross}
    )


def attribution_block(esc, path=None):
    """Attribution by ledger, and the one increment even the ledger cannot explain.

    The rule this project now uses: an increase in the download count is a reader only if
    it is larger than the number of downloads this project made on purpose inside the same
    window - and the authority on those downloads is the ledger, not the campaign's own
    record. A campaign can subtract only the downloads it scheduled itself; a control
    download made from another code path is invisible to it, and invisible downloads turn
    into readers. That is not hypothetical: it is how the quiet watch was lost.
    """
    import json as _json
    import os as _os

    here = _os.path.dirname(_os.path.abspath(__file__))
    path = path or _os.path.join(here, "data", "movement_attribution.json")
    try:
        with open(path) as fh:
            a = _json.load(fh)
    except Exception:
        return ""
    camps = a.get("campaigns") or {}
    if not camps:
        return ""

    rows = []
    for label in ("campaign4-long", "campaign1"):
        c = camps.get(label) or {}
        if not c.get("movements_n"):
            continue
        lag = c.get("lag_bracket_s") or []
        lag_txt = "n/a"
        if lag:
            lo = min(x[0] for x in lag)
            hi = max(x[1] for x in lag)
            lag_txt = "%d-%d s" % (lo, hi)
        rows.append(
            "<tr><td><code>%(lab)s</code></td><td>%(mov)d</td><td>+%(inc)d</td>"
            "<td>%(led)d</td><td><strong>%(read)d</strong></td><td>%(lag)s</td></tr>"
            % {"lab": esc(label), "mov": _i(c.get("movements_n")), "inc": _i(c.get("increase")),
               "led": _i(c.get("downloads_in_the_ledger_inside_the_window")),
               "read": _i(c.get("readers_this_campaign_can_claim")), "lag": esc(lag_txt)})

    # The increment no record explains: a rise between two series readings with no
    # deliberate download of ours anywhere in the interval.
    led = a.get("ledger") or []
    unexp = None
    try:
        with open(_os.path.join(here, "data", "counter_series.json")) as fh:
            readings = [(r.get("at"), _i(r.get("release_downloads_raw")))
                        for r in _json.load(fh)]
        readings = [x for x in readings if x[0] and x[1] is not None]
        for (t1, v1), (t2, v2) in zip(readings, readings[1:]):
            if v2 <= v1 or [e for e in led if e.get("at") and t1 <= e["at"] <= t2]:
                continue
            unexp = (t1, v1, t2, v2, v2 - v1)
            break
    except Exception:
        pass

    unexp_txt = ("none - every increase so far has a download of ours inside its "
                 "interval.")
    if unexp:
        unexp_txt = (
            "one. The count read <strong>%(v1)d</strong> at %(t1)s and "
            "<strong>%(v2)d</strong> at %(t2)s, an increase of %(inc)d inside "
            "%(mins)d minutes, and this project made <strong>zero</strong> deliberate "
            "downloads anywhere in that interval. It is either one of our own downloads "
            "settling late - the sixth of campaign1 was still absent %(floor_text)s after it was "
            "made, and appeared somewhere in this gap - or it is one reader. The record "
            "cannot say which, and it never will, because nobody was reading the count "
            "between those two moments. That is the whole argument for a watch that polls "
            "every 30 seconds: an instrument that reads once an hour measures the hour, "
            "not the counter."
            % {"v1": unexp[1], "t1": esc(unexp[0]), "v2": unexp[3], "t2": esc(unexp[2]),
               "inc": _i(unexp[4], 0),
               "floor_text": settlement()["floor_text"],
               "mins": int(_span_s(unexp[0], unexp[2]) or 0) // 60})

    # The paragraph below used to state the offset between the watch's launch and the control
    # download as a hand-entered "107 seconds". It is 97. A page whose whole subject is which
    # numbers can be trusted cannot carry a number nobody can trace, so it now renders from
    # the record: the campaign's start, the ledger entry inside its window, the movement.
    q4 = camps.get("campaign4-long") or {}
    q4_movs = q4.get("movements") or []
    _m0 = q4_movs[0] if q4_movs else {}
    _ours = (_m0.get("ours") or [{}])
    own_at = (_ours[0] or {}).get("at") if _ours else None
    own_delay = _span_s(q4.get("started_at"), own_at) if own_at else None
    if own_delay is None:
        own_delay = "unknown"
    q4_ctx = {"q4_start": esc(q4.get("started_at") or "an unrecorded time"),
              "own_delay": own_delay,
              "mov_at": esc(_m0.get("at") or "an unrecorded moment"),
              "movn": _i(q4.get("movements_n")),
              "q4_inc": _i(_m0.get("increase") or q4.get("increase")),
              "q4_rec": _i(q4.get("downloads_recorded_by_the_campaign")),
              "q4_led": _i(q4.get("downloads_in_the_ledger_inside_the_window")),
              "q4_read": _i(q4.get("readers_this_campaign_can_claim"))}

    return (
        "<h2>Attribution now reads the ledger, and the first thing it caught was our "
        "own watch</h2>"
        "<p>A quiet watch is supposed to be the clean case: it makes no downloads of its "
        "own, so any increase in the count belongs to somebody else. campaign4-long was "
        "launched on that premise at %(q4_start)s - and %(own_delay)s seconds later the "
        "run that launched it made a positive control download of its own, from a "
        "different code path. The watch could not see it, because a watch subtracts only "
        "the downloads it scheduled itself. Its record says "
        "<strong>%(q4_rec)d</strong> downloads of ours; the ledger says "
        "<strong>%(q4_led)d</strong>. It has %(movn)d movement, +%(q4_inc)d, at %(mov_at)s, "
        "and that movement is that download: the readers it can claim are "
        "<strong>%(q4_read)d</strong>. "
        "Without the ledger this page would have called it a reader - the third time in "
        "this project that a download of our own, made where the instrument was not "
        "looking, turned into a stranger. The previous two were caught after publication. "
        "This one was caught before, and only because a separate record exists that no "
        "campaign is allowed to keep on its behalf.</p>"
        "<table><tr><th>watch</th><th>movements</th><th>increase</th>"
        "<th>our downloads, from the ledger</th><th>readers it can claim</th>"
        "<th>settlement bracket</th></tr>%(rows)s</table>"
        "<p><strong>The one increase that is not attributed:</strong> %(unexp)s</p>"
        "<p><strong>An uncomfortable property of the counter itself:</strong> campaign1 "
        "made six deliberate downloads within 25 minutes of the start of a 30-minute watch, "
        "and the count rose by five, so one of "
        "ours had still not moved the number when the watch ended - and the count did rise "
        "once, later, in an interval where we downloaded nothing, which is the increment "
        "discussed above. That cuts against this project, not for it: a count that can miss "
        "one of our downloads for hours can miss a reader's, so <em>the count did not "
        "move</em> is a weaker statement than it looks, and every \"no readers\" figure on "
        "this page is a floor on readership, never a ceiling. It is also why the watch "
        "subtracts downloads from a ledger written at the moment of the download, instead "
        "of trusting the counter to confirm that a download happened.</p>"
        "<p><strong>How late the counter settles, measured only on deliberate downloads of "
        "ours:</strong> held for more than <strong>%(floor_text)s</strong> (download "
        "%(floor_download_at)s, count still reading %(floor_read_showed)s at "
        "%(floor_read_at)s) and released within <strong>%(ceiling_text)s</strong> (download "
        "%(ceiling_download_at)s, present by the read of %(ceiling_read_at)s). "
        "The ~15-hour latency once published on this page was withdrawn by run 40, twenty "
        "minutes after it went up: three latencies that differ by exactly the offset "
        "between the downloads are the arithmetic of one read, not a property of the "
        "counter. Run 44 replaced the 5.5-minute floor with %(floor_text)s - a <em>larger</em> "
        "blind spot, which is the direction that costs this project the most, and the "
        "reason the watch now polls through the lag rather than once after it. Run 45 renders "
        "both figures from "
        "<a href=\"data/retained_record_audit.json\">retained_record_audit.json</a>, because "
        "run 44 published them typed by hand and said so in the note below.</p>"
        "<p class=\"note\">Ledger, rule and per-movement brackets: "
        "<a href=\"data/movement_attribution.json\">movement_attribution.json</a>. Two "
        "defects fixed this run, and one still open. Fixed: the ledger's run label was "
        "hardcoded at 40, so the entry made by run 43 still says <em>run 40</em> - a stale "
        "label on the one entry that decided a movement; and this paragraph first went up "
        "claiming the control download came <em>107</em> seconds after the watch launched, "
        "because that number was typed by hand. It is <strong>97</strong> seconds, and the "
        "figure now renders from the campaign's start and the ledger entry inside it. Closed "
        "by run 45: the two settlement figures in the latency paragraph above "
        "(%(floor_text)s, %(ceiling_text)s) were hand-entered when run 44 wrote this note, and "
        "now render from the same audit that carries their timestamps - so the sentence and "
        "the record cannot drift apart again.</p>"
        % dict(q4_ctx, rows="".join(rows), unexp=unexp_txt, **settlement())
    )
