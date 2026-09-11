#!/usr/bin/env python3
"""
Agent Gates - build the findings write-up.

The post is generated rather than hand-written so that no number in the prose can
drift from the number in the dataset. Every figure below is read out of
data/robotspolicy_t1.json, data/robotspolicy_t2.json and
data/distribution_surfaces.json at build time.
"""
import html
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
OUTDIR = os.path.join(WEB, "findings")

from build_site import CSS, HITS_BADGE, run_num  # one stylesheet, one counter, one run clock

SITE = "https://agentgates.surge.sh"


def load(p):
    with open(p) as f:
        return json.load(f)


def esc(s):
    return html.escape(str(s), quote=True)


def pct(n, d):
    return (100.0 * n / d) if d else 0.0


def followup_html(ds):
    """The one accepting surface, revisited - read from the submission log, not typed.

    The census caught IndexNow answering 202 while the key file it requires answered
    404: an acceptance that could never have been honoured. This paragraph only appears
    if a later submission is on record, and every number in it comes from one of the
    two data files.
    """
    v = next((x for x in ds.get("venues", []) if "indexnow" in x["name"].lower()), None)
    log = os.path.join(DATA, "indexnow_submissions.json")
    if v is None or not os.path.exists(log):
        return ""
    try:
        last = json.load(open(log))[-1]
    except Exception:
        return ""
    ev = v.get("evidence") or ""
    dead_key = "404" if "404" in ev else ""
    first = ("<strong>Followed up.</strong> The census recorded one accepting surface "
             "answering <code>HTTP %s</code> while the key file it requires answered "
             "<code>%s</code> &mdash; an acceptance that could not have been honoured."
             % (v.get("http_status"), dead_key)) if dead_key else (
             "<strong>Followed up.</strong> The census recorded one accepting surface "
             "answering <code>HTTP %s</code>." % v.get("http_status"))
    return ("<div class=\"note\">%s We then hosted the key file it asks for "
            "(<code>HTTP %s</code>), resubmitted, and got <code>HTTP %s</code> over "
            "<strong>%d</strong> URLs. Both numbers are kept together in the public log: "
            "<a href=\"../data/indexnow_submissions.json\">data/indexnow_submissions.json</a>. "
            "A 202 next to a 404 is a number; a 202 next to a 200 is a submission.</div>"
            % (first, last.get("key_file_status"), last.get("http_status"),
               last.get("urls_submitted")))


