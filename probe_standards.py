"""Agent Gates - standards census.

Measures how far agent-facing identity/access standards are actually deployed
across a real traffic-ranked domain list (Tranco). Four signals per domain:
robots.txt AI-agent blocking, the HTTP Message Signatures directory that
Cloudflare's verified-agent scheme relies on, llms.txt, and ai.txt.
"""
from __future__ import annotations

import csv
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from validate_census import is_sig_directory, is_text_standard, looks_like_html
from probe_keydirs import classify

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

USER_AGENT = (
    "AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
    "autonomous-agent reachability measurement; GET-only, non-destructive)"
)
TIMEOUT = 15
UA_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}
CENSUS_SIZE = 200

AI_AGENT_TOKENS = [
    "gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web",
    "anthropic-ai", "ccbot", "google-extended", "perplexitybot", "bytespider",
    "amazonbot", "applebot-extended", "meta-externalagent", "cohere-ai",
    "youbot", "diffbot", "imagesiftbot", "omgilibot", "timpibot", "facebookbot",
    "petalbot", "iaskspider", "crawl4ai", "kumatocrawler", "wrtnbot",
]

FALLBACK_DOMAINS = [
    "google.com", "youtube.com", "facebook.com", "instagram.com", "x.com", "wikipedia.org",
    "reddit.com", "amazon.com", "yahoo.com", "bing.com", "whatsapp.com", "netflix.com",
    "linkedin.com", "microsoft.com", "apple.com", "office.com", "live.com", "tiktok.com",
    "pinterest.com", "wordpress.com", "zoom.us", "github.com", "cloudflare.com", "mozilla.org",
    "nytimes.com", "cnn.com", "bbc.co.uk", "theguardian.com", "washingtonpost.com", "forbes.com",
    "bloomberg.com", "reuters.com", "espn.com", "spotify.com", "twitch.tv", "discord.com",
    "medium.com", "quora.com", "stackoverflow.com", "gitlab.com", "bitbucket.org", "atlassian.com",
    "salesforce.com", "shopify.com", "etsy.com", "ebay.com", "walmart.com", "target.com",
    "booking.com", "airbnb.com", "uber.com", "dropbox.com", "adobe.com", "oracle.com",
    "ibm.com", "samsung.com", "sony.com", "nintendo.com", "steampowered.com", "epicgames.com",
]


def http(url):
    req = urllib.request.Request(url, headers=UA_HEADERS)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def get_with_fallback(domain, path):
    for scheme in ("https", "http"):
        st, body = http("%s://%s%s" % (scheme, domain, path))
        if st is not None:
            return st, body
    return None, ""


def robots_blocks_ai(body):
    """Return the list of AI tokens that appear as a User-agent in robots.txt."""
    named = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip().lower() == "user-agent":
            tok = v.strip().lower()
            if tok in AI_AGENT_TOKENS:
                named.append(tok)
    return sorted(set(named))


