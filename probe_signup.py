"""Agent Gates - signup-surface prober.

Measures what an honestly-declared autonomous AI agent can reach on the open
internet. Non-destructive: GET only, public URLs only, one request per surface,
robots.txt honoured, identifed user-agent that says exactly what this is.
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import ssl
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

USER_AGENT = (
    "AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
    "autonomous-agent reachability measurement; GET-only, non-destructive)"
)
TIMEOUT = 20
UA_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*", "Accept-Language": "en"}

AI_AGENT_TOKENS = [
    "gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web",
    "anthropic-ai", "ccbot", "google-extended", "perplexitybot", "bytespider",
    "amazonbot", "applebot-extended", "meta-externalagent", "cohere-ai",
    "youbot", "diffbot", "imagesiftbot", "omgilibot", "timpibot",
    "facebookbot", "petalbot", "iaskspider", "crawl4ai", "kumatocrawler",
]

WAF_SIGNATURES = [
    ("cloudflare", ["cloudflare", "cf-ray", "cf-mitigated"]),
    ("akamai", ["akamai", "akamaighost"]),
    ("datadome", ["datadome"]),
    ("perimeterx", ["perimeterx", "px-"]),
    ("imperva", ["imperva", "incapsula"]),
    ("sucuri", ["sucuri"]),
    ("fastly", ["fastly"]),
    ("aws-waf", ["awselb", "awselb/"]),
]

CHALLENGE_MARKERS = [
    "just a moment", "cf-challenge", "attention required", "checking your browser",
    "enable javascript and cookies to continue", "ddos protection by",
    "verify you are human", "please verify you are a human", "unusual traffic",
    "are you a robot", "cf_chl_opt", "challenge-platform",
]

TARGETS = [
    {"id": "hn", "name": "Hacker News", "category": "news/community", "url": "https://news.ycombinator.com/login"},
    {"id": "github", "name": "GitHub", "category": "code hosting", "url": "https://github.com/signup"},
    {"id": "gitlab", "name": "GitLab", "category": "code hosting", "url": "https://gitlab.com/users/sign_up"},
    {"id": "bsky", "name": "Bluesky", "category": "social", "url": "https://bsky.app/"},
    {"id": "mastodon_social", "name": "Mastodon (mastodon.social)", "category": "social/fediverse", "url": "https://mastodon.social/auth/sign_up"},
    {"id": "reddit", "name": "Reddit", "category": "social", "url": "https://www.reddit.com/register/"},
    {"id": "lemmy_ml", "name": "Lemmy (lemmy.ml)", "category": "social/fediverse", "url": "https://lemmy.ml/signup"},
    {"id": "discourse", "name": "Discourse (meta)", "category": "forum", "url": "https://meta.discourse.org/signup"},
    {"id": "x", "name": "X", "category": "social", "url": "https://x.com/i/flow/signup"},
    {"id": "lobsters", "name": "Lobsters", "category": "news/community", "url": "https://lobste.rs/login"},
    {"id": "tildes", "name": "Tildes", "category": "news/community", "url": "https://tildes.net/register"},
    {"id": "devto", "name": "dev.to", "category": "publishing", "url": "https://dev.to/enter"},
    {"id": "medium", "name": "Medium", "category": "publishing", "url": "https://medium.com/m/signin"},
    {"id": "substack", "name": "Substack", "category": "publishing", "url": "https://substack.com/signup"},
    {"id": "producthunt", "name": "Product Hunt", "category": "launch platform", "url": "https://www.producthunt.com/"},
    {"id": "stackoverflow", "name": "Stack Overflow", "category": "Q&A", "url": "https://stackoverflow.com/users/signup"},
    {"id": "wikipedia", "name": "Wikipedia", "category": "reference", "url": "https://en.wikipedia.org/w/index.php?title=Special:CreateAccount&returnto=Main+Page"},
    {"id": "craigslist", "name": "Craigslist", "category": "classifieds", "url": "https://accounts.craigslist.org/signup"},
    {"id": "ebay", "name": "eBay", "category": "commerce", "url": "https://signup.ebay.com/pa/crte"},
    {"id": "stripe", "name": "Stripe", "category": "payments", "url": "https://dashboard.stripe.com/register"},
    {"id": "vercel", "name": "Vercel", "category": "hosting", "url": "https://vercel.com/signup"},
    {"id": "netlify", "name": "Netlify", "category": "hosting", "url": "https://app.netlify.com/signup"},
    {"id": "railway", "name": "Railway", "category": "hosting", "url": "https://railway.app/login"},
    {"id": "npm", "name": "npm", "category": "package registry", "url": "https://www.npmjs.com/signup"},
    {"id": "openai_platform", "name": "OpenAI Platform", "category": "AI API", "url": "https://platform.openai.com/signup"},
    {"id": "keyid", "name": "KeyID.ai", "category": "agent identity", "url": "https://keyid.ai/"},
    {"id": "cloudflare", "name": "Cloudflare", "category": "infrastructure", "url": "https://dash.cloudflare.com/sign-up"},
    {"id": "huggingface", "name": "Hugging Face", "category": "AI platform", "url": "https://huggingface.co/join"},
    {"id": "arxiv", "name": "arXiv", "category": "preprints", "url": "https://arxiv.org/user/register"},
    {"id": "wallapop", "name": "Wallapop", "category": "classifieds", "url": "https://es.wallapop.com/register"},
    {"id": "leboncoin", "name": "Leboncoin", "category": "classifieds", "url": "https://www.leboncoin.fr/compte/creation"},
    {"id": "nostr_njump", "name": "Nostr (njump gateway)", "category": "social/decentralised", "url": "https://njump.me/"},
]


def fetch(url, method="GET"):
    req = urllib.request.Request(url, headers=UA_HEADERS, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            body = r.read(400000)
            return {
                "status": r.status,
                "final_url": r.geturl(),
                "headers": dict(r.headers.items()),
                "body": body.decode("utf-8", "replace"),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        try:
            body = e.read(400000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"status": e.code, "final_url": url, "headers": dict(e.headers.items()) if e.headers else {},
                "body": body, "error": "HTTPError"}
    except Exception as e:
        return {"status": None, "final_url": url, "headers": {}, "body": "", "error": "%s: %s" % (type(e).__name__, str(e)[:160])}


def parse_robots(text):
    """Return list of (agents, rules) groups; rules are raw Disallow/Allow values."""
    groups, agents, rules = [], [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if agents and rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
        elif k == "disallow" and agents:
            rules.append(v)
        elif k == "allow" and agents:
            rules.append("!" + v)
    if agents:
        groups.append((agents, rules))
    return groups


def is_disallowed(groups, agents_of_interest, path):
    """True if any of agents_of_interest is disallowed at path."""
    hit = False
    for agents, rules in groups:
        if not any(a in agents_of_interest for a in agents):
            continue
        for r in rules:
            if r.startswith("!"):
                continue
            if r == "":
                continue
            if r == "/" or path.startswith(r):
                hit = True
    return hit


def detect_waf(headers):
    blob = " ".join("%s: %s" % (k.lower(), v.lower()) for k, v in headers.items())
    for vendor, sigs in WAF_SIGNATURES:
        for s in sigs:
            if s in blob:
                return vendor
    return None


def classify(rec):
    """Priority-ordered gate classification."""
    if rec["robots_disallows_path"]:
        return "robots-disallow"
    body = (rec.get("_body") or "").lower()
    if rec.get("http_status") == 402:
        return "pay-per-crawl"
    if rec["challenge_detected"]:
        return "waf-challenge"
    if rec.get("captcha_signal") and not rec.get("http_status") == 200:
        return "captcha"
    if rec.get("phone_signal"):
        return "phone"
    if any(t in body for t in ["invite only", "invitation", "by approval", "requires approval",
                               "application to join", "account approval", "awaiting approval"]):
        return "human-approval"
    if rec.get("captcha_signal"):
        return "captcha"
    if rec.get("email_signal"):
        return "email"
    return "open"


BLOCKING_GATES = {"robots-disallow", "captcha", "phone", "pay-per-crawl", "waf-challenge", "human-approval"}


def probe(target):
    host = urllib.parse.urlparse(target["url"]).netloc
    path = urllib.parse.urlparse(target["url"]).path or "/"
    rec = dict(target)
    rec.update({
        "host": host, "robots_status": None, "robots_disallows_path": False,
        "ai_agent_disallows_path": False,
        "ai_agents_named": [], "http_status": None, "final_url": None, "server": None,
        "elapsed_ms": None, "waf": None, "challenge_detected": False,
        "phone_signal": False, "captcha_signal": False, "email_signal": False,
        "oauth_available": False, "error": None, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    # --- robots.txt first ---
    try:
        rb = fetch("https://%s/robots.txt" % host)
        rec["robots_status"] = rb["status"]
        if rb["status"] == 200 and rb["body"]:
            groups = parse_robots(rb["body"])
            rec["ai_agents_named"] = sorted({a for agents, _ in groups for a in agents if a in AI_AGENT_TOKENS})
            # Two distinct metrics, deliberately kept apart:
            #   robots_disallows_path    -> a generic declared crawler is forbidden here.
            #   ai_agent_disallows_path  -> the site names AI agents specifically and forbids them.
            # Only the first stops us fetching, because that is what crawler etiquette binds us to.
            rec["robots_disallows_path"] = is_disallowed(groups, {"*"}, path)
            rec["ai_agent_disallows_path"] = is_disallowed(groups, set(AI_AGENT_TOKENS), path)
    except Exception as e:
        rec["error"] = "robots: %s" % str(e)[:120]
    time.sleep(1.5 + random.random() * 0.6)

    if rec["robots_disallows_path"]:
        rec["gate"] = "robots-disallow"
        rec["outcome"] = "BLOCKED"
        rec.pop("_body", None)
        return rec

    # --- the surface itself, one request ---
    t0 = time.time()
    r = fetch(target["url"])
    rec["elapsed_ms"] = int((time.time() - t0) * 1000)
    rec["http_status"] = r["status"]
    rec["final_url"] = r["final_url"]
    rec["error"] = r["error"] or rec["error"]
    body = r["body"]
    low = body.lower()
    rec["server"] = (r["headers"].get("Server") or r["headers"].get("server") or "")[:80]
    rec["waf"] = detect_waf(r["headers"])
    rec["challenge_detected"] = any(m in low for m in CHALLENGE_MARKERS) or r["status"] in (403, 429, 503) and bool(rec["waf"])
    rec["phone_signal"] = bool(re.search(r"phone|mobile number|sms|verify.{0,20}number", low))
    rec["captcha_signal"] = any(m in low for m in ["captcha", "recaptcha", "hcaptcha", "turnstile", "g-recaptcha"])
    rec["email_signal"] = bool(re.search(r'type=["\']email["\']|name=["\']email["\']', low)) or "email" in low
    rec["oauth_available"] = any(p in low for p in ["sign in with google", "continue with google", "sign in with github",
                                                    "continue with github", "sign in with apple", "continue with apple"])
    rec["_body"] = body
    rec["gate"] = classify(rec)
    rec["outcome"] = "BLOCKED" if rec["gate"] in BLOCKING_GATES else "REACHABLE"
    rec.pop("_body", None)
    return rec


def main():
    print("Agent Gates signup prober - %d surfaces" % len(TARGETS))
    print("UA: %s" % USER_AGENT)
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rec in ex.map(probe, TARGETS):
            results.append(rec)
            print("  %-22s %-16s %-9s http=%s %s" % (
                rec["id"], rec["gate"], rec["outcome"], rec["http_status"], rec["waf"] or ""), flush=True)

    summary = {}
    for r in results:
        summary[r["gate"]] = summary.get(r["gate"], 0) + 1
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_agent": USER_AGENT,
        "count": len(results),
        "blocked": sum(1 for r in results if r["outcome"] == "BLOCKED"),
        "reachable": sum(1 for r in results if r["outcome"] == "REACHABLE"),
        "summary": summary,
        "results": results,
    }
    with open(os.path.join(DATA, "signup_gates.json"), "w") as f:
        json.dump(out, f, indent=2)
    cols = ["id", "name", "category", "host", "gate", "outcome", "http_status", "waf",
            "robots_status", "robots_disallows_path", "ai_agent_disallows_path", "challenge_detected", "phone_signal",
            "captcha_signal", "email_signal", "oauth_available", "ai_agents_named", "checked_at"]
    with open(os.path.join(DATA, "signup_gates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = dict(r)
            row["ai_agents_named"] = ";".join(r["ai_agents_named"])
            w.writerow(row)

    print("\nBLOCKED %d / REACHABLE %d of %d" % (out["blocked"], out["reachable"], out["count"]))
    for g, c in sorted(summary.items(), key=lambda kv: -kv[1]):
        print("   %-16s %d" % (g, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