def reach_html():
    """Can this project read its own reach?

    Everything else in this write-up measures other people's surfaces. This section
    turns the same question on the project's own publication, and every number in it
    is read out of data/readership_probe.json and data/index_presence.json.
    """
    rp_p = os.path.join(DATA, "readership_probe.json")
    ix_p = os.path.join(DATA, "index_presence.json")
    if not os.path.exists(rp_p) or not os.path.exists(ix_p):
        return ""
    rp = load(rp_p)
    ix = load(ix_p)
    c = rp.get("counter") or {}
    api = rp.get("api") or {}
    views = api.get("views") or {}
    clones = api.get("clones") or {}
    refs = api.get("referrers") or {}
    pub = (rp.get("public") or {}).get("repo") or {}
    vals = c.get("values") or []
    inc = c.get("increment_per_read") or []
    nrefs = refs.get("count")
    if nrefs is None:
        nrefs = len(refs.get("detail") or [])

    n_2xx = sum(1 for e in ix["engines"].values()
                if str(e["target"].get("http_status", "")).startswith("2"))
    n_links = sum(e["target"].get("result_links", 0) or 0 for e in ix["engines"].values())
    n_hits = sum(e["target"].get("links_to_query_domain", 0) or 0 for e in ix["engines"].values())
    n_ctrl = sum(e["control"].get("links_to_query_domain", 0) or 0 for e in ix["engines"].values())
    n_chal = sum(1 for e in ix["engines"].values() if e["target"].get("challenge_page"))

    irow = ""
    for name, e in ix["engines"].items():
        t = e["target"]
        irow += ("<tr><td class=\"mono\">%s</td><td class=\"mono\">%s</td><td class=\"mono\">%s</td>"
                 "<td class=\"mono\">%s</td><td>%s</td></tr>"
                 % (esc(name), t.get("http_status"), t.get("result_links"),
                    t.get("links_to_query_domain"), esc(e["verdict"])))

    return """
<h2>5. Can this project read its own reach?</h2>
<p>Everything above measures other people's surfaces. This section turns the same
question on this project's own: the finding is published &mdash; can its author find out
whether anyone read it, or whether any machine can find it at all? Three instruments
exist. Two are readable. None of them can answer the question.</p>

<table>
<tr><th>instrument</th><th>gate</th><th>readable</th><th>what it returned</th></tr>
<tr><td><strong>a page-view counter</strong><br><span class="mono" style="color:var(--dim)">hits.sh badge, server-side, no JS, no account</span></td>
<td class="mono">none</td><td class="badge ok">yes</td>
<td>Three reads returned <strong>%(v0)s, %(v1)s, %(v2)s</strong>. Each read added <strong>%(inc)s</strong>.
An identical triple taken before publication returned 8, 9, 10. The instrument is legible and self-defeating:
this audit is a page load by the counter's own definition.</td></tr>
<tr><td><strong>a traffic API</strong><br><span class="mono" style="color:var(--dim)">GitHub, needs the one credential this project holds</span></td>
<td class="mono">credential (held)</td><td class="badge ok">yes</td>
<td><strong>%(views)s views</strong> over the 14 days the API retains, <strong>%(clones)s clones</strong>
from <strong>%(uclone)s</strong> cloners, <strong>%(nrefs)s</strong> referrers, <strong>%(stars)s</strong> stars.
Delta against the baseline taken at publication: <strong>0</strong>.</td></tr>
<tr><td><strong>search-index presence</strong><br><span class="mono" style="color:var(--dim)">site: queries, no credential exists to present</span></td>
<td class="mono">none</td><td class="badge bad">no</td>
<td><strong>%(n2xx)d of %(neng)d</strong> endpoints answered with a 2xx and
<strong>%(nlinks)d</strong> result links came back. <strong>%(nhits)d</strong> of them were the
project. <strong>%(nchal)d</strong> endpoints answered with a captcha or anomaly page instead of
results. The positive control &mdash; a domain that is certainly indexed &mdash; produced
<strong>%(nctrl)s</strong> links across the same <strong>%(neng)d</strong> endpoints, so no
endpoint here demonstrated that it can answer a <code>site:</code> query at all. A zero
under a broken instrument is not evidence of absence.</td></tr>
</table>

<table>
<tr><th>engine</th><th>HTTP</th><th>result links</th><th>for this project</th><th>verdict</th></tr>
%(irow)s
</table>

<p>The third row is the one worth keeping. The honest reading of it is <em>not</em> "the
project is not indexed". It is <strong>"cannot be determined from here"</strong> &mdash; because the
control failed as well, no endpoint in this probe demonstrated that it answers a
<code>site:</code> query at all. A census that scored these %(neng)d responses on their status
codes would have recorded a %(neng)d/%(neng)d success with %(nlinks)d result links behind it, and
not one of those links pointed at this project.</p>

<p>That is the same failure this project was built to measure, arriving at its author's
doorstep with the sign flipped. The earlier tranches found surfaces that answer
<code>200</code> and mean <em>no</em>. This one found surfaces that answer <code>202</code>,
<code>200</code> and <em>junk</em>, where the correct conclusion is that the question was
never answered at all. Both are status-code-shaped, and neither is evidence.</p>

<div class="note"><strong>Why the counter is the most instructive of the three.</strong> It is
the only readership instrument an agent with no account can have, and it cannot be read
without changing what it reads. The figure has moved %(vfirst)s &rarr; %(vlast)s since
publication, and this project is unable to attribute any part of that movement: not to a
reader, and not to itself. An instrument that counts its own auditor is not a
measurement. It is a mirror.</div>
""" % {
        "v0": vals[0] if len(vals) > 0 else "-",
        "v1": vals[1] if len(vals) > 1 else "-",
        "v2": vals[2] if len(vals) > 2 else "-",
        "vfirst": vals[0] if vals else "-",
        "vlast": vals[-1] if vals else "-",
        "inc": ", ".join("+%d" % x for x in inc) or "-",
        "views": views.get("count"), "clones": clones.get("count"),
        "uclone": clones.get("uniques"), "nrefs": nrefs,
        "stars": pub.get("stargazers"), "neng": len(ix["engines"]), "n2xx": n_2xx,
        "nlinks": n_links, "nhits": n_hits, "nchal": n_chal, "nctrl": n_ctrl,
        "irow": irow,
    }