def probe(domain):
    rec = {"domain": domain, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    st, body = get_with_fallback(domain, "/robots.txt")
    rec["robots_status"] = st
    # an HTTP 200 alone is not evidence: many sites answer every path with an HTML
    # error page, so require the body to actually look like a robots.txt
    rec["robots_present"] = bool(
        st == 200 and "user-agent" in body.lower() and not looks_like_html(body)
    )
    rec["ai_agents_named"] = robots_blocks_ai(body) if rec["robots_present"] else []
    rec["blocks_named_ai_agent"] = bool(rec["ai_agents_named"])
    time.sleep(1.5 + random.random() * 0.5)

    st, body = get_with_fallback(domain, "/.well-known/http-message-signatures-directory")
    rec["sig_directory_status"] = st
    rec["has_sig_directory"] = is_sig_directory(st, "", body)
    # "a key document exists" and "the document has the shape the draft
    # describes" are different claims - only the second is a working directory
    rec["sig_directory_shape"] = classify(body)[0] if rec["has_sig_directory"] else None
    time.sleep(1.5 + random.random() * 0.5)

    st, body = get_with_fallback(domain, "/llms.txt")
    rec["llms_txt_status"] = st
    rec["has_llms_txt"] = is_text_standard(st, "", body)
    time.sleep(1.5 + random.random() * 0.5)

    st, body = get_with_fallback(domain, "/ai.txt")
    rec["ai_txt_status"] = st
    rec["has_ai_txt"] = is_text_standard(st, "", body)
    return rec


def load_domains():
    path = os.path.join(DATA, "top_domains.txt")
    if os.path.exists(path):
        with open(path) as f:
            doms = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        if doms:
            print("loaded %d domains from data/top_domains.txt" % len(doms))
            return doms[:CENSUS_SIZE]
    # try Tranco directly
    try:
        st, body = http("https://tranco-list.eu/api/lists/date/latest")
        if st == 200:
            lid = json.loads(body)["list_id"]
            st, csvtext = http("https://tranco-list.eu/download/%s/%d" % (lid, CENSUS_SIZE))
            if st == 200 and csvtext:
                doms = []
                for line in csvtext.splitlines():
                    parts = line.split(",")
                    if len(parts) >= 2 and "." in parts[1]:
                        doms.append(parts[1].strip())
                if doms:
                    with open(path, "w") as f:
                        f.write("\n".join(doms) + "\n")
                    print("fetched %d domains from Tranco (list %s)" % (len(doms), lid))
                    return doms
    except Exception as e:
        print("tranco fetch failed: %s" % str(e)[:120])
    print("using fallback list (%d domains)" % len(FALLBACK_DOMAINS))
    with open(path, "w") as f:
        f.write("\n".join(FALLBACK_DOMAINS) + "\n")
    return FALLBACK_DOMAINS


def main():
    domains = load_domains()
    print("Agent Gates standards census - %d domains" % len(domains))
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rec in ex.map(probe, domains):
            results.append(rec)
            flag = "BLOCKS-AI(%d)" % len(rec["ai_agents_named"]) if rec["blocks_named_ai_agent"] else ""
            print("  %-28s robots=%s %s %s%s" % (
                rec["domain"], rec["robots_status"],
                "SIGDIR " if rec["has_sig_directory"] else "",
                "llms.txt " if rec["has_llms_txt"] else "",
                flag), flush=True)

    n = len(results)
    sig = sum(1 for r in results if r["has_sig_directory"])
    llms = sum(1 for r in results if r["has_llms_txt"])
    ai_txt = sum(1 for r in results if r["has_ai_txt"])
    rob = sum(1 for r in results if r["robots_present"])
    blocks = sum(1 for r in results if r["blocks_named_ai_agent"])
    # what a naive status-code-only census would have reported (kept so the
    # inflation caused by soft-404 pages is visible, not hidden)
    raw = {
        "robots_txt": sum(1 for r in results if r["robots_status"] == 200),
        "signature_directory": sum(1 for r in results if r["sig_directory_status"] == 200),
        "llms_txt": sum(1 for r in results if r["llms_txt_status"] == 200),
        "ai_txt": sum(1 for r in results if r["ai_txt_status"] == 200),
    }
    token_counts = {}
    for r in results:
        for t in r["ai_agents_named"]:
            token_counts[t] = token_counts.get(t, 0) + 1

    def pct(a):
        return round(100.0 * a / n, 1) if n else 0.0

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_agent": USER_AGENT,
        "census_size": n,
        "source": "Tranco top domains (https://tranco-list.eu)",
        "summary": {
            "robots_txt_present": rob, "robots_txt_present_pct": pct(rob),
            "blocks_named_ai_agent": blocks, "blocks_named_ai_agent_pct": pct(blocks),
            "has_signature_directory": sig, "has_signature_directory_pct": pct(sig),
            "has_llms_txt": llms, "has_llms_txt_pct": pct(llms),
            "has_ai_txt": ai_txt, "has_ai_txt_pct": pct(ai_txt),
            "sig_directory_jwks": sum(
                1 for r in results if r.get("sig_directory_shape") == "jwks_directory"),
            "sig_directory_jwks_pct": pct(sum(
                1 for r in results if r.get("sig_directory_shape") == "jwks_directory")),
            "token_counts": dict(sorted(token_counts.items(), key=lambda kv: -kv[1])),
            "status_code_only": raw,
            "status_code_only_note": (
                "Counts of HTTP 200 responses before content validation. Reported so the "
                "inflation from soft-404 pages (a 200 with an HTML error body) is visible."
            ),
        },
        "results": results,
    }
    with open(os.path.join(DATA, "standards_census.json"), "w") as f:
        json.dump(out, f, indent=2)
    cols = ["domain", "robots_status", "robots_present", "blocks_named_ai_agent", "ai_agents_named",
            "sig_directory_status", "has_sig_directory", "sig_directory_shape",
            "llms_txt_status", "has_llms_txt",
            "ai_txt_status", "has_ai_txt", "checked_at"]
    with open(os.path.join(DATA, "standards_census.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = dict(r)
            row["ai_agents_named"] = ";".join(r["ai_agents_named"])
            w.writerow(row)

    s = out["summary"]
    print("\n=== CENSUS SUMMARY (n=%d) ===" % n)
    print("robots.txt present                 %5d  %s%%" % (s["robots_txt_present"], s["robots_txt_present_pct"]))
    print("names an AI agent in robots.txt    %5d  %s%%" % (s["blocks_named_ai_agent"], s["blocks_named_ai_agent_pct"]))
    print("has signed-agent key directory     %5d  %s%%" % (s["has_signature_directory"], s["has_signature_directory_pct"]))
    print("has llms.txt                       %5d  %s%%" % (s["has_llms_txt"], s["has_llms_txt_pct"]))
    print("has ai.txt                         %5d  %s%%" % (s["has_ai_txt"], s["has_ai_txt_pct"]))
    print("top named tokens: %s" % ", ".join("%s=%d" % kv for kv in list(s["token_counts"].items())[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
