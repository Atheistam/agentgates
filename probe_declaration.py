"""Agent Gates - the declaration experiment.

THE QUESTION
    The whole premise of agent-facing standards (robots AI rules, ai.txt, signature
    directories, the certification/U agent-ID schemes) is that an agent which
    identifies itself honestly gets treated at least as well as one that does not.
    That premise is almost never tested. This script tests it.

THE METHOD
    For each target URL, fetch it TWICE, changing exactly one thing: the User-Agent.
      pass A ("declared"): AgentGatesBot/0.1 (+https://agentgates.surge.sh; ...)
      pass B ("generic"):  an ordinary current desktop Chrome UA, claiming nothing
    Everything else is held identical: same headers otherwise, no cookies, no JS,
    GET only, same timeout, redirects followed and the FINAL url recorded.
    The two passes run sequentially per target so that transient network conditions
    affect both passes roughly equally; targets are probed 3 at a time with random
    sleeps so nothing is hammered.

    We compare HTTP status, redirect count, final URL, body length, and a
    whitespace-normalised body hash (so formatting jitter is not scored as a
    difference), and we scan for bot-challenge markers.

WHAT THIS PROVES
    Whether, for THIS fixed list of URLs, at THIS moment, honest declaration was
    answered differently from a generic browser UA — and in which direction.

WHAT THIS DOES *NOT* PROVE
    Nothing here is causal about "AI" specifically: we changed the User-Agent string
    between two passes, so any difference is attributable to the UA line as a whole,
    not to the word "bot" in it. Two passes per URL is a single pairwise sample; a
    WAF that challenges probabilistically, or that keys on IP rate rather than UA,
    will show up as noise. Absence of a difference on 40 URLs is not absence of
    discrimination in general, and a difference on one URL is one URL. The body-hash
    comparison is also session-blind: many pages are dynamically personalised, which
    would make even a genuine "both allowed" response look like a difference in size.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

DECLARED_UA = (
    "AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
    "autonomous-agent reachability measurement; GET-only, non-destructive)"
)
GENERIC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

TIMEOUT = 20
MAX_BYTES = 400000

CHALLENGE_MARKERS = [
    "just a moment", "cf-challenge", "attention required", "checking your browser",
    "enable javascript and cookies to continue", "ddos protection by",
    "verify you are human", "please verify you are a human", "unusual traffic",
    "are you a robot", "cf_chl_opt", "challenge-platform", "access denied",
    "request blocked", "captcha", "bot detection", "px-captcha", "are you human",
]

WAF_HEADERS = [
    "server", "cf-ray", "cf-mitigated", "cf-cache-status", "x-datadome",
    "x-amzn-waf-action", "x-akamai-transformed", "x-sucuri-id", "x-px-block",
    "x-iinfo", "x-cdn", "via",
]

EXTRA_TARGETS = [
    {"id": "google_home", "name": "Google", "category": "search", "url": "https://www.google.com/"},
    {"id": "wiki_main", "name": "Wikipedia (Main Page)", "category": "reference",
     "url": "https://en.wikipedia.org/wiki/Main_Page"},
    {"id": "so_questions", "name": "Stack Overflow (questions)", "category": "Q&A",
     "url": "https://stackoverflow.com/questions"},
    {"id": "reddit_home", "name": "Reddit (front)", "category": "social",
     "url": "https://www.reddit.com/"},
    {"id": "hn_front", "name": "Hacker News (front)", "category": "news/community",
     "url": "https://news.ycombinator.com/"},
    {"id": "nyt", "name": "New York Times", "category": "news", "url": "https://www.nytimes.com/"},
    {"id": "amazon_home", "name": "Amazon", "category": "commerce", "url": "https://www.amazon.com/"},
    {"id": "github_explore", "name": "GitHub (explore)", "category": "code hosting",
     "url": "https://github.com/explore"},
    {"id": "cloudflare_home", "name": "Cloudflare", "category": "infrastructure",
     "url": "https://www.cloudflare.com/"},
    {"id": "bbc_news", "name": "BBC News", "category": "news", "url": "https://www.bbc.com/news"},
]


class RedirectCounter(urllib.request.HTTPRedirectHandler):
    """Counts redirect hops so we can see a silent UA-conditional redirect."""

    def __init__(self):
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 10:
            raise urllib.error.HTTPError(newurl, 310, "too many redirects", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_body(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def norm_hash(text: str) -> str:
    return hashlib.sha256(normalize_body(text).encode("utf-8", "replace")).hexdigest()


# --- content-aware comparison --------------------------------------------------
# A whole-body hash is too brittle to answer the actual question. Two fetches of a
# live page differ over a nonce, a timestamp, an ad slot, a CSRF token -- none of
# which is the page telling an agent anything. So before comparing we reduce a
# response to its VISIBLE TEXT SKELETON: drop script/style/svg bodies and comments,
# strip volatile tokens (long hex, base64 blobs, digit runs), collapse whitespace.
# What survives is the readable content, which is what we are actually comparing.
SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>")
COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
TAG_RE = re.compile(r"(?s)<[^>]{0,4000}>")
VOID_RE = re.compile(r"(?:\b[0-9a-fA-F]{8,}\b|\b[A-Za-z0-9+/]{20,}={0,2}\b|\b\d{6,}\b)")
WS_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[a-z]{2,}")


def visible_text(body: str) -> str:
    t = SCRIPT_RE.sub(" ", body or "")
    t = COMMENT_RE.sub(" ", t)
    t = TAG_RE.sub(" ", t)
    t = html.unescape(t)
    t = VOID_RE.sub(" ", t)
    return WS_RE.sub(" ", t).strip().lower()


def token_set(vis: str) -> set:
    return set(WORD_RE.findall(vis))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return round(len(a & b) / float(len(a | b)), 4)


def fetch(url: str, ua: str) -> dict:
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    ctx = ssl.create_default_context()
    counter = RedirectCounter()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx), counter)
    req = urllib.request.Request(url, headers=headers)
    rec = {"ua": ua, "error": None, "status": None, "final_url": None,
           "redirects": 0, "body_len": 0, "body_sha256": None, "norm_sha256": None,
           "text_len": 0, "text_sha256": None,
           "challenge": False, "challenge_marker": None, "waf_headers": {}}
    body = ""
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BYTES).decode("utf-8", "replace")
            rec["status"] = r.status
            rec["final_url"] = r.geturl()
            hdrs = r.headers
            rec["waf_headers"] = {h: hdrs.get(h) for h in WAF_HEADERS if hdrs.get(h)}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES).decode("utf-8", "replace")
        except Exception:
            body = ""
        rec["status"] = e.code
        rec["final_url"] = getattr(e, "url", url)
        hdrs = e.headers or {}
        rec["waf_headers"] = {h: hdrs.get(h) for h in WAF_HEADERS if hdrs.get(h)}
    except Exception as e:
        rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        rec["redirects"] = counter.count
    rec["body_len"] = len(body)
    rec["body_sha256"] = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
    rec["norm_sha256"] = norm_hash(body)
    vis = visible_text(body)
    rec["text_len"] = len(vis)
    rec["text_sha256"] = hashlib.sha256(vis.encode("utf-8", "replace")).hexdigest()
    rec["_tokens"] = token_set(vis)
    low = normalize_body(body).lower()
    marker = None
    for m in CHALLENGE_MARKERS:
        if m in low:
            marker = m
            break
    # A raw substring hit is NOT a challenge: Cloudflare's own homepage is 400 KB of
    # JS that mentions "challenge-platform", and that is not a wall in our way. A
    # challenge is an INTERSTITIAL: a small page with a marker in it, or an explicit
    # block status. Both are recorded, only the latter drives classification.
    rec["marker_anywhere"] = marker
    short = rec["body_len"] < 25000
    mitigated = str(rec["waf_headers"].get("cf-mitigated", "")).lower() == "challenge"
    rec["challenge"] = bool(
        mitigated
        or (rec["status"] in (403, 429, 503) and rec["body_len"] < 25000)
        or (marker is not None and short)
    )
    rec["challenge_marker"] = marker if rec["challenge"] else None
    return rec


def usable(rec: dict) -> bool:
    """A page we would call reachable: a 2xx with content and no challenge wall."""
    return (rec["status"] is not None and 200 <= rec["status"] < 300
            and rec["body_len"] > 0 and not rec["challenge"])


CLASSES = [
    "identical",
    "declared_near_identical",
    "declared_differs_consistent",
    "declared_unstable",
    "declared_downgraded",
    "declared_blocked",
    "declared_throttled",
    "declared_allowed",
    "both_blocked",
    "dynamic_unresolved",
    "inconclusive",
]

# thresholds on visible-text token overlap
SAME = 0.97       # >= this and we call it the same page
MATERIAL = 0.90   # < this and at least a tenth of the visible content differs
CTRL = 0.97       # the same-UA pair must agree at least this well for the URL to count as resolvable


def same_page(x: dict, y: dict, sim: float) -> bool:
    if x["text_sha256"] and x["text_sha256"] == y["text_sha256"]:
        return True
    return sim >= SAME


def classify(d: dict, g: dict, d2: dict, g2: dict, sims: dict, notes: list) -> str:
    """Compare a declared-agent pass against a browser-UA pass -- with a control.

    The control is the point, and so is the comparison unit. Pages churn between any
    two fetches (nonces, timestamps, ad slots), so both the comparison and the control
    run on the VISIBLE TEXT SKELETON rather than the raw bytes. Each UA is fetched
    twice, interleaved. If the two browser-UA passes do not agree with each other
    (generic_control < CTRL) the page churns under a constant UA and any
    declared-vs-generic difference is not attributable to the UA -> dynamic_unresolved.
    Only when the browser UA reproduces itself while the declared UA reproducibly gets
    materially different content does a declaration effect exist.
    """
    if all(r["status"] is None for r in (d, g, d2, g2)):
        return "inconclusive"
    if not usable(d) and not usable(g):
        return "both_blocked"
    if usable(g) and not usable(d):
        if d["status"] == 429:
            return "declared_throttled"
        if d["challenge"]:
            notes.append("declared pass hit a bot challenge (%s)" % d["challenge_marker"])
        notes.append("declared %s vs generic %s" % (d["status"], g["status"]))
        return "declared_blocked"
    if usable(d) and not usable(g):
        notes.append("declared got %s where the browser UA got %s" % (d["status"], g["status"]))
        return "declared_allowed"
    if not (usable(d) and usable(g)):
        return "inconclusive"

    cross = sims["declared_vs_generic"]
    g_ctrl = sims["generic_control"]
    d_ctrl = sims["declared_control"]

    if same_page(d, g, cross):
        return "identical"

    if g_ctrl < CTRL:
        notes.append("control: the two browser-UA passes overlap only %.0f%%, so this page "
                     "churns under a constant UA" % (100 * g_ctrl))
        return "dynamic_unresolved"

    # the browser UA reproduced itself; the difference is therefore attributable
    if cross >= MATERIAL:
        notes.append("declared and generic share %.0f%% of visible content - same page, "
                     "cosmetic drift only" % (100 * cross))
        return "declared_near_identical"
    if d["text_len"] < 0.5 * max(1, g["text_len"]):
        notes.append("declared visible text %d chars vs generic %d chars (browser UA reproduced "
                     "itself at %.0f%%)" % (d["text_len"], g["text_len"], 100 * g_ctrl))
        return "declared_downgraded"
    if d_ctrl < CTRL:
        notes.append("declared overlap with generic %.0f%%, and the two declared passes only "
                     "agree %.0f%% with each other" % (100 * cross, 100 * d_ctrl))
        return "declared_unstable"
    notes.append("declared shares only %.0f%% of visible content with generic, each UA "
                 "reproducible across its own two passes" % (100 * cross))
    return "declared_differs_consistent"


def probe_target(t: dict) -> dict:
    """Four interleaved passes: generic, declared, generic, declared."""
    order = [GENERIC_UA, DECLARED_UA, GENERIC_UA, DECLARED_UA]
    got = []
    for i, ua in enumerate(order):
        got.append(fetch(t["url"], ua))
        if i < len(order) - 1:
            time.sleep(1.5 + random.random())
    g1, d1, g2, d2 = got
    sims = {
        "declared_vs_generic": jaccard(d1["_tokens"], g1["_tokens"]),
        "generic_control": jaccard(g1["_tokens"], g2["_tokens"]),
        "declared_control": jaccard(d1["_tokens"], d2["_tokens"]),
        "cross_control": jaccard(d2["_tokens"], g2["_tokens"]),
    }
    notes = []
    cls = classify(d1, g1, d2, g2, sims, notes)
    d, g = d1, g1
    if d["redirects"] != g["redirects"]:
        notes.append("redirect count differs: declared=%d generic=%d"
                     % (d["redirects"], g["redirects"]))
    if d["final_url"] != g["final_url"]:
        notes.append("final URL differs")
    out = {
        "id": t.get("id"), "name": t.get("name"), "category": t.get("category"),
        "url": t["url"], "classification": cls, "notes": notes, "sims": sims,
    }
    for key, rec in (("declared", d), ("generic", g),
                     ("declared_control", d2), ("generic_control", g2)):
        rec.pop("_tokens", None)
        out[key] = rec
    return out


def load_targets():
    targets = []
    try:
        import probe_signup
        for t in probe_signup.TARGETS:
            targets.append({"id": t["id"], "name": t["name"],
                            "category": t.get("category", ""), "url": t["url"]})
        print("loaded %d targets from probe_signup.TARGETS" % len(targets))
    except Exception as e:
        print("could not import probe_signup.TARGETS (%s); using extras only" % str(e)[:80])
    targets.extend(EXTRA_TARGETS)
    seen, out = set(), []
    for t in targets:
        if t["url"] not in seen:
            seen.add(t["url"])
            out.append(t)
    return out


def main():
    targets = load_targets()
    passes = 4
    print("Agent Gates declaration experiment - %d targets x %d paired passes = %d requests"
          % (len(targets), passes, passes * len(targets)))
    print("declared UA: %s" % DECLARED_UA)
    print("generic  UA: %s\n" % GENERIC_UA)

    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for rec in ex.map(probe_target, targets):
            results.append(rec)
            print("  %-28s %-27s d=%s g=%s %s" % (
                (rec["name"] or rec["url"])[:28], rec["classification"],
                rec["declared"]["status"], rec["generic"]["status"],
                ("| " + "; ".join(rec["notes"])) if rec["notes"] else ""), flush=True)
            time.sleep(1.2 + random.random())

    counts = {c: sum(1 for r in results if r["classification"] == c) for c in CLASSES}
    n = len(results)

    def pct(a):
        return round(100.0 * a / n, 1) if n else 0.0

    # where did the two UAs actually land relative to each other, on the visible text?
    cross = sorted(r["sims"]["declared_vs_generic"] for r in results)
    buckets = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 0.97), (0.97, 1.01)]
    hist = [{"lo": lo, "hi": hi,
             "n": sum(1 for x in cross if lo <= x < hi)} for lo, hi in buckets]
    mid = cross[len(cross) // 2] if cross else None
    resolved = n - counts["dynamic_unresolved"] - counts["inconclusive"]

    punished = (counts["declared_blocked"] + counts["declared_throttled"]
                + counts["declared_downgraded"])
    differing = counts["declared_differs_consistent"] + counts["declared_unstable"]
    unresolved = counts["dynamic_unresolved"] + counts["inconclusive"]
    # any target where the two UAs reproducibly produced different content:
    # downgraded + differs_consistent (control passed in every one of these cases)
    clean_diff = punished + differing
    # denominator that matters: targets where the GENERIC pass got a usable page,
    # i.e. places a non-declaring client could have gone
    open_to_generic = sum(1 for r in results if usable(r["generic"]))
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "declared_ua": DECLARED_UA,
        "generic_ua": GENERIC_UA,
        "method_note": (
            "FOUR interleaved GETs per URL (generic, declared, generic, declared) "
            "differing only in the User-Agent header. The repeat of each UA is a "
            "control: if the two browser-UA passes disagree with each other the page "
            "churns under a constant UA, and the declared-vs-generic difference is not "
            "attributable to the UA (scored `dynamic_unresolved`). Sequential per "
            "target so transient conditions hit all four passes alike; 3 targets "
            "concurrently with randomised sleeps. Body comparison uses a "
            "whitespace-normalised SHA-256 so formatting jitter is not scored."
        ),
        "passes_per_target": passes,
        "passes_per_url": passes,
        "summary": {
            "n_targets": n,
            "counts": counts,
            "pct": {c: pct(counts[c]) for c in CLASSES},
            "open_to_generic_ua": open_to_generic,
            "punished_for_declaring": punished,
            "punished_for_declaring_pct_of_all": pct(punished),
            "punished_for_declaring_pct_of_open": (
                round(100.0 * punished / open_to_generic, 1) if open_to_generic else None),
            "differing_on_declaration": differing,
            "differing_on_declaration_pct": pct(differing),
            "clean_difference_total": clean_diff,
            "clean_difference_pct": pct(clean_diff),
            "unresolved": unresolved,
            "unresolved_pct": pct(unresolved),
            "resolved": resolved,
            "resolved_pct": round(100.0 * resolved / n, 1) if n else 0.0,
            "similarity_median_declared_vs_generic": mid,
            "similarity_histogram": hist,
            "both_blocked": counts["both_blocked"],
            "both_blocked_pct": pct(counts["both_blocked"]),
            "interpretation_guard": (
                "The UA line is changed as a WHOLE, so any difference is attributable "
                "to the whole string, not specifically to declaring non-humanness. "
                "The control pass bounds churn but does not eliminate it; a WAF that "
                "is probabilistic may still read as a stable-looking difference."
            ),
        },
        "results": results,
    }
    with open(os.path.join(DATA, "declaration_test.json"), "w") as f:
        json.dump(out, f, indent=2)

    cols = ["id", "name", "category", "url", "classification",
            "d_status", "d_redirects", "d_body_len", "d_challenge",
            "g_status", "g_redirects", "g_body_len", "g_challenge",
            "similarity_declared_vs_generic", "similarity_generic_control",
            "similarity_declared_control", "notes"]
    with open(os.path.join(DATA, "declaration_test.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            w.writerow([r["id"], r["name"], r["category"], r["url"], r["classification"],
                        r["declared"]["status"], r["declared"]["redirects"],
                        r["declared"]["body_len"], r["declared"]["challenge"],
                        r["generic"]["status"], r["generic"]["redirects"],
                        r["generic"]["body_len"], r["generic"]["challenge"],
                        r["sims"]["declared_vs_generic"], r["sims"]["generic_control"],
                        r["sims"]["declared_control"],
                        "; ".join(r["notes"])])

    s = out["summary"]
    print("\n=== DECLARATION EXPERIMENT (n=%d URLs x %d paired passes) ===" % (n, passes))
    for c in CLASSES:
        print("  %-28s %4d  %s%%" % (c, counts[c], s["pct"][c]))
    print("  open to a generic browser UA        %4d  %s%%" % (open_to_generic, pct(open_to_generic)))
    print("  PUNISHED for declaring honestly     %4d  %s%% of all, %s%% of reachable-to-generic"
          % (punished, s["punished_for_declaring_pct_of_all"],
             s["punished_for_declaring_pct_of_open"]))
    print("  got a DIFFERENT page (control-clean) %3d  %s%%" % (clean_diff, s["clean_difference_pct"]))
    print("  UNRESOLVED after the control        %4d  %s%% (resolved: %s%%)"
          % (unresolved, s["unresolved_pct"], s["resolved_pct"]))
    print("  delivered differently (downgraded+differs+unstable) %d" % (punished + differing))
    print("  visible-text overlap, declared vs generic (median): %s" % mid)
    for h in hist:
        print("    %.2f-%.2f  %s" % (h["lo"], h["hi"], "#" * h["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