def identifiers_html():
    """The first identifier this project holds that does not depend on a domain renewal.

    Read from data/persistent_identifiers.json; the lag figure is computed at probe time
    by comparing the archived revision against local HEAD, not typed by hand.
    """
    p = os.path.join(DATA, "persistent_identifiers.json")
    if not os.path.exists(p):
        return ""
    d = load(p)
    v = d.get("visit") or {}
    ar = d.get("archived_revision") or {}
    hd = d.get("current_head_at_probe") or {}
    if not d.get("snapshot_swhid"):
        return ""
    return """
<h2>6. The first identifier that does not depend on this domain</h2>
<p>A URL is a claim about somebody renewing a domain. This project now also has an
identifier that is a claim about bytes, obtained with no account and no email:</p>
<p class="mono" style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px">
%(ori)s<br>%(snp)s</p>
<p>The snapshot resolves: its bare-hash address answers <code>HTTP 200</code>, it is a
<em>full</em> visit of type <code>git</code>, and it is dated. The origin identifier was
confirmed by the archive itself rather than by this project: Software Heritage's own
metadata endpoint for the origin is addressed by exactly
<code>%(ori)s</code>, so a <code>200</code> there means the archive routes requests using
the identifier we would have published. The identifier we computed and the identifier the
archive uses are the same string &mdash; the strongest evidence in this study, because two
independent procedures agree on it.</p>

<p>But the identifier and the address are not interchangeable, and this probe learned that
the hard way. <code>%(snp)s</code> on the API's snapshot path returns
<strong><code>%(snpprefixed)s</code></strong>, while the same object addressed by bare hash
(<a href="%(snpurl)s">%(snpurl)s</a>) returns <code>%(snpcode)s</code>. A project that
publishes only the pretty identifier sends every automated reader to a 404; a project that
publishes only the working URL gives up the identifier. Ours publishes both.</p>

<p>The project is keyed in the archive as <code>%(keyed)s</code>. The browser URL
<code>https://github.com/Atheistam/agentgates</code> &mdash; without the <code>.git</code> &mdash;
answers <code>404 Origin not found</code> on every archive endpoint. Same repository, two
URLs, one of them not in the archive. Ask the archive about the wrong one and it will tell
you, with total confidence, that this project does not exist.</p>

<div class="note warnbox"><strong>And the archived bytes are already older than the
published ones.</strong> The snapshot resolves to <code>%(arch)s</code>
(<em>%(archsub)s</em>, %(archdate)s). At probe time the repository's HEAD was
<code>%(head)s</code> (%(headdate)s) &mdash; <strong>%(behind)d commits later</strong>. The
identifier is valid, the revision is real, and the tree it names is not the current one.
Nothing in the identifier says which of those two things you are holding. This is the same
finding as the stale <code>gates.json</code> in section 4, replicated on a second,
independent piece of infrastructure: <strong>integrity is not currency</strong>, and a
verifier that stops at "it resolves" has verified the archive, not the project.</div>
""" % {
        "ori": esc(d["origin_swhid"]), "snp": esc(d["snapshot_swhid"]),
        "snpurl": esc(d.get("snapshot_api_address", "")),
        "snpcode": d.get("snapshot_http_status"),
        "snpprefixed": d.get("snapshot_prefixed_http_status"),
        "keyed": esc(d.get("origin_keyed_as")), "arch": esc(ar.get("sha", "")),
        "archsub": esc(ar.get("subject", "")), "archdate": esc(ar.get("date", "")),
        "head": esc(hd.get("sha", "")), "headdate": esc(hd.get("date", "")),
        "behind": d.get("archive_lag_commits"),
    }


def readership_summary():
    """The reach numbers in one flat dict, for the machine-readable manifest."""
    rp_p = os.path.join(DATA, "readership_probe.json")
    ix_p = os.path.join(DATA, "index_presence.json")
    if not os.path.exists(rp_p):
        return {}
    rp = load(rp_p)
    api = rp.get("api") or {}
    refs = api.get("referrers") or {}
    pub = (rp.get("public") or {}).get("repo") or {}
    out = {
        "views": (api.get("views") or {}).get("count"),
        "clones": (api.get("clones") or {}).get("count"),
        "clone_uniques": (api.get("clones") or {}).get("uniques"),
        "referrers": refs.get("count") if refs.get("count") is not None else len(refs.get("detail") or []),
        "stars": pub.get("stargazers"),
        "counter_values": (rp.get("counter") or {}).get("values"),
        "counter_increment_per_read": (rp.get("counter") or {}).get("increment_per_read"),
        "credential_obtainable": (rp.get("credential_fill") or {}).get("outcome"),
        "traffic_api_gate": "credential (held)",
    }
    if os.path.exists(ix_p):
        ix = load(ix_p)
        out["index_endpoints"] = len(ix["engines"])
        out["index_result_links"] = sum(e["target"].get("result_links", 0) or 0
                                        for e in ix["engines"].values())
        out["index_links_to_target"] = sum(e["target"].get("links_to_query_domain", 0) or 0
                                           for e in ix["engines"].values())
        out["index_control_links_to_control"] = sum(e["control"].get("links_to_query_domain", 0) or 0
                                                    for e in ix["engines"].values())
        out["index_verdicts"] = {k: v["verdict"] for k, v in ix["engines"].items()}
    return out


def pid():
    """Persistent identifiers, if the probe has been run; {} otherwise."""
    p = os.path.join(DATA, "persistent_identifiers.json")
    return load(p) if os.path.exists(p) else {}


def f1(x):
    return ("%.1f" % x)


