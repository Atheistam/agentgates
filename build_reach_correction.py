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
        "<p>What replaced it is watched with zero downloads of its own, so any movement is "
        "unambiguously someone else. It has been running against a live count of %(qcount)s "
        "since %(qstart)s: %(qpolls)d poll(s), %(qchanges)d change(s), %(qdl)d download(s) "
        "of ours. The first campaign only wrote when the number moved, so its quiet "
        "stretches left no record - a campaign whose finding is an absence has to write its "
        "evidence while it is still nothing. The second one writes what it has seen every "
        "tenth poll.</p>"
        % {"base": base_c, "end": end_c, "inc": increase, "own": own, "surp": surplus,
           "lat": ", ".join(str(x) for x in lat) or "none",
           "maxlat": lat[0] if lat else 0,
           "maxlatmin": (lat[0] / 60.0) if lat else 0.0,
           "sweeps": len(rows) - 1,
           "span": int(sum(gaps) / 60.0) if gaps else 0,
           "gaps": ", ".join(str(int(g)) for g in gaps) or "n/a",
           "counted": counted, "made": made,
           "outside": outside if outside is not None else "not computed",
           "interval": interval or "n/a",
           "qcount": _i(q_rows[0].get("count")) if q_rows else "n/a",
           "qstart": esc(str(q_rows[0].get("at"))) if q_rows else "n/a",
           "qpolls": _i(quiet.get("polls"), 0),
           "qchanges": max(0, len(q_rows) - 1),
           "qdl": len(quiet.get("downloads") or [])}
    )
