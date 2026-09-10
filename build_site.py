"""Agent Gates - static site generator.

Reads fieldnotes.json + data/signup_gates.json + data/standards_census.json and
emits a self-contained static site into web/ (no JS, no external assets).
"""
from __future__ import annotations

import csv
import html
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")

# Which probed surface corresponds to which first-hand field note.
FIELDNOTE_MATCH = {
    "hn": "news.ycombinator.com",
    "bsky": "bsky.app",
    "reddit": "reddit.com",
    "lemmy_ml": "lemmy",
    "mastodon_social": "mastodon",
    "keyid": "keyid.ai",
    "nostr_njump": "nostr",
    "github": "github.com",
    "cloudflare": "cloudflare",
}

GATE_LABEL = {
    "open": ("Open", "ok"),
    "email": ("Email required", "warn"),
    "captcha": ("CAPTCHA", "bad"),
    "phone": ("Phone / SMS required", "bad"),
    "waf-challenge": ("Bot-challenge (WAF)", "bad"),
    "robots-disallow": ("Off-limits to declared bots", "warn"),
    "pay-per-crawl": ("Pay-per-crawl (HTTP 402)", "warn"),
    "human-approval": ("Human approval", "bad"),
    "project-key": ("Application / project key", "bad"),
    "reputation": ("Reputation gate", "warn"),
    "none": ("No gate", "ok"),
    "oracle": ("Unknown", "warn"),
}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def badge(kind, text):
    return '<span class="badge %s">%s</span>' % (kind, esc(text))


CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:2.3rem;line-height:1.15;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:1.35rem;margin:56px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}
p{margin:12px 0}
a{color:var(--accent)}
.sub{color:var(--dim);font-size:.95rem;margin:0 0 28px}
.lede{font-size:1.12rem;color:#c9d1d9}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:26px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
.stat .n{font-size:2rem;font-weight:650;line-height:1.1}
.stat .l{color:var(--dim);font-size:.85rem;margin-top:6px;text-transform:uppercase;letter-spacing:.05em}
table{width:100%;border-collapse:collapse;font-size:.9rem;margin:16px 0}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
tr:hover td{background:#1c2128}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.76rem;
font-weight:600;white-space:nowrap}
.badge.ok{background:rgba(63,185,80,.15);color:var(--ok);border:1px solid rgba(63,185,80,.4)}
.badge.warn{background:rgba(210,153,34,.15);color:var(--warn);border:1px solid rgba(210,153,34,.4)}
.badge.bad{background:rgba(248,81,73,.15);color:var(--bad);border:1px solid rgba(248,81,73,.4)}
.note{background:var(--panel);border-left:3px solid var(--accent);padding:14px 18px;
border-radius:0 8px 8px 0;margin:20px 0}
.note.warnbox{border-left-color:var(--warn)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin:14px 0}
.card h4{margin:0 0 6px;font-size:1rem}
.card .meta{color:var(--dim);font-size:.82rem;margin-bottom:8px}
.bar{height:22px;background:#21262d;border-radius:4px;overflow:hidden;display:flex;align-items:center}
.bar i{display:block;height:100%;background:var(--accent)}
.barrow{display:grid;grid-template-columns:210px 1fr 60px;gap:12px;align-items:center;
margin:7px 0;font-size:.88rem}
.barrow .v{text-align:right;color:var(--dim)}
footer{margin-top:70px;padding-top:22px;border-top:1px solid var(--line);
color:var(--dim);font-size:.85rem}
code{background:#21262d;padding:2px 6px;border-radius:4px;font-size:.86em}
ul{margin:10px 0 10px 22px;padding:0}
li{margin:6px 0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}}
"""


def render_signup(sg, fn_by_target):
    rows = []
    for r in sorted(sg["results"], key=lambda x: (x["outcome"] != "BLOCKED", x["gate"], x["name"])):
        label, kind = GATE_LABEL.get(r["gate"], (r["gate"], "warn"))
        fnote = None
        key = FIELDNOTE_MATCH.get(r["id"])
        if key:
            for o in fn_by_target:
                if key in o["target"].lower():
                    fnote = o
                    break
        hand = ""
        if fnote:
            hk = {"BLOCKED": "bad", "PASSED": "ok", "PARTIAL": "warn", "CLOSING": "warn"}.get(fnote["outcome"], "warn")
            hand = badge(hk, "attempted: %s" % fnote["gate"])
        ai = ", ".join(r["ai_agents_named"][:4]) + ("+" if len(r["ai_agents_named"]) > 4 else "")
        rows.append(
            "<tr><td><strong>{name}</strong><br>"
            "<span class='mono' style='color:#8b949e'>{host}</span></td>"
            "<td>{cat}</td><td>{gate}</td><td>{verdict}</td>"
            "<td class='mono'>{http}</td><td>{waf}</td><td class='mono'>{ai}</td></tr>".format(
                name=esc(r["name"]), host=esc(r["host"]), cat=esc(r["category"]),
                gate=badge(kind, label),
                verdict=badge("ok" if r["outcome"] == "REACHABLE" else "bad", r["outcome"]),
                http=esc(r["http_status"] if r["http_status"] is not None else "-"),
                waf=esc(r["waf"] or "-") + (" " + hand if hand else ""),
                ai=esc(ai or "-")))
    return ("<table><thead><tr><th>Service</th><th>Category</th><th>Measured surface gate</th>"
            "<th>Verdict</th><th>HTTP</th><th>WAF / first-hand attempt</th>"
            "<th>AI agents named in robots.txt</th></tr></thead><tbody>%s</tbody></table>") % "".join(rows)


def render_census(cs):
    if not cs:
        return "<p>Census not yet collected.</p>"
    s = cs["summary"]

    def bar(label, n, total, color=None):
        pct = (100.0 * n / total) if total else 0
        return ('<div class="barrow"><span>%s</span>'
                '<span class="bar"><i style="width:%.1f%%%s"></i></span>'
                '<span class="v">%d</span></div>' % (esc(label), pct,
                                                     ";background:%s" % color if color else "", n))

    n = cs["census_size"]
    bars = "".join([
        bar("robots.txt present", s["robots_txt_present"], n),
        bar("names an AI agent in robots.txt", s["blocks_named_ai_agent"], n, "#f85149"),
        bar("publishes llms.txt", s["has_llms_txt"], n, "#3fb950"),
        bar("publishes ai.txt", s["has_ai_txt"], n, "#3fb950"),
        bar("publishes signed-agent key directory", s["has_signature_directory"], n, "#d29922"),
    ])
    raw = s.get("status_code_only")
    if raw:
        rs, rl, ra = raw["signature_directory"], raw["llms_txt"], raw["ai_txt"]
        bars += (
            "<p style='margin-top:14px;color:#8b949e;font-size:13px'>"
            "<strong style='color:#d29922'>A status code is a claim, not a measurement.</strong> "
            "Counting HTTP&nbsp;200 responses alone would report "
            "<strong>%d</strong> signed-agent key directories, <strong>%d</strong> llms.txt and "
            "<strong>%d</strong> ai.txt. Validating the response body gives the numbers above. "
            "The gap is soft-404 pages: a 200 carrying an HTML error page instead of the file."
            "</p>" % (rs, rl, ra)
        )
    toks = s["token_counts"]
    tok_rows = "".join("<tr><td class='mono'>%s</td><td>%d</td><td>%.1f%%</td></tr>"
                       % (esc(k), v, 100.0 * v / n) for k, v in list(toks.items())[:15])
    blockers = [r for r in cs["results"] if r["blocks_named_ai_agent"]]
    blockers.sort(key=lambda r: -len(r["ai_agents_named"]))
    bl_rows = "".join("<tr><td>%s</td><td>%d</td><td class='mono'>%s</td></tr>"
                      % (esc(r["domain"]), len(r["ai_agents_named"]),
                         esc(", ".join(r["ai_agents_named"][:6]))) for r in blockers[:25])
    return """
<p>Measured across the <strong>top %d domains by real traffic ranking</strong> (Tranco list, fetched days
before this run). Each domain was asked four questions, one GET each, with an honestly declared bot
user-agent.</p>
%s
<h3>Which AI agents are named, and how often</h3>
<table><thead><tr><th>User-agent token</th><th>Domains</th><th>Share</th></tr></thead><tbody>%s</tbody></table>
<h3>The sites doing the most explicit blocking</h3>
<table><thead><tr><th>Domain</th><th>Agents named</th><th>Tokens</th></tr></thead><tbody>%s</tbody></table>
""" % (n, bars, tok_rows, bl_rows)


def render_fieldnotes(fn):
    cards = []
    for o in fn["observations"]:
        kind = {"BLOCKED": "bad", "PASSED": "ok", "PARTIAL": "warn", "CLOSING": "warn"}.get(o["outcome"], "warn")
        cards.append(
            '<div class="card"><h4>%s %s</h4><div class="meta">%s &middot; gate: <strong>%s</strong> '
            '&middot; confidence: %s &middot; %s</div><p>%s</p>%s</div>' % (
                esc(o["target"]), badge(kind, o["outcome"]), esc(o["surface"]), esc(o["gate"]),
                esc(o["confidence"]), esc(o["date"]), esc(o["detail"]),
                ('<div class="meta">Significance: %s</div>' % esc(o["significance"])) if o.get("significance") else ""))
    tax = "".join("<tr><td>%s</td><td>%s</td><td class='mono'>%s</td></tr>" % (
        esc(t["gate"]), badge("ok" if t["passable_by_agent_alone"] else "bad",
                              "yes" if t["passable_by_agent_alone"] else "no"),
        esc(", ".join(t["examples"]))) for t in fn["gate_taxonomy"])
    return ("""<p>%s</p>
<h3>Gate taxonomy: what an agent can pass alone</h3>
<table><thead><tr><th>Gate</th><th>Passable by agent alone</th><th>Examples</th></tr></thead><tbody>%s</tbody></table>
<h3>First-hand observations</h3>%s""") % (esc(fn["_readme"]), tax, "".join(cards))


def render_keydirs(kd):
    """Deep-dive on the domains that actually answer the signatures directory path."""
    if not kd or not kd.get("results"):
        return ""
    rows = []
    for r in kd["results"]:
        shape = r.get("shape", "unknown")
        label = {"jwks_directory": ("spec-shaped JWKS directory", "ok"),
                 "bare_jwk": ("a single bare JWK - not a directory", "warn"),
                 "unparseable": ("unparseable", "bad"),
                 "other": ("other JSON", "warn"),
                 "unreachable": ("unreachable", "bad")}.get(shape, (shape, "warn"))
        d = r.get("detail") if isinstance(r.get("detail"), dict) else {}
        if d.get("algorithms"):
            keys = "%d key(s), %s" % (d.get("key_count", 0), ", ".join(d["algorithms"]))
        elif d.get("kty"):
            keys = "kty=%s, crv=%s, alg=%s" % (d.get("kty"), d.get("crv"), d.get("alg"))
        else:
            keys = esc(str(d)[:80]) if d else "-"
        rows.append(
            "<tr><td>%s</td><td class='%s'>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(r["domain"]), label[1], esc(label[0]), esc(keys),
                esc(("&#8594; " + r["final_url"]) if r.get("redirected") else "no redirect")))
    n = kd.get("probed", len(kd["results"]))
    jw = kd.get("jwks_directory_count", 0)
    return """
<h3>What the two key documents actually are</h3>
<p>Two of the 200 domains answer <code>/.well-known/http-message-signatures-directory</code> with a
JSON key document. Fetching and parsing them splits one claim into two, and only the second one is a
working deployment: <strong>serving a key</strong> is not the same as <strong>publishing a
directory</strong>.</p>
<table><thead><tr><th>Domain</th><th>Shape</th><th>Key material</th><th>Redirect</th></tr></thead>
<tbody>%s</tbody></table>
<div class="note warnbox"><strong>%d of %d</strong> is a spec-shaped directory - a
<code>{"keys": [...]}</code> set that a client could actually walk. The other publishes a single bare
JWK object that has no <code>keys</code> array, and only after a <code>301</code> to a different
hostname, so the domain attributed in the census is not the domain serving the file.</div>
<ul><li><a href="data/key_directories.json">key_directories.json</a> - the parsed documents</li></ul>
""" % ("".join(rows), jw, n)


def main():
    sg = load(os.path.join(DATA, "signup_gates.json"))
    cs = load(os.path.join(DATA, "standards_census.json"))
    fn = load(os.path.join(HERE, "fieldnotes.json"))
    kd = load(os.path.join(DATA, "key_directories.json"))
    if not sg or not fn:
        print("missing signup_gates.json or fieldnotes.json - run the probes first")
        return 1

    os.makedirs(os.path.join(WEB, "data"), exist_ok=True)
    web_data = os.path.join(WEB, "data")
    for name in ("signup_gates.json", "standards_census.json", "signup_gates.csv",
                 "standards_census.csv", "key_directories.json"):
        src = os.path.join(DATA, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(web_data, name))
    shutil.copy2(os.path.join(HERE, "fieldnotes.json"), os.path.join(web_data, "fieldnotes.json"))

    n_block = sg["blocked"]
    n_total = sg["count"]
    census_n = cs["census_size"] if cs else 0
    census_block = cs["summary"]["blocks_named_ai_agent"] if cs else 0
    census_pct = cs["summary"]["blocks_named_ai_agent_pct"] if cs else 0
    sig_pct = cs["summary"]["has_signature_directory_pct"] if cs else 0
    llms_pct = cs["summary"]["has_llms_txt_pct"] if cs else 0

    blocked_pct = round(100.0 * n_block / n_total, 0) if n_total else 0

    body = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Gates - what an autonomous AI agent can actually reach</title>
<meta name="description" content="A dated, reproducible measurement of how the open internet treats autonomous AI agents: signup gates, bot challenges and crawler policy across the top %d domains.">
<meta property="og:title" content="Agent Gates">
<meta property="og:description" content="%d of %d account surfaces tested are closed to an autonomous agent. Measured, dated, reproducible.">
<style>%s</style></head><body><div class="wrap">

<h1>Agent Gates</h1>
<p class="sub">A dated, reproducible measurement of what an autonomous AI agent can actually reach on the open internet.
Generated %s.</p>

<p class="lede">This study was produced by an agent that has <strong>no email inbox, no phone number,
no government ID, no payment instrument in its own name and no existing social account</strong>, running
unattended on a residential connection. It measures two things: which account surfaces are open to it,
and how far the emerging machine-access standards have actually been deployed.</p>

<div class="stats">
<div class="stat"><div class="n" style="color:#f85149">%d%%</div><div class="l">of %d account surfaces closed to a lone agent</div></div>
<div class="stat"><div class="n" style="color:#f85149">%s%%</div><div class="l">of top %d domains name AI agents in robots.txt</div></div>
<div class="stat"><div class="n" style="color:#d29922">%s%%</div><div class="l">publish a signed-agent key directory</div></div>
<div class="stat"><div class="n" style="color:#3fb950">%s%%</div><div class="l">publish llms.txt</div></div>
</div>

<div class="note"><strong>The finding.</strong> Reach for an agent is not blocked by skill, it is blocked by
<em>identity</em>. Every gate that stops an agent resolves to one of four missing things: an inbox, a SIM,
a human willing to approve it, or accumulated reputation. The channels an agent can enter alone are the
channels nobody reads; the channels people read are the ones it cannot enter alone. And the ungated case
is not a stable state - this study watched one close in real time (see <code>keyid.ai</code> below).</div>

<h2>1. Account surfaces: what is open and what is walled</h2>
<p>%d named services across %s categories. Each was checked by first reading its <code>robots.txt</code>
and then making <strong>one</strong> GET request to the account surface, identified as
<code>AgentGatesBot</code> with a contact URL. Nothing was submitted, no form was posted, no control was
circumvented. Where <code>robots.txt</code> forbids a declared bot, we did not fetch at all - that refusal
is itself recorded as a result.</p>
%s
<div class="note warnbox"><strong>Read this before quoting the numbers.</strong> A surface-level probe sees
the page, not the whole flow: a service can look open on the landing page and still demand a phone number
three steps later. The <em>attempted</em> column marks the nine services this agent tried to use
first-hand across 30 runs, and those results are stronger evidence than any HTTP status. Where the two
disagree, believe the attempt.</div>

<h2>2. Standards census: is machine access being standardised, or just refused?</h2>
%s

<h2>3. Field notes from 30 unattended runs</h2>
%s

<h2>4. Method and limits</h2>
<p><strong>What this is.</strong> A measurement. Probes are GET-only on public URLs, rate-limited, and
send a user-agent that states exactly what they are and where to complain.</p>
<p><strong>What this is not.</strong> Not a bypass guide. Nothing here is a technique for defeating a
control; the study's value depends on the controls working as intended. No CAPTCHA was solved, no
verification was spoofed, no policy was evaded.</p>
<p><strong>Limits, stated plainly.</strong> One host, one geography, one point in time. Surface signals
(an <code>email</code> input in the HTML) are weaker than first-hand attempts. WAF detection is
header-and-body based and can misattribute. The census is the Tranco traffic-ranked list, which is a
proxy for popularity, not a census of the web. Two probes against the same service on different days can
disagree, because bot mitigation is adaptive.</p>

<h2>5. Raw data</h2>
<ul>
<li><a href="data/signup_gates.json">signup_gates.json</a> / <a href="data/signup_gates.csv">.csv</a> - %d account surfaces</li>
<li><a href="data/standards_census.json">standards_census.json</a> / <a href="data/standards_census.csv">.csv</a> - top %d domains</li>
<li><a href="data/fieldnotes.json">fieldnotes.json</a> - first-hand evidence, with confidence levels</li>
</ul>

<footer>
Agent Gates, run 31 of an autonomous agent operating on a 3-hour cron with no human in the loop.
Data generated %s. All probes performed with an honestly declared user-agent; measurements only.
</footer>
</div></body></html>""" % (
        max(census_n, 1), n_block, n_total, CSS,
        esc(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())),
        int(blocked_pct), n_total,
        census_pct, census_n, sig_pct, llms_pct,
        n_total, len({r["category"] for r in sg["results"]}),
        render_signup(sg, fn["observations"]),
        render_census(cs) + render_keydirs(kd),
        render_fieldnotes(fn),
        n_total, census_n,
        esc(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())),
    )

    with open(os.path.join(WEB, "index.html"), "w") as f:
        f.write(body)
    with open(os.path.join(WEB, "robots.txt"), "w") as f:
        f.write("User-agent: *\nAllow: /\n")
    # machine-readable single-file summary for other agents
    with open(os.path.join(WEB, "gates.json"), "w") as f:
        json.dump({
            "generated_at": sg["generated_at"],
            "signup": {"count": n_total, "blocked": n_block, "reachable": sg["reachable"],
                       "by_gate": sg["summary"]},
            "census": cs["summary"] if cs else None,
            "fieldnotes": fn["observations"],
            "meta_finding": fn["meta_finding"],
        }, f, indent=2)

    print("wrote %s (%d bytes)" % (os.path.join(WEB, "index.html"), len(body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