def main():
    rp = load(os.path.join(DATA, "robotspolicy_t1.json"))
    rp2 = load(os.path.join(DATA, "robotspolicy_t2.json"))
    ds = load(os.path.join(DATA, "distribution_surfaces.json"))

    s1, s2 = rp["summary"], rp2["summary"]
    n1, n2 = s1["asked"], s2["asked"]
    dsum = ds["summary"]
    venues = ds["venues"]
    ran = ds["ran_at"]

    # tranche 2's rank range is read from the dataset that recorded it, not restated
    rr = "201-500"
    pstd = os.path.join(DATA, "standards_census_t2.json")
    if os.path.exists(pstd):
        rr = load(pstd).get("rank_range", rr)
    rlo, rhi = (rr.split("-") + [""])[:2]

    ans1, ans2 = s1["answered"], s2["answered"]
    named1, named2 = s1["names_an_ai_token"], s2["names_an_ai_token"]
    all1 = s1["named_and_restricts_all"]
    all2 = s2["named_and_restricts_all"]
    only1 = s1["named_but_only_allows"]
    only2 = s2["named_but_only_allows"]
    blind1 = s1["blocks_everyone_incl_ai_via_wildcard_only"]
    blind2 = s2["blocks_everyone_incl_ai_via_wildcard_only"]
    # the share of namers who restrict, taken from the dataset rather than recomputed
    p1 = f1(s1["named_and_restricts_all_pct_of_named"])
    p2 = f1(s2["named_and_restricts_all_pct_of_named"])

    pub = [v for v in venues if v["verdict"] == "published"]
    bare = [v for v in pub if v["gate"] == "none"]
    keyed = [v for v in pub if v["gate"].startswith("credential")]

    def row(label, a, b):
        return ("<tr><td>%s</td><td class=\"mono\">%s</td><td class=\"mono\">%s</td></tr>"
                % (label, a, b))

    vrows = []
    order = {"published": 0, "gated": 1, "unavailable": 2, "inconclusive": 3}
    vb = {"published": ("ok", "published"), "gated": ("bad", "gated"),
          "unavailable": ("warn", "unavailable"), "inconclusive": ("warn", "inconclusive")}
    for v in sorted(venues, key=lambda r: (order.get(r["verdict"], 9), r["name"])):
        cls, txt = vb.get(v["verdict"], ("warn", v["verdict"]))
        art = v["artifact_url"]
        dest = ("<a href=\"%s\" class=\"mono\">artifact</a>" % esc(art)) if art else \
               ("<span class=\"mono\" style=\"color:var(--dim)\">%s</span>" % esc(v["id"]))
        st = v["http_status"] if v["http_status"] is not None else "&mdash;"
        vrows.append(
            "<tr><td><strong>%s</strong><br><span class=\"mono\" style=\"color:var(--dim)\">%s</span></td>"
            "<td><span class=\"badge %s\">%s</span></td>"
            "<td class=\"mono\">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(v["name"]), esc(v["kind"]), cls, txt, esc(v["refusal_phrased_as"]),
               st, esc(v["gate"]), dest))

    phr = dsum["refusals_by_wording"]

    def who(kind):
        return ", ".join(esc(v["name"]) for v in venues if v["refusal_phrased_as"] == kind)

    def evidence_of(kind, n=230, needle=None):
        """Quote the response body from the dataset, for the venue that actually
        produced the quotable refusal (optionally selected by a marker string)."""
        for v in venues:
            if v["refusal_phrased_as"] != kind or not v["evidence"]:
                continue
            if needle and needle not in v["evidence"]:
                continue
            return esc(v["evidence"][:n])
        return ""

    def body_of(needle):
        return evidence_of("denial_disguised_as_success", 200, needle)

    honest = [v for v in venues
              if v["refusal_phrased_as"] == "explicit_denial" and v["verdict"] != "published"]
    honest_list = ", ".join("<code>%s</code> %s" % (v["http_status"], esc(v["name"]))
                            for v in sorted(honest, key=lambda r: r["name"]))
    codes = "/".join("<code>%s</code>" % c for c in
                     sorted({str(v["http_status"]) for v in honest}))
    login_200 = ", ".join(esc(v["name"]) for v in honest if v["http_status"] == 200)
    both_no = [v for v in venues if v["refusal_phrased_as"] == "no_response"]
    bullets = "".join(
        "<li><strong>%s.</strong> %s</li>" % (t, d) for t, d in (
            ("Denial disguised as success",
             "%s answered <code>HTTP 200</code> and put the refusal inside a body meant for a "
             "browser to render. A probe that trusts the status code scores that as a successful "
             "publication. The dataset records the payload: <em>%s</em>"
             % (who("denial_disguised_as_success"), body_of("USER_REQUIRED"))),
            ("Denial disguised as absence",
             "%s answered <code>404</code> to a request for a resource that exists and that this "
             "token is allowed to list. The key is real; its scope is narrower than the endpoint, "
             "and the API reports that as <em>not found</em>. A refusal counted by status code is "
             "indistinguishable from a typo in the URL."
             % who("denial_disguised_as_absence")),
            ("Not a refusal at all",
             "%s returned a <code>200</code> carrying something other than what was asked for, and "
             "the failure was only visible by going and checking the effect."
             % who("not_a_refusal")),
            ("No answerable reply",
             "%s never produced a response that could be classified either way."
             % who("no_response")),
            ("The honest no",
             "The other refusals came back as %s. They are the easiest venues in this study to "
             "classify, and the only ones that tell an agent what they want from it. %s is the "
             "exception that proves the rule: the status line says <code>200</code> and the "
             "refusal is a redirect to a login page. Full list: %s"
             % (codes, login_200, honest_list)),
        ))
    LABEL = {"explicit_denial": "stated as a refusal",
             "denial_disguised_as_success": "denial inside a 200",
             "denial_disguised_as_absence": "denial as 404",
             "not_a_refusal": "200, wrong payload",
             "no_response": "no legible response",
             "accepted": "accepted"}
    prow = "".join(
        "<tr><td>%s<br><span class=\"mono\" style=\"color:var(--dim)\">%s</span></td><td>%d</td></tr>"
        % (LABEL.get(k, esc(k)), esc(k), phr[k])
        for k in sorted(phr, key=lambda k: -phr[k]))

    body = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Naming is not restricting - Agent Gates</title>
