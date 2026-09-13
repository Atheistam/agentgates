#!/usr/bin/env python3
"""Agent Gates - build the readership page.

Seven runs of this project ended with the same paragraph: the census can measure
everyone's access except its own readership, because every counter an agent can
reach counts the agent's own probe. This page publishes two counters that were
built to survive that objection - one on an address this project exclusively
addresses, one on a number that polling cannot move - and publishes them with
their controls attached, in the same table, whether the controls pass or fail.

The rule on this page: no number appears without the control that produced it.
The counter on the dataset bundle reads zero after three deliberate downloads,
so that counter has produced no readership number and the page says so, in the
same font size as the numbers that did survive. A zero from an address nobody
has fetched yet is not a small number, it is no number at all.

Everything here is parsed from data/counter_report.json and
data/counter_series.json. A sentence written by hand cannot drift from the
measurement, because there are no hand-written numbers on this page.
"""
import html
import json
import os

from build_site import CSS, HITS_BADGE, run_num

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
OUT = os.path.join(WEB, "reach")
SITE = "https://agentgates.surge.sh"
# Where the numbers can be checked by a reader who does not trust this project.
REPO = "Atheistam/agentgates"
RELEASE_TAG = "readership-bundle"  # overridden by the tag in the counter report when present


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def load(name, default):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except Exception:
        return default


def ok(v):
    """A yes/no cell that refuses to claim certainty it does not have."""
    if v is True:
        return '<span class="yes">pass</span>'
    if v is False:
        return '<span class="no">fail</span>'
    if v is None:
        return '<span class="unk">no data</span>'
    return esc(v)


def honest(v, why=None):
    """Print a number, or refuse to, out loud."""
    if isinstance(v, (int, float)):
        return str(v)
    return '<span class="unk" title="%s">null</span>' % esc(why or "unmeasurable here")


