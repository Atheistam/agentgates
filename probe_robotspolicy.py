"""Agent Gates - robots.txt policy classification (the naming-vs-restricting check).

WHY THIS EXISTS
    The standards census (probe_standards.py) records which AI-agent tokens appear
    under a `User-agent:` line in robots.txt, and the site reports that as "names an
    AI agent". Reading the raw bodies afterwards showed the obvious hole: a group that
    names GPTBot is NOT necessarily a group that restricts GPTBot. All three of these
    are counted identically by a token-name census:

        User-agent: GPTBot          User-agent: GPTBot          User-agent: GPTBot
        Disallow: /                 Disallow: /private/         Allow: /

    The first excludes the crawler, the second restricts it partly, the third
    explicitly permits it. A number that reports "16% of domains name an AI agent"
    is true, but it is not the number most readers will hear ("16% block AI agents").

    This script re-probes robots.txt and classifies, for every AI token named, what
    the rules actually say. It also measures the case the token-name census cannot
    see at all: a domain whose wildcard group (`User-agent: *`) disallows everything,
    which blocks every AI crawler without ever naming one.

WHAT THIS DOES *NOT* PROVE
    - It classifies the *text* of robots.txt, not its enforcement. A Disallow is a
      request, not a wall; a compliant crawler honours it, a non-compliant one ignores
      it. This project measures policy as written, never as enforced.
    - A token named in an exact-match group may also be governed by that group only
      for paths it lists; robots.txt matching is longest-match on paths, and this
      script does not model path-level precedence beyond the whole-path case.
    - "Covered by the wildcard group" means the site restricts *everyone* by default,
      including this crawler; it is not evidence of a decision about AI agents.
    - Same host, same geography, same day, same honest user-agent as the census.
"""
from __future__ import annotations

import argparse
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate_census import looks_like_html  # noqa: E402
from probe_standards import AI_AGENT_TOKENS, USER_AGENT  # noqa: E402

DATA = os.path.join(HERE, "data")
TIMEOUT = 15
UA_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}

# how a named token's rules are classified
RESTRICT_ALL = "restrict_all"        # Disallow: / with nothing allowed back
RESTRICT_PARTIAL = "restrict_partial"  # some paths disallowed, site not fully closed
ALLOW_ONLY = "allow_only"            # named and explicitly allowed
MENTION_ONLY = "mention_only"        # named, but the group carries no rules
WILDCARD_ONLY = "wildcard_only"      # not named; governed by a `User-agent: *` group


