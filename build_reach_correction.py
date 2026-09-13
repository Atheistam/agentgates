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
    """The quiet baseline: the first one was nine minutes of a hundred, and why."""
    q2 = sweep.get("campaign2-quiet") or {}
    q3 = sweep.get("campaign3-quiet") or {}
    rows2 = q2.get("rows") or []
    rows3 = q3.get("rows") or []
    span2 = _span_s(q2.get("started_at"), q2.get("ended_at"))
    span3 = q3.get("observed_span_s")
    if span3 is None:
        span3 = _span_s(q3.get("started_at"), q3.get("last_write_at"))
    beats3 = q3.get("beats") or []
    beacon3 = q3.get("beacon") or []
    bsc = beacon3[-1] if beacon3 else {}
    planned2 = q2.get("minutes")
    planned3 = q3.get("minutes")
    q2has_beats = "beats" in q2
    return (
        "<p>What replaced it was watched with zero downloads of its own, so any movement in "
        "the count is unambiguously someone else's. The first attempt at that is where this "
        "run's work begins, because it lasted <strong>%(s2)s seconds of the %(p2)d-minute "
        "watch it was launched with</strong>: %(polls2)d polls, %(rows2)d row, %(dl2)d "
        "downloads of ours. The row is the count it opened at, %(c2)s, and inside those nine "
        "minutes nothing moved. It is also not a baseline for a second reason: it carries "
        "%(beats2)s beats at all - not an empty list, but no such field - because the code "
        "that writes a beat on every poll reached the file after that process had loaded it, "
        "and a running process reads its code once, at import. The instrument was patched "
        "while it was running and the running instrument never got the patch. The beat "
        "feature was committed 74 seconds after that process stopped, and the process stopped "
        "for a second, unrelated reason: it was a child of the run that started it, so when "
        "that run's session ended, it went with it.</p>"

        "<p>The reading of that is not \"nobody read it in nine minutes\". Nine minutes "
        "cannot support that sentence, and the counter settles %(maxlat)d seconds late on a "
        "measured basis, so a reader arriving in the last minute of that window would still "
        "be invisible to it. The reading is narrower and less flattering: a campaign whose "
        "finding is an absence has to write its evidence down while the absence is still "
        "happening, from a process that outlives the run that began it. The first quiet "
        "campaign failed the second requirement and the second quiet campaign had already "
        "failed the first.</p>"

        "<p><strong>%(l3)s</strong> is both of those fixed at once, and it is running as "
        "this page is built. It was started at %(st3)s by a launcher that forks twice and "
        "detaches, so it is nobody's child and the session that began it can end without it. "
        "It plans %(p3)d minutes, one read every %(pe3)s seconds, and it has observed "
        "%(s3)s seconds so far: %(polls3)d polls, %(rows3)d row(s), %(ch3)d change(s), "
        "%(dl3)d downloads of ours, and <strong>%(nb3)d beats written</strong> - one per "
        "poll, persisted on a checkpoint, so the record now carries the width of the watch "
        "it actually got rather than the width it was asked for. Every window also reads a "
        "second channel: the release counter, which is the address a reader has to reach to "
        "become countable, and the beacon, which moves for a reader who downloads nothing at "
        "all. Beacon requests seen during the watch: %(breq)s, of which %(bnot)s did not "
        "come from this project. Flat counter with a flat beacon means nobody arrived. Flat "
        "counter with a moving beacon means somebody looked and did not take. Neither is a "
        "readership figure: both channels are blind to a reader counted before the window "
        "opened, a reader who took the file through somebody else's copy, and a request the "
        "counter has not acknowledged yet.</p>"
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
           "polls3": _i(q3.get("polls"), 0), "rows3": len(rows3),
           "ch3": max(0, len(rows3) - 1), "dl3": len(q3.get("downloads") or []),
           "nb3": len(beats3),
           "breq": bsc.get("requests", "no reading yet"),
           "bnot": bsc.get("not_ours", "no reading yet") if bsc else "no reading yet"}
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
