#!/usr/bin/env python3
"""Agent Gates - deep-dive on the domains flagged as serving a signed-agent
key directory.

The census can only say "a key document is served". This script fetches each
flagged URL, follows and records the redirect target, parses the payload, and
classifies its shape:

  jwks_directory  {"keys": [...]}  - the shape the Web Bot Auth draft describes
  bare_jwk        a single JWK object with no "keys" array
  other           something else that parsed as JSON

GET only, public URLs, one request per surface, declared bot UA.

Output: data/key_directories.json
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CENSUS = os.path.join(DATA, "standards_census.json")
OUT = os.path.join(DATA, "key_directories.json")

UA = ("AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
      "autonomous-agent reachability measurement)")
PATH = "/.well-known/http-message-signatures-directory"


def classify(body):
    """Return (shape, detail) for a fetched key document."""
    try:
        doc = json.loads(body)
    except Exception as exc:
        return "unparseable", str(exc)[:120]
    if isinstance(doc, dict) and isinstance(doc.get("keys"), list):
        keys = doc["keys"]
        algs = sorted({str(k.get("alg") or k.get("crv") or k.get("kty"))
                       for k in keys if isinstance(k, dict)})
        detail = {"key_count": len(keys), "algorithms": algs,
                  "top_level_fields": sorted(doc.keys())}
        if doc.get("signature_agent"):
            detail["signature_agent"] = doc["signature_agent"]
        if doc.get("purpose"):
            detail["purpose"] = doc["purpose"]
        return "jwks_directory", detail
    if isinstance(doc, dict) and doc.get("kty"):
        return "bare_jwk", {"top_level_fields": sorted(doc.keys()),
                            "kty": doc.get("kty"), "crv": doc.get("crv"),
                            "alg": doc.get("alg"), "use": doc.get("use"),
                            "has_expiry": "exp" in doc}
    return "other", {"type": type(doc).__name__}


def probe(domain):
    rec = {"domain": domain, "url": "https://%s%s" % (domain, PATH)}
    try:
        req = urllib.request.Request(rec["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8", "replace")
            rec["status"] = r.status
            rec["content_type"] = r.headers.get("Content-Type")
            rec["final_url"] = r.geturl()
            rec["redirected"] = r.geturl() != rec["url"]
            rec["bytes"] = len(body)
    except Exception as exc:
        rec["status"] = None
        rec["error"] = str(exc)[:160]
        rec["shape"] = "unreachable"
        return rec
    rec["shape"], rec["detail"] = classify(body)
    return rec


def main():
    domains = []
    if os.path.exists(CENSUS):
        with open(CENSUS) as fh:
            census = json.load(fh)
        domains = [r["domain"] for r in census.get("results", [])
                   if r.get("has_sig_directory")]
    if not domains:
        domains = ["chatgpt.com", "shopify.com"]
    results = [probe(d) for d in domains]
    shapes = {}
    for r in results:
        shapes[r["shape"]] = shapes.get(r["shape"], 0) + 1
    payload = {
        "probed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": PATH,
        "probed": len(results),
        "shapes": shapes,
        "jwks_directory_count": shapes.get("jwks_directory", 0),
        "results": results,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    print("=== KEY DIRECTORY CLASSIFICATION (n=%d) ===" % len(results))
    for r in results:
        print("  %-16s %-15s %s" % (r["domain"], r["shape"],
              ("-> " + r["final_url"]) if r.get("redirected") else ""))
        if isinstance(r.get("detail"), dict):
            print("      %s" % json.dumps(r["detail"])[:200])
    print("  jwks_directory (spec-shaped): %d/%d" %
          (shapes.get("jwks_directory", 0), len(results)))


if __name__ == "__main__":
    main()
