"""Agent Gates - content validation for the standards census.

An HTTP 200 is not evidence. Many large sites answer *every* unknown path with a
200 and an HTML error page, which silently inflates any census that only checks
status codes. This module re-fetches each flagged URL and applies a content test
so the published percentages mean something.

Call apply_validation(census_dict) to correct flags in place and recompute the
summary, or run this file directly to re-validate data/standards_census.json.
"""
from __future__ import annotations

import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TIMEOUT = 15
UA_HEADERS = {
    "User-Agent": "AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
                  "autonomous-agent reachability measurement; GET-only, non-destructive)",
    "Accept": "*/*",
}

HTML_START = ("<!doctype", "<html", "<?xml", "<head", "<body", "<!--", "<meta", "<center")
HTML_MARKERS = ("<html", "<!doctype", "<head>", "<title", "<!--", "<noscript")


def fetch(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA_HEADERS),
                                   timeout=TIMEOUT, context=ssl.create_default_context())
        return r.status, (r.headers.get("Content-Type") or ""), r.read(60000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Content-Type") or "") if e.headers else "", ""
    except Exception:
        return None, "", ""


def looks_like_html(body):
    """Catch soft-404 pages regardless of leading whitespace, comments or BOM."""
    head = body.lstrip("\ufeff \t\r\n")[:600].lower()
    if head.startswith(HTML_START):
        return True
    return any(m in head for m in HTML_MARKERS)


def is_sig_directory(status, ctype, body):
    """A real HTTP Message Signatures directory is a JWKS-shaped JSON document."""
    if status != 200:
        return False
    ct = (ctype or "").lower()
    if "text/html" in ct:
        return False
    b = body.strip()
    if not b or b[0] not in "{[":
        return False
    low = b.lower()
    return any(k in low for k in ('"keys"', '"kty"', '"crv"', '"x"', "ed25519", "jwks"))


def is_text_standard(status, ctype, body):
    """llms.txt / ai.txt must be a plain-text document, not an SPA error page."""
    if status != 200:
        return False
    ct = (ctype or "").lower()
    if "text/html" in ct or "image/" in ct or "video/" in ct:
        return False
    b = body.strip()
    if len(b) < 8:
        return False
    if looks_like_html(b):
        return False
    return True


def probe_one(domain):
    """Re-validate all flagged standard URLs for one domain, plus robots.txt."""
    out = {"domain": domain}
    st, ct, body = fetch("https://%s/robots.txt" % domain)
    out["robots_verified"] = bool(st == 200 and "user-agent" in body.lower())
    time.sleep(1.2 + random.random() * 0.4)
    st, ct, body = fetch("https://%s/.well-known/http-message-signatures-directory" % domain)
    out["sig_directory_verified"] = is_sig_directory(st, ct, body)
    time.sleep(1.2 + random.random() * 0.4)
    st, ct, body = fetch("https://%s/llms.txt" % domain)
    out["llms_txt_verified"] = is_text_standard(st, ct, body)
    time.sleep(1.2 + random.random() * 0.4)
    st, ct, body = fetch("https://%s/ai.txt" % domain)
    out["ai_txt_verified"] = is_text_standard(st, ct, body)
    return out


def recompute_summary(c, use_verified=True):
    res = c["results"]
    n = len(res)
    sig_key = "sig_directory_verified" if use_verified and "sig_directory_verified" in res[0] else "has_sig_directory"
    ll_key = "llms_txt_verified" if use_verified and "llms_txt_verified" in res[0] else "has_llms_txt"
    ai_key = "ai_txt_verified" if use_verified and "ai_txt_verified" in res[0] else "has_ai_txt"

    def pct(a):
        return round(100.0 * a / n, 1) if n else 0.0

    rob = sum(1 for r in res if r.get("robots_verified", r["robots_present"]))
    blocks = sum(1 for r in res if r["blocks_named_ai_agent"])
    sig = sum(1 for r in res if r.get(sig_key))
    llms = sum(1 for r in res if r.get(ll_key))
    ai_txt = sum(1 for r in res if r.get(ai_key))
    token_counts = {}
    for r in res:
        for t in r["ai_agents_named"]:
            token_counts[t] = token_counts.get(t, 0) + 1

    c["summary"] = {
        "robots_txt_present": rob, "robots_txt_present_pct": pct(rob),
        "blocks_named_ai_agent": blocks, "blocks_named_ai_agent_pct": pct(blocks),
        "has_signature_directory": sig, "has_signature_directory_pct": pct(sig),
        "has_llms_txt": llms, "has_llms_txt_pct": pct(llms),
        "has_ai_txt": ai_txt, "has_ai_txt_pct": pct(ai_txt),
        "token_counts": dict(sorted(token_counts.items(), key=lambda kv: -kv[1])),
        "content_verified": use_verified and "sig_directory_verified" in res[0],
    }
    if "has_signature_directory_raw" not in c["summary"]:
        c["summary"]["has_signature_directory_raw"] = sum(1 for r in res if r.get("has_sig_directory"))
        c["summary"]["has_llms_txt_raw"] = sum(1 for r in res if r.get("has_llms_txt"))
        c["summary"]["has_ai_txt_raw"] = sum(1 for r in res if r.get("has_ai_txt"))
    return c


def apply_validation(census, max_workers=4):
    """Re-validate every flagged domain in-place; returns the corrected census."""
    res = census["results"]
    flagged = [r for r in res if r["robots_present"] or r["has_sig_directory"] or r["has_llms_txt"]
               or r["has_ai_txt"] or r.get("robots_verified") or r.get("sig_directory_verified")
               or r.get("llms_txt_verified") or r.get("ai_txt_verified")]
    print("re-validating %d flagged domains (of %d)" % (len(flagged), len(res)))
    by_domain = {r["domain"]: r for r in res}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for out in ex.map(probe_one, [r["domain"] for r in flagged]):
            by_domain[out["domain"]].update(out)
    for r in res:
        r.setdefault("sig_directory_verified", False)
        r.setdefault("llms_txt_verified", False)
        r.setdefault("ai_txt_verified", False)
    # domains never flagged can never be verified-true
    return recompute_summary(census, use_verified=True)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Independent counter-check of a census file.")
    ap.add_argument("--file", default="standards_census.json",
                    help="file inside data/ to re-validate (default: standards_census.json)")
    args = ap.parse_args()
    path = os.path.join(DATA, args.file)
    with open(path) as f:
        c = json.load(f)
    before = dict(c["summary"])
    apply_validation(c)
    with open(path, "w") as f:
        json.dump(c, f, indent=2)
    s = c["summary"]
    print("\n=== BEFORE (status-code only) -> AFTER (content verified) ===")
    for k, lbl in (("has_signature_directory", "signed-agent key directory"),
                   ("has_llms_txt", "llms.txt"),
                   ("has_ai_txt", "ai.txt")):
        raw = s.get(k + "_raw", before.get(k))
        print("  %-28s %3d (%.1f%%) -> %3d (%.1f%%)" % (lbl, raw,
              100.0 * raw / len(c["results"]), s[k], s[k + "_pct"]))
    print("  %-28s %3d (%.1f%%)" % ("blocks named AI agent",
          s["blocks_named_ai_agent"], s["blocks_named_ai_agent_pct"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
