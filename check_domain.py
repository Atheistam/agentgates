#!/usr/bin/env python3
"""Agent Gates - single-domain live check (the interactive counterpart to the census).

Given one domain, ask the same questions the census asks of 500:
  - does key-less, credential-less access to robots.txt even work (and is the body
    really a robots.txt, or a 200-wrapped HTML error page)?
  - which AI-agent tokens are NAMED, and of those, which are actually RESTRICTED?
    (This project's finding: naming is not restricting.)
  - are llms.txt / ai.txt present as content, not just as a status code?
  - is there a machine-signature key directory a declared agent could use to
    authenticate itself?

The output is deliberately <= 12 lines of plain ASCII so it can be pasted verbatim
into an IRC channel or a forum post. --json gives the full record.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate_census import is_sig_directory, is_text_standard, looks_like_html  # noqa: E402
from probe_standards import AI_AGENT_TOKENS  # noqa: E402
from probe_robotspolicy import (  # noqa: E402
    ALLOW_ONLY,
    MENTION_ONLY,
    RESTRICT_ALL,
    RESTRICT_PARTIAL,
    get_robots,
    parse_groups,
    token_policy,
)

SIG_DIR_PATH = "/.well-known/http-message-signatures-directory"
KEY_MIRROR_PATH = "/agent-key.jwks"


def http_get(domain, path):
    """Same fallback discipline as the census: https first, then plain http."""
    from probe_standards import get_with_fallback

    return get_with_fallback(domain, path)


def check(domain: str) -> dict:
    domain = domain.strip().lower()
    for pre in ("https://", "http://"):
        if domain.startswith(pre):
            domain = domain[len(pre):]
    domain = domain.split("/")[0]

    rec: dict = {"domain": domain, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # --- robots.txt: status AND content -------------------------------------
    st, body = get_robots(domain)
    present = bool(st == 200 and "user-agent" in body.lower() and not looks_like_html(body))
    rec["robots"] = {
        "status": st,
        "content_valid": present,
        "body_is_html": looks_like_html(body) if st == 200 else None,
        "bytes": len(body) if st == 200 else 0,
        "note": None,
    }
    if st == 200 and not present:
        rec["robots"]["note"] = "HTTP 200 but not robots.txt (soft-404 / HTML body)"
    elif st == 403:
        rec["robots"]["note"] = "403 at the edge (WAF/bot filter, not a policy)"
    elif st is None:
        rec["robots"]["note"] = "unreachable"

    named, restricted, unrestricted, by_token = [], [], [], {}
    if present:
        groups = parse_groups(body)
        for tok in AI_AGENT_TOKENS:
            policy, how = token_policy(groups, tok)
            if policy is None:
                continue
            by_token[tok] = {"policy": policy, "via": how}
            if how == "exact":
                named.append(tok)
                if policy in (RESTRICT_ALL, RESTRICT_PARTIAL):
                    restricted.append(tok)
                else:
                    unrestricted.append(tok)
        rec["robots"]["groups"] = len(groups)
        rec["robots"]["wildcard_restricts_all"] = any(
            "*" in g["agents"] and all(f == "disallow" for f, _ in g["rules"]) and
            any(p == "/" for f, p in g["rules"] if f == "disallow")
            for g in groups
        )
    rec["robots"]["named_ai_tokens"] = sorted(named)
    rec["robots"]["restricted_ai_tokens"] = sorted(restricted)
    rec["robots"]["named_but_not_restricted"] = sorted(unrestricted)
    rec["robots"]["token_detail"] = by_token

    # --- the text standards -------------------------------------------------
    for path, key in (("/llms.txt", "llms_txt"), ("/ai.txt", "ai_txt")):
        st2, body2 = http_get(domain, path)
        rec[key] = {"status": st2, "present": bool(is_text_standard(st2, "", body2))}

    # --- machine signature key directory -----------------------------------
    st3, body3 = http_get(domain, SIG_DIR_PATH)
    rec["sig_directory"] = {
        "path": SIG_DIR_PATH,
        "status": st3,
        "present": bool(is_sig_directory(st3, "", body3)),
    }
    st4, body4 = http_get(domain, KEY_MIRROR_PATH)
    rec["key_mirror"] = {"path": KEY_MIRROR_PATH, "status": st4, "present": st4 == 200}

    # --- verdict ------------------------------------------------------------
    if not present:
        verdict = "NO POLICY PUBLISHED"
        why = rec["robots"]["note"] or ("robots.txt %s" % st)
        level = "UNKNOWN"
    elif rec["robots"].get("wildcard_restricts_all") and not named:
        verdict = "CLOSED"
        why = "User-agent: * disallows everything; no AI token named"
        level = "CLOSED"
    elif named and len(restricted) == len(named):
        verdict = "CLOSED"
        why = "all %d named AI tokens are restricted" % len(named)
        level = "CLOSED"
    elif restricted:
        verdict = "PARTIAL"
        why = "%d of %d named AI tokens restricted" % (len(restricted), len(named))
        level = "PARTIAL"
    elif named:
        verdict = "OPEN"
        why = "%d AI tokens named, none of them restricted" % len(named)
        level = "OPEN"
    else:
        verdict = "OPEN"
        why = "robots.txt sets no rule for any AI token; wildcard group does not close the site"
        level = "OPEN"
    rec["verdict"] = {"level": level, "text": verdict, "reason": why}
    return rec


def render(rec: dict) -> str:
    r = rec["robots"]
    lines = []
    lines.append("agent-access check: %s   (%s)" % (rec["domain"], rec["checked_at"]))
    if r["content_valid"]:
        lines.append("robots.txt: HTTP %s, valid, %d groups, %d bytes" % (r["status"], r["groups"], r["bytes"]))
    else:
        lines.append("robots.txt: %s" % (r["note"] or ("HTTP %s" % r["status"])))
    if r["named_ai_tokens"]:
        lines.append("named AI agents: %s" % ", ".join(r["named_ai_tokens"]))
        lines.append("  restricted: %s" % (", ".join(r["restricted_ai_tokens"]) or "none"))
        lines.append("  named but NOT restricted: %s" % (", ".join(r["named_but_not_restricted"]) or "none"))
    else:
        lines.append("named AI agents: none")
    lines.append("llms.txt: %s (%s)   ai.txt: %s (%s)" % (
        "yes" if rec["llms_txt"]["present"] else "no", rec["llms_txt"]["status"],
        "yes" if rec["ai_txt"]["present"] else "no", rec["ai_txt"]["status"]))
    lines.append("signature key directory: %s (HTTP %s)" % (
        "yes" if rec["sig_directory"]["present"] else "no", rec["sig_directory"]["status"]))
    lines.append("VERDICT: %s - %s" % (rec["verdict"]["text"], rec["verdict"]["reason"]))
    lines.append("method + raw census: https://agentgates.surge.sh (declared agent, GET-only, no credentials)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rec = check(a.domain)
    if a.json:
        print(json.dumps(rec, indent=2, sort_keys=True))
    else:
        print(render(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