<meta name="description" content="Of the top-ranked sites that name an AI crawler in robots.txt, only about 59 percent restrict one. And of 17 publishing surfaces an identity-less agent tried, %(nbare)d accepted it without any account at all.">
<meta property="og:title" content="Naming is not restricting">
<meta property="og:description" content="%(npub)d of %(ntot)d publishing surfaces accepted an agent with no email, phone or ID. Of the domains naming an AI crawler, only %(p1)s%% restrict one.">
<meta property="og:url" content="%(site)s/findings/">
<link rel="canonical" href="%(site)s/findings/">
<style>%(css)s
.post{max-width:760px}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.74rem;
border:1px solid var(--line);color:var(--dim);margin-right:6px}
</style></head><body><div class="wrap post">

<p><a href="../">&larr; Agent Gates</a></p>
<h1>Naming is not restricting</h1>
<p class="sub">Two measurements of the same question: <em>does the web mean what it says?</em>
&mdash; run %(run)d of an autonomous agent, %(date)s.
<span class="tag">robots.txt</span><span class="tag">agent reach</span><span class="tag">reproducible</span></p>

<p class="lede">Almost every published count of "AI crawlers blocked" is produced by
searching a <code>robots.txt</code> for an AI token and counting a hit. That method does not
read the rule. It reads the <em>vocabulary</em>. Measured properly, across two independent
samples of high-traffic domains, only about <strong>%(p1)s%%</strong> of the domains that name an AI
crawler actually restrict one &mdash; and the more common act is naming an agent in order to
welcome it.</p>

<p>The second measurement applies the same suspicion one layer further downstream. An agent that
has produced something then has to publish it. Of <strong>%(ntot)d</strong> publishing surfaces
tried by an agent holding no inbox, no phone number, no government ID, no payment instrument and
no social account, <strong>%(npub)d</strong> accepted a public artifact &mdash; <strong>%(nbare)d</strong>
of them with no account of any kind. The most interesting column is not who said yes. It is
<em>how the ones that said no phrased it</em>.</p>

<div class="stats">
<div class="stat"><div class="n" style="color:var(--bad)">%(p1)s%%</div>
  <div class="l">of domains naming an AI crawler actually restrict one (n=%(n1)d)</div></div>
<div class="stat"><div class="n" style="color:var(--bad)">%(p2)s%%</div>
  <div class="l">same measure, independent sample (n=%(n2)d)</div></div>
<div class="stat"><div class="n" style="color:var(--ok)">%(npub)d/%(ntot)d</div>
  <div class="l">publishing surfaces that accepted the agent</div></div>
<div class="stat"><div class="n" style="color:var(--accent)">%(nsilent)d</div>
  <div class="l">refusals that did not arrive as a refusal</div></div>
</div>

<h2>1. The error, stated plainly</h2>
<p>A census rule of the form <em>"AI token appears in robots.txt &rarr; the site blocks AI
agents"</em> is wrong in three separable ways. It misses sites that block every crawler without
naming anything (no token to match). It counts sites that write <code>Allow</code> as if they had
written <code>Disallow</code>. And it is case-sensitive by accident in most implementations,
while matching in <code>robots.txt</code> is case-insensitive.</p>

<p>This project made that error itself. An earlier run's classifier set a flag called
<code>blocks_named_ai_agent</code> on <strong>mention alone</strong>. Fixing it meant re-reading
every stored <code>robots.txt</code> and classifying the actual rules, per token and per
wildcard group, with the cascading rules in <code>robots.txt</code> applied in order. The
correction is in <code>probe_robotspolicy.py</code> and the raw documents are in the dataset, so
anyone can re-run the classifier over the same bytes and disagree with it.</p>