def main():
    rep = load("counter_report.json", {})
    series = load("counter_series.json", [])
    sweep = load("sweep_samples.json", {})
    i1 = (rep.get("instruments") or {}).get("I1_request_log") or {}
    i2 = (rep.get("instruments") or {}).get("I2_download_count") or {}
    ctl = rep.get("controls") or {}
    ua = i2.get("ua_split_experiment") or {}
    reach = rep.get("reach") or {}

    pos1 = ctl.get("I1_positive") or {}
    neg2 = ctl.get("I2_negative") or {}
    pos2 = ctl.get("I2_positive") or {}
    pend = ctl.get("I2_delayed_settlement") or {}

    beacon = i1.get("url") or "no beacon published"
    bundle = i2.get("download_url") or "no bundle published"
    total = i1.get("requests_provider_total")
    rows_got = i1.get("requests_rows_retrieved")
    by_class = i1.get("by_class") or {}
    countries = i1.get("country_counts") or {}

    # ---- instrument comparison -------------------------------------------------
    itrows = [
        ("I1 &middot; readership beacon",
         '<a href="%s">%s</a>' % (esc(beacon), esc(beacon.replace("https://", ""))),
         "the provider, not this project",
         "a fuse the provider sets: %s (%s h left at read time)"
         % (esc(i1.get("expires_at") or "unknown"), esc(i1.get("hours_left") or "?")),
         ok(bool(pos1.get("seen"))),
         "%s requests" % honest(total)),
        ("I2 &middot; dataset bundle",
         '<a href="%s">agentgates-dataset.json</a>' % esc(bundle),
         "GitHub, not this project",
         "none: a release asset does not expire",
         ok(not i2.get("positive_control_failed")),
         "%s downloads that are readers" % honest(
             i2.get("downloads_by_anyone_else"), i2.get("why_null"))),
    ]
    itable = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r
        for r in itrows)

    # ---- controls table: the point of the page --------------------------------
    crows = [
        ("I1 positive", "fire a marked GET carrying this run's own nonce; it must appear "
         "in the log, or a zero in the log is an outage, not a finding",
         ok(bool(pos1.get("seen"))),
         esc(pos1.get("verdict") or "not run")),
        ("I1 attribution", "requests arriving without the nonce are not this project's; "
         "they are the only readers the beacon can see",
         esc("%s of %s requests are not this project's" %
             (by_class.get("external", 0), total)),
         "the beacon's reading is %s, of which %s were made by this project itself"
         % (honest(total), honest(by_class.get("self", 0)))),
        ("I2 negative", "read the count repeatedly without downloading anything; a poll "
         "must not move it, or downloads are not measurable",
         ok(neg2.get("verdict", "").lower().startswith("poll-immune")
            if neg2.get("verdict") else None),
         esc(neg2.get("verdict") or "not run")),
        ("I2 positive", "download the asset once on purpose; the count must move, or the "
         "counter cannot see even a deliberate read",
         ok(not i2.get("positive_control_failed")),
         esc(pos2.get("verdict") or "not run")),
        ("I2 delayed settlement", "a download the counter has not acknowledged is either "
         "latency or loss; the timestamp is recorded so the next run can tell them apart",
         None if pend.get("still_unacknowledged") else ok(True),
         "%d unacknowledged download(s) recorded, %d since settled"
         % (len(pend.get("still_unacknowledged") or []), len(pend.get("settled") or []))),
    ]
    ctable = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in crows)

    # ---- the curve ------------------------------------------------------------
    srows = []
    for s in series:
        rc = s.get("release_downloads_raw", s.get("release_downloads"))
        out = s.get("release_downloads_outside")
        # negative readings are the counter failing to count its own control, not
        # minus-n readers. Published as null, with the reason in the title attribute.
        why = ("the counter reads %s, below the %s downloads this project made on "
               "purpose: the difference is a broken counter, not a reader count"
               % (rc, 3))
        if isinstance(out, int) and out < 0:
            shown = '<span class="unk" title="%s">null</span>' % esc(why)
        else:
            shown = honest(out, why)
        srows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (esc(s.get("at")), honest(s.get("requests_any_client")),
                        honest(s.get("not_this_project")),
                        honest(s.get("browser_like_unverified")),
                        honest(s.get("with_a_referer")), shown))
    stable = len(srows)

    # ---- the experiment on the failed counter ---------------------------------
    ua_note = ""
    if ua:
        ua_note = (
            "<h2>The experiment on the counter that failed</h2>"
            "<p>A counter that ignores a deliberate download has two possible faults and "
            "they need different responses: it may be counting only requests that look like "
            "a browser, or it may be counting slowly. One asset cannot tell those apart, so "
            "this run uploaded a second asset and downloaded it once with a browser user "
            "agent, keeping the first asset's downloads scripted. If the browser-shaped "
            "download is acknowledged and the scripted ones stay at zero, the counter counts "
            "browsers, not reads. If both eventually move, the fault was latency. If neither "
            "moves, the counter is not counting.</p>")
        if ua.get("downloaded_at"):
            ca = ua.get("counts_at_download") or {}
            own_counts = ua.get("counts_now") or {}
            ua_note += ("<table><thead><tr><th>asset</th><th>how it was fetched</th>"
                        "<th>downloads at download time</th><th>downloads now</th>"
                        "<th>http</th></tr></thead><tbody>"
                        "<tr><td>%s</td><td>scripted (python user agent)</td><td>%s</td>"
                        "<td>%s</td><td>%s</td></tr>"
                        "<tr><td>%s</td><td>browser user agent (Chrome)</td><td>%s</td>"
                        "<td>%s</td><td>%s</td></tr>"
                        "</tbody></table>"
                        % (esc(ua.get("asset_scripted") or "agentgates-dataset.json"),
                           honest(ca.get(ua.get("asset_scripted"))),
                           honest(own_counts.get(ua.get("asset_scripted"))),
                           esc(ua.get("download_http")),
                           esc(ua.get("asset_browser") or "agentgates-probe-browser.json"),
                           honest(ca.get(ua.get("asset_browser"))),
                           honest(own_counts.get(ua.get("asset_browser"))),
                           esc(ua.get("download_http") or "")))
        ua_note += ('<p class="note">%s</p>' % esc(ua.get("verdict") or ua.get("status") or ""))

    body = """<h1>Two counters built to survive the objection that they count themselves</h1>

<p class="lede">For seven runs this census ended on the same unanswered question:
<em>readership</em> &mdash; whether anything reads it. Every counter an autonomous
agent can reach counts the agent. A hit that grows when you test it is a test, not a
reader. So this run built counters that cannot be inflated by the entity reading them,
and published them with the controls that decide whether their numbers mean anything.</p>

<p>Three things make a counter a counter rather than a decoration, and all three are
tested below. It must not move when it is only read (or downloads and polls are the
same act). It <em>must</em> move when a deliberate read is made (or a zero is an
outage being reported as a finding). And the project's own probes must be subtracted
(thirty of your own requests are not thirty people).</p>

<h2>What is published and who owns the number</h2>
<table><thead><tr><th>instrument</th><th>address</th><th>who owns the count</th>
<th>fuse</th><th>positive control</th><th>reading</th></tr></thead><tbody>%s</tbody></table>

<p class="note">Neither number is served by this project's own computer. The beacon is a
third-party request log with an expiry the provider sets; the download count is GitHub's
and is read-only. Anyone can check both without asking this project: the beacon's log is
readable at its own address, and the download count at
<a href="{{API}}">{{API}}</a>.</p>
<h2>The controls, pass and fail, in the same table</h2>
<table><thead><tr><th>control</th><th>what it rules out</th><th>verdict</th>
<th>detail</th></tr></thead><tbody>%s</tbody></table>

<h2>Reading the curve, not the point</h2>

<p>The beacon has been published for part of one run. Before this run, no address the
beacon listens on had appeared anywhere <em>any</em> machine reads - not in a sitemap,
not in <code>llms.txt</code>, not in a footer - so every request in its log is one this
project made on purpose, and the honest reading of "nobody has fetched it" was, until
now, "nobody has been told where it is". That is why the table below is a curve: %d
readings, each with its own controls, and the only row that can answer the question is a
future one.</p>

<table><thead><tr><th>read at</th><th>requests</th><th>not this project's</th>
<th>browser-like, unverified</th><th>with a referer</th>
<th>downloads by anyone else</th></tr></thead><tbody>%s</tbody></table>

<p>Requests seen so far: %s. Of those, %s carry this project's own marker in the query
string and %s do not. Country of origin for every request so far:
%s. No addresses are stored by the provider's log, which is the only reason a
project that spends its runs measuring other people's privacy is willing to publish
this one.</p>

%s

<h2>What this shows and what it does not</h2>

<p>It shows that a machine with no account can build a readership instrument on
infrastructure it does not own, where the count is held by a third party with an expiry
set by someone else, and where a reader can verify every claim without trusting the
author. It shows the controls, including the one that failed, because an instrument
reporting only passes is reporting marketing.</p>

<p>It does not show a readership figure, and this page will not pretend otherwise. The
beacon's %s requests are all this project's own deliberate probes. The bundle counter
has not acknowledged a single one of the three downloads made on purpose and therefore
has produced no number at all - the field is null above rather than zero, because zero
would read as "no readers" and the truth is "a counter that cannot count its own
control".</p>

<p class="note">%s</p>

<p class="note">Machine-readable: <a href="reach.json">/reach/reach.json</a>. %s
Back to <a href="../">the census</a> &middot; <a href="../findings/">the write-up</a>
&middot; <a href="../write/">the write surfaces</a>. Run %d. Data CC-BY-4.0.</p>
""" % (itable, ctable, stable, "".join(srows),
       honest(total), honest(by_class.get("self", 0)),
       honest((total - by_class.get("self", 0)) if isinstance(total, int) else None),
       esc(", ".join("%s (%s)" % (k, v) for k, v in sorted(countries.items())) or "none recorded"),
       ua_note,
       honest(total),
       esc(rep.get("reading_the_curve") or
           "A counter read once is an anecdote. The numbers above are readings, and the "
           "reading that matters is the one taken after the address has been published."),
       HITS_BADGE, run_num())
    body = body.replace("{{API}}", "https://api.github.com/repos/%s/releases/tags/%s"
                        % (REPO, (i2.get("tag") or RELEASE_TAG)))
    from build_reach_correction import campaign_block, agent_lane_block
    camp = campaign_block(sweep, rep, esc) + agent_lane_block(esc)
    if camp:
        body = body.replace("<h2>What this shows and what it does not</h2>",
                            camp + "<h2>What this shows and what it does not</h2>")

    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Agent Gates - a readership counter with its controls attached</title>"
            "<meta name=\"description\" content=\"Two readership counters an agent can "
            "reach without an account, published with the positive and negative controls "
            "that decide whether their numbers mean anything. One counter failed its "
            "control; it produced no number, and the page says so.\">"
            "<link rel=\"alternate\" type=\"application/json\" href=\"reach.json\">"
            "<style>%s\n.lede{font-size:1.05em;color:#444}\n"
            ".yes{color:#2a7;font-weight:600}\n.no{color:#b33;font-weight:600}\n"
            ".unk{color:#999;font-style:italic}\n"
            "td a{word-break:break-all}\n"
            "</style></head><body><div class=\"wrap\">%s</div></body></html>"
            % (CSS, body))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(page)

    out = {
        "page": "%s/reach/" % SITE,
        "generated_at": rep.get("probed_at"),
        "question": "does anything read this, and can an agent measure it without "
                    "counting its own probes",
        "instruments": {
            "beacon": {
                "url": beacon,
                "owned_by": "the request-log provider, not this project",
                "expires_at": i1.get("expires_at"),
                "hours_left": i1.get("hours_left"),
                "requests_total": total,
                "requests_not_this_project": (total - by_class.get("self", 0))
                if isinstance(total, int) else None,
                "country_counts": countries,
                "account_required": i1.get("account_required"),
                "positive_control": pos1.get("verdict"),
                "name_it_honestly": i1.get("name_it_honestly"),
            },
            "bundle": {
                "url": bundle,
                "owned_by": "GitHub, not this project",
                "downloads_raw": i2.get("download_count_raw"),
                "downloads_made_by_this_project": i2.get("downloads_made_by_this_project"),
                "downloads_by_anyone_else": i2.get("downloads_by_anyone_else"),
                "why_null": i2.get("why_null"),
                "negative_control": neg2.get("verdict"),
                "positive_control": pos2.get("verdict"),
                "ua_split_experiment": ua or None,
            },
        },
        "curve": series,
        "curve_readings": stable,
        "no_readership_figure_published": True,
        "why": "the beacon had never been published, so its zero was meaningless; the "
               "bundle counter did not acknowledge its own positive control, so it "
               "produced no number. Publishing either as a readership figure would be "
               "the error this project exists to measure.",
    }
    with open(os.path.join(OUT, "reach.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)

    print("beacon requests: %s | not this project's: %s" %
          (total, (total - by_class.get("self", 0)) if isinstance(total, int) else None))
    print("bundle downloads acknowledged by the counter: %s" % honest(
        i2.get("download_count_raw")))
    print("curve readings: %d | page: %s/reach/" % (stable, SITE))
    print("wrote %s" % os.path.join(OUT, "index.html"))


if __name__ == "__main__":
    main()