def http(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA_HEADERS),
                                    timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            return r.status, r.read(400000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def get_robots(domain):
    for scheme in ("https", "http"):
        st, body = http("%s://%s/robots.txt" % (scheme, domain))
        if st is not None:
            return st, body
    return None, ""


def parse_groups(body):
    """robots.txt -> list of {"agents": [...], "rules": [(field, path), ...]}.

    A group is one or more consecutive User-agent lines followed by the rules that
    apply to them. Comments and blank lines are ignored; anything before the first
    User-agent line is discarded, as the parser in the RFC does.
    """
    groups = []
    cur = None
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if cur is None or cur["rules"]:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(value.lower())
        elif field in ("allow", "disallow") and cur is not None:
            cur["rules"].append((field, value))
    return groups


def classify_group(rules):
    if not rules:
        return MENTION_ONLY
    disallows = [p for f, p in rules if f == "disallow" and p]
    allows = [p for f, p in rules if f == "allow" and p]
    if any(p == "/" for p in disallows) and not allows:
        return RESTRICT_ALL
    if disallows:
        return RESTRICT_PARTIAL
    if allows:
        return ALLOW_ONLY
    return MENTION_ONLY


def token_policy(groups, token):
    """Exact-match group wins; otherwise fall back to the wildcard group.

    Tokens are canonicalised to lower case because robots.txt agent matching is
    case-insensitive (RFC 9309 section 2.2.1) while this project's token list is
    written the way the vendors spell it (`GPTBot`, `ClaudeBot`).
    """
    t = token.strip().lower()
    for g in groups:
        if t in g["agents"]:
            return classify_group(g["rules"]), "exact"
    for g in groups:
        if "*" in g["agents"]:
            c = classify_group(g["rules"])
            # the wildcard group only matters here when it actually closes the site;
            # "no rules at all for everyone" says nothing about AI agents.
            if c in (RESTRICT_ALL, RESTRICT_PARTIAL):
                return c, "wildcard"
            return None, "uncovered"
    return None, "uncovered"


def probe(domain):
    rec = {"domain": domain, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    st, body = get_robots(domain)
    rec["robots_status"] = st
    rec["robots_present"] = bool(st == 200 and "user-agent" in body.lower()
                                 and not looks_like_html(body))
    rec["groups"] = []
    rec["named_agents"] = []
    rec["tokens"] = {}
    if rec["robots_present"]:
        groups = parse_groups(body)
        rec["groups"] = [{"agents": g["agents"], "rules": ["%s %s" % r for r in g["rules"]]}
                         for g in groups]
        rec["named_agents"] = sorted({a for g in groups for a in g["agents"] if a != "*"})
        for tok in AI_AGENT_TOKENS:
            policy, how = token_policy(groups, tok)
            if policy is not None:
                rec["tokens"][tok] = {"policy": policy, "via": how}
    rec["names_ai_token"] = [t for t, v in rec["tokens"].items() if v["via"] == "exact"]
    rec["blocks_via_wildcard"] = any(v["via"] == "wildcard" and v["policy"] == RESTRICT_ALL
                                     for v in rec["tokens"].values())
    return rec


def summarize(results):
    n = len(results)
    present = [r for r in results if r["robots_present"]]
    named = [r for r in present if r["names_ai_token"]]
    exact_all = [r for r in named
                 if any(v["policy"] == RESTRICT_ALL for t, v in r["tokens"].items()
                        if v["via"] == "exact")]
    exact_any = [r for r in named
                 if any(v["policy"] in (RESTRICT_ALL, RESTRICT_PARTIAL)
                        for t, v in r["tokens"].items() if v["via"] == "exact")]
    allow_only = [r for r in named
                  if all(v["policy"] in (ALLOW_ONLY, MENTION_ONLY)
                         for t, v in r["tokens"].items() if v["via"] == "exact")]
    wildcard = [r for r in present if r["blocks_via_wildcard"] and not r["names_ai_token"]]
    per_token = {}
    for r in results:
        for t, v in r["tokens"].items():
            if v["via"] != "exact":
                continue
            d = per_token.setdefault(t, {"named": 0, "restrict_all": 0, "restrict_partial": 0,
                                         "allow_or_mention": 0})
            d["named"] += 1
            if v["policy"] == RESTRICT_ALL:
                d["restrict_all"] += 1
            elif v["policy"] == RESTRICT_PARTIAL:
                d["restrict_partial"] += 1
            else:
                d["allow_or_mention"] += 1

    def pct(a, d=None):
        d = n if d is None else d
        return round(100.0 * a / d, 1) if d else 0.0

    return {
        "answered": len(present), "asked": n,
        "answered_pct": pct(len(present)),
        "names_an_ai_token": len(named), "names_an_ai_token_pct": pct(len(named)),
        "names_an_ai_token_pct_of_answered": pct(len(named), len(present)),
        "named_and_restricts_all": len(exact_all),
        "named_and_restricts_all_pct": pct(len(exact_all)),
        "named_and_restricts_all_pct_of_named": pct(len(exact_all), len(named)),
        "named_and_restricts_some": len(exact_any),
        "named_and_restricts_some_pct_of_named": pct(len(exact_any), len(named)),
        "named_but_only_allows": len(allow_only),
        "named_but_only_allows_pct_of_named": pct(len(allow_only), len(named)),
        "blocks_everyone_incl_ai_via_wildcard_only": len(wildcard),
        "blocks_everyone_incl_ai_via_wildcard_only_pct": pct(len(wildcard)),
        "per_token": dict(sorted(per_token.items(), key=lambda kv: -kv[1]["named"])),
        "naming_is_not_restricting_note": (
            "Of the domains that name an AI agent, only a subset actually restricts it. "
            "The token-name census reports the naming figure; that figure must not be "
            "restated as a blocking figure."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify robots.txt AI-agent rules: naming vs restricting.")
    ap.add_argument("--domains", default=os.path.join(DATA, "top_domains.txt"))
    ap.add_argument("--out-prefix", default="robotspolicy_t1")
    args = ap.parse_args(argv)

    with open(args.domains) as f:
        domains = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    print("robots policy classification - %d domains from %s" % (len(domains), args.domains))

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rec in ex.map(probe, domains):
            results.append(rec)
            tag = ""
            if rec["names_ai_token"]:
                tag = "NAMES(%d)" % len(rec["names_ai_token"])
            if rec["blocks_via_wildcard"] and not rec["names_ai_token"]:
                tag += " WILDCARD-BLOCK"
            print("  %-30s robots=%s %s" % (rec["domain"], rec["robots_status"], tag), flush=True)
            time.sleep(1.2 + random.random() * 0.4)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_agent": USER_AGENT,
        "domains_file": args.domains,
        "classifier": {
            "restrict_all": "exact-match group with `Disallow: /` and no Allow rule",
            "restrict_partial": "exact-match group disallowing specific paths only",
            "allow_only": "exact-match group that names the token but only allows paths",
            "wildcard_only": "token not named; the `User-agent: *` group disallows everything",
            "note": "Classification is of the text of robots.txt, not of its enforcement.",
        },
        "summary": summarize(results),
        "results": results,
    }
    jpath = os.path.join(DATA, args.out_prefix + ".json")
    with open(jpath, "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(DATA, args.out_prefix + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["domain", "robots_status", "robots_present", "named_ai_tokens",
                    "restricts_all_named", "restricts_some_named", "wildcard_only_block"])
        for r in results:
            exact = {t: v for t, v in r["tokens"].items() if v["via"] == "exact"}
            w.writerow([r["domain"], r["robots_status"], r["robots_present"],
                        ";".join(sorted(exact)),
                        ";".join(sorted(t for t, v in exact.items() if v["policy"] == RESTRICT_ALL)),
                        ";".join(sorted(t for t, v in exact.items()
                                        if v["policy"] in (RESTRICT_ALL, RESTRICT_PARTIAL))),
                        r["blocks_via_wildcard"] and not exact])

    s = out["summary"]
    print("\n=== ROBOTS POLICY (n=%d asked, %d answered) ===" % (s["asked"], s["answered"]))
    print("names an AI token                     %4d  %5.1f%% of asked  (%.1f%% of answering)"
          % (s["names_an_ai_token"], s["names_an_ai_token_pct"],
             s["names_an_ai_token_pct_of_answered"]))
    print("  of those, restricts ALL named       %4d  %5.1f%% of namers"
          % (s["named_and_restricts_all"], s["named_and_restricts_all_pct_of_named"]))
    print("  of those, restricts at least one    %4d  %5.1f%% of namers"
          % (s["named_and_restricts_some"], s["named_and_restricts_some_pct_of_named"]))
    print("  of those, only ever allows them     %4d  %5.1f%% of namers"
          % (s["named_but_only_allows"], s["named_but_only_allows_pct_of_named"]))
    print("blocks everyone incl. AI, names none  %4d  %5.1f%%"
          % (s["blocks_everyone_incl_ai_via_wildcard_only"],
             s["blocks_everyone_incl_ai_via_wildcard_only_pct"]))
    print("wrote %s" % jpath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