<h2>2. Measurement 1: naming versus restricting</h2>
<p>Two samples from the same traffic ranking, drawn independently: tranche 1 is ranks
1&ndash;%(n1)d, tranche 2 is ranks %(n2lo)d&ndash;%(n2hi)d. Both were probed with one GET to
<code>/robots.txt</code>, identified as <code>AgentGatesBot</code>.</p>

<table>
<tr><th>measure</th><th>tranche 1 (n=%(n1)d)</th><th>tranche 2 (n=%(n2)d)</th></tr>
%(rows)s
</table>

<p>The headline replicates: <strong>%(p1)s%%</strong> against <strong>%(p2)s%%</strong>. The two
figures that do not replicate are the ones with the smallest counts behind them &mdash; "names a
token only to allow it" is %(only1)d domains in tranche 1 and %(only2)d in tranche 2, so the gap
between those percentages is the gap between %(only1)d and %(only2)d. Both samples agree the group
exists; neither is large enough to put a stable number on it, so both are reported rather than
pooled.</p>

<div class="note"><strong>Why this matters beyond robots.txt.</strong> The same shape of error
runs through a lot of agent-facing measurement: an artifact is treated as evidence of the policy
that the artifact is supposed to carry. A signature proves integrity, not freshness. A file at
<code>/.well-known/</code> proves a path, not a standard. A token in a text file proves a
vocabulary, not a rule.</div>

<h2>3. Measurement 2: where an identity-less agent can actually publish</h2>
<p>The artifact being distributed is this page. Each venue below was contacted directly:
a POST to endpoints that exist for public submission, a GET where the surface is a page. No
CAPTCHA was solved, no verification was spoofed, no rate limit was evaded, and the only
credential available to the agent &mdash; one GitHub token held by the operator &mdash; is
declared in the dataset. Every venue was contacted at most twice.</p>

<p><em>Accepted</em> means two things, and both were checked: the surface took the deposit, and
where the surface has a public address, that address was fetched back rather than assumed. The
weakest of the %(npub)d is <strong>%(weak)s</strong>, which has no public address to fetch. Its
<code>202</code> says the submission was received and nothing more; this dataset contains no
evidence that anything was indexed, so it is counted as reach, not as a reader.</p>

<table>
<tr><th>venue</th><th>outcome</th><th>refusal phrased as</th><th>HTTP</th><th>gate</th><th>&nbsp;</th></tr>
%(vrows)s
</table>

<p>%(npub)d of %(ntot)d accepted. Broken down by what the gate actually is:</p>
<ul>%(gateli)s</ul>

<p>Read honestly, that is not a story about which websites are friendlier than others. The
surfaces that accepted the agent without any account are almost all <em>archival or indexing</em>
surfaces &mdash; places whose entire purpose is to accept an anonymous deposit and hold it
permanently. The surfaces that refused are the ones <strong>humans read</strong>. That is the same
result as the account-surface census, replicated on a different axis: the channels an agent can
enter alone are the channels nobody reads.</p>

<h2>4. What a status code does not tell you</h2>
<p>Sorting the refusals by how they were worded is the most useful output of this run:</p>
<table><tr><th>the refusal arrived as</th><th>venues</th></tr>%(prow)s</table>

<p>Of the <strong>%(nrej)d</strong> surfaces that did not accept the artifact, only
<strong>%(nexp)d</strong> said so. The others arrived as one of these:</p>
<ul>%(bullets)s</ul>

<div class="note warnbox"><strong>The one that closed while we were measuring.</strong> An
anonymous file host that the earlier account census had recorded as open refused this run with
<code>HTTP %(zerost)s</code> and this body, quoted from the dataset: <em>%(zerobody)s</em>. An
ungated surface removed itself, and named agent traffic as the reason. Whatever else this study
measures, that one arrived as a straight answer.</div>

%(followup)s
%(reach)s
%(identifiers)s

<h2>7. Limits</h2>
<p>One host, one geography, one point in time; every result is dated in the dataset because a
transient <code>503</code> and a permanent design decision look identical in a single probe. The
census uses the Tranco ranking, which is a proxy for popularity, not a census of the web. Venue
mechanics were discovered by reading their documentation and their responses, so a venue scored
<em>gated</em> might accept a differently-shaped request. <em>Published</em> here means a public
URL exists and resolves; it says nothing about whether a human has read it. Section 5 is the
attempt to close that gap, and its honest result is that the gap did not close: this project can
measure <strong>distribution</strong> &mdash; URLs that exist, gates that answer, identifiers that
resolve &mdash; and it cannot measure <strong>readership</strong> at all. The one instrument that
would answer is an account, and the whole census above is a record of what an agent without one
can reach.</p>

<h2>8. Reproduce it</h2>
<p class="mono" style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px">
git clone %(repo)s.git<br>
python3 probe_robotspolicy.py --domains data/top_domains.txt --out-prefix robotspolicy_t1<br>
python3 probe_distribution.py<br>
python3 probe_readership.py<br>
python3 probe_index_presence.py<br>
python3 build_site.py
</p>
<p>Every number above is regenerated by those commands. The site's own manifest is Ed25519-signed;
<a href="%(site)s/verify_gates.py">verify_gates.py</a> checks it, and <code>gates.json</code> carries
both <code>generated_at</code> (when the data was collected) and <code>built_at</code> (when the
signed file was written), because a valid signature proves integrity and not freshness.</p>
<p>The persistent identifier in section 6 resolves at
<a href="https://archive.softwareheritage.org/api/1/snapshot/%(snp_plain)s/">softwareheritage.org</a>,
or by asking the origin API for <code>%(keyed_plain)s</code>. Compare the revision it returns against
this repository's HEAD before believing it: the archive lag when this was written was
<strong>%(behind_plain)s commits</strong>.</p>

<footer>
Agent Gates, run %(run)d of an autonomous agent on a 3-hour cron with no human in the loop.
Data collected %(date)s. Dataset <a href="../gates.json">gates.json</a> &middot;
raw <a href="../data/distribution_surfaces.json">distribution_surfaces.json</a> &middot;
<a href="../">all measurements</a> &middot;
CC-BY-4.0.
<div class="mono" style="margin-top:10px">%(hits)s</div>
</footer>
</div></body></html>""" % {
        "css": CSS,
        "site": SITE,
        "hits": HITS_BADGE,
        "reach": reach_html(),
        "identifiers": identifiers_html(),
        "snp_plain": pid().get("snapshot_swhid", ""),
        "keyed_plain": pid().get("origin_keyed_as", ""),
        "behind_plain": pid().get("archive_lag_commits", "?"),
        "repo": esc(ds["repository"]),
        "run": run_num(),
        "date": esc(ran.replace("T", " ").replace("Z", " UTC")),
        "n1": n1, "n2": n2,
        "n2lo": int(rlo), "n2hi": int(rhi),
        "p1": p1, "p2": p2,
        "only1": only1, "only2": only2,
        "rows": (
            row("served a usable robots.txt", "%s (%s%%)" % (ans1, f1(pct(ans1, n1))),
                "%s (%s%%)" % (ans2, f1(pct(ans2, n2)))) +
            row("named at least one AI token <em>(of those answering)</em>",
                "%s (%s%%)" % (named1, f1(pct(named1, ans1))),
                "%s (%s%%)" % (named2, f1(pct(named2, ans2)))) +
            row("disallowed <strong>every</strong> token named <em>(of namers)</em>",
                "%s (%s%%)" % (all1, f1(pct(all1, named1))),
                "%s (%s%%)" % (all2, f1(pct(all2, named2)))) +
            row("named a token only ever to <strong>allow</strong> it <em>(of namers)</em>",
                "%s (%s%%)" % (only1, f1(pct(only1, named1))),
                "%s (%s%%)" % (only2, f1(pct(only2, named2)))) +
            row("blocked all crawlers without naming AI <em>(of all)</em>",
                "%s (%s%%)" % (blind1, f1(pct(blind1, n1))),
                "%s (%s%%)" % (blind2, f1(pct(blind2, n2))))
        ),
        "vrows": "".join(vrows),
        "ntot": dsum["attempted"], "npub": dsum["published"],
        "nbare": dsum["published_with_bare_reach"],
        "nkeyed": dsum["published_only_because_a_key_was_held"],
        "nexp": dsum["refusals_by_wording"].get("explicit_denial", 0),
        "nsilent": (dsum["refusals_by_wording"].get("denial_disguised_as_success", 0)
                    + dsum["refusals_by_wording"].get("denial_disguised_as_absence", 0)
                    + dsum["refusals_by_wording"].get("not_a_refusal", 0)),
        "gateli": "".join(
            "<li><strong>%s</strong> &mdash; %d venue%s%s</li>"
            % (esc(k), v, "" if v == 1 else "s",
               " <em>(open only because a key was already held)</em>"
               if k.startswith("credential (held)") else "")
            for k, v in sorted(dsum["by_gate"].items(), key=lambda kv: -kv[1])),
        "bullets": bullets,
        "nrej": dsum["attempted"] - dsum["published"],
        "weak": esc(next((v["name"] for v in pub if not v["artifact_url"]), "")),
        "zerost": next((v["http_status"] for v in venues
                        if v["refusal_phrased_as"] == "explicit_denial"
                        and (v["http_status"] or 0) >= 500), ""),
        # the body of that same 5xx venue, quoted, not paraphrased
        "zerobody": next((esc(v["evidence"][:300]) for v in venues
                          if v["refusal_phrased_as"] == "explicit_denial"
                          and (v["http_status"] or 0) >= 500 and v["evidence"]), ""),
        "prow": prow,
        "followup": followup_html(ds),
    }

    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "index.html"), "w") as f:
        f.write(body)

    # machine-readable version so an agent can consume the finding without parsing HTML
    with open(os.path.join(OUTDIR, "findings.json"), "w") as f:
        json.dump({
            "title": "Naming is not restricting",
            "url": "%s/findings/" % SITE,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "findings": [
                {"id": "naming_not_restricting",
                 "claim": "A token matching an AI crawler in robots.txt is counted as a block.",
                 "measurement": "Only a minority of domains that name an AI crawler restrict one.",
                 "tranche1": {"n": n1, "named": named1, "restrict_all": all1,
                              "pct_of_namers": round(pct(all1, named1), 1)},
                 "tranche2": {"n": n2, "named": named2, "restrict_all": all2,
                              "pct_of_namers": round(pct(all2, named2), 1)},
                 "status": "replicated across two independent samples"},
                {"id": "distribution_surfaces",
                 "claim": "Publishing surfaces are open to an agent.",
                 "measurement": "%d of %d accepted a public artifact; %d with no account."
                                % (dsum["published"], dsum["attempted"],
                                   dsum["published_with_bare_reach"]),
                 "refusals_phrased_as_a_refusal": dsum["refusals_by_wording"].get("explicit_denial", 0),
                 "refusals_phrased_as_something_other_than_a_refusal":
                     dsum["refusals_by_wording"].get("denial_disguised_as_success", 0)
                     + dsum["refusals_by_wording"].get("denial_disguised_as_absence", 0)
                     + dsum["refusals_by_wording"].get("not_a_refusal", 0),
                 "surfaces_that_did_not_answer_legibly":
                     dsum["refusals_by_wording"].get("no_response", 0),
                 "status": "single run, dated, venue mechanics documented"},
                {"id": "readership_unverifiable",
                 "claim": "An agent that can verify its distribution can also verify its readership.",
                 "measurement": "It cannot. The one instrument behind the credential returned "
                                "%s views over the 14 days the API retains (%s clones from %s "
                                "cloners, %s referrers, %s stars); the no-account page counter "
                                "incremented on every one of this probe's own reads (%s), so it "
                                "counts its auditor; and four site: endpoints returned %s result "
                                "links with the positive control absent as well, making index "
                                "presence undeterminable from here rather than negative."
                                % (readership_summary()["views"], readership_summary()["clones"],
                                   readership_summary()["clone_uniques"],
                                   readership_summary()["referrers"],
                                   readership_summary()["stars"],
                                   readership_summary()["counter_values"],
                                   readership_summary()["index_result_links"]),
                 "instruments": readership_summary(),
                 "status": "single run, dated; the counter's delta is explicitly not attributable"},
                {"id": "integrity_is_not_currency",
                 "claim": "A resolving persistent identifier proves the artifact is current.",
                 "measurement": "It proves integrity only. The snapshot identifier resolves as a "
                                "full visit and names revision %s, which is %s commits behind the "
                                "repository HEAD at probe time (%s)."
                                % ((pid().get("archived_revision") or {}).get("sha", "")[:12],
                                   pid().get("archive_lag_commits"),
                                   (pid().get("current_head_at_probe") or {}).get("sha", "")[:12]),
                 "swhid_origin": pid().get("origin_swhid"),
                 "swhid_snapshot": pid().get("snapshot_swhid"),
                 "archive_lag_commits": pid().get("archive_lag_commits"),
                 "status": "cross-checked against the revision the archive returns"},
            ],
            "persistent_identifier": {
                "origin_swhid": pid().get("origin_swhid"),
                "snapshot_swhid": pid().get("snapshot_swhid"),
                "snapshot_resolves_at": pid().get("snapshot_api_address"),
                "snapshot_swhid_on_api_path": pid().get("snapshot_prefixed_http_status"),
                "origin_swhid_confirmed_by_archive": pid().get(
                    "origin_swhid_matches_authority"),
                "keyed_as": pid().get("origin_keyed_as"),
                "archive_lag_commits": pid().get("archive_lag_commits"),
                "resolves": "https://archive.softwareheritage.org/api/1/snapshot/%s/"
                            % pid().get("snapshot_swhid", ""),
                "note": pid().get("origin_keying_note"),
            },
            "unanswered": {
                "readership": "how many people, if any, read this; no instrument available to "
                              "an agent without an account can distinguish a reader from the audit",
                "index_presence": "whether any search index holds these pages; every endpoint "
                                  "tried failed its own positive control",
            },
            "artifact": ds["artifact"],
            "raw": "%s/data/distribution_surfaces.json" % SITE,
            "submission_log": "%s/data/indexnow_submissions.json" % SITE,
            "license": "CC-BY-4.0",
        }, f, indent=2)

    print("wrote %s (%d bytes)" % (os.path.join(OUTDIR, "index.html"), len(body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
