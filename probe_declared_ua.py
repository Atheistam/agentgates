#!/usr/bin/env python3
"""The agent category gets a default: a baseline taken while the old default still holds.

On 2026-07-01 Cloudflare replaced its one-click "block AI bots" switch with three
lanes - Search, Agent, Training - and announced that from 2026-09-15 the Agent and
Training lanes are blocked by default, at the network edge, on pages that display
ads, for new zones and existing free-tier zones. Existing paid zones are not
changed automatically. Enforcement is by classification at the edge, from observed
behaviour and the declared user agent together.

This project sends one declared agent user agent to whatever it measures, and it
has spent eight runs measuring how the open web answers a declared agent. That
makes this the one moment in the project's life when a before/after is available
for free: today is before. So the same fixed host set is read twice, once with the
declared agent user agent and once with a control that declares nothing agentic,
and both readings are stored now.

What is stored is deliberately a baseline and not a finding. A pass taken before a
deadline cannot show what the deadline does. It can only be re-read afterwards -
and the honest version of that second reading is that a null result means the
default did not bite on this set, which is not the same as saying nothing changed
anywhere.

Both user agents are stored verbatim, because the whole policy turns on what is
declared and how it is classified. The ad marker is our own operationalisation of
"a page that displays ads" - the providers have not published theirs, so this one
is named, listed and counted in the data rather than assumed.
"""
import argparse
import hashlib
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STORE = os.path.join(DATA, "declared_ua_baseline.json")
DOMAINS = os.path.join(DATA, "top_domains.txt")

# The declared agent: the same string this project has been sending since the census.
AGENT_UA = ("AgentGatesBot/0.1 (+https://agentgates.surge.sh; "
            "research bot; measures how the open web answers a declared agent; "
            "contact vagopopulo@gmail.com)")
# The control: declares no bot, no purpose, and claims to be a browser.
CONTROL_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CHALLENGE_MARKERS = ["just a moment", "cf-chl", "attention required",
                     "verify you are human", "checking your browser",
                     "enable javascript and cookies to continue",
                     "ddos protection by"]
# Kept apart from the strong markers on purpose. A first pass counted "captcha" as a
# challenge and reported seven of forty hosts as challenged; four of those answered 200
# with a page whose signup furniture contains the word, which is not a challenge. A
# marker that fires on ordinary page furniture is not evidence, so it is counted
# separately and named as the weaker signal it is.
WEAK_MARKERS = ["captcha", "access denied", "blocked"]
AD_MARKERS = ["adsbygoogle", "googlesyndication", "doubleclick.net", "googletag",
              "prebid", "advertisement", "taboola", "outbrain", "criteo"]


def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch(url, ua, timeout=12.0):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx()) as r:
            body = r.read(400000)
            h = dict((k.lower(), v) for k, v in r.headers.items())
            status = r.status
            final = r.geturl()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(400000)
        except Exception:
            pass
        h = dict((k.lower(), v) for k, v in (e.headers or {}).items())
        status = e.code
        final = url
    except Exception as e:
        return {"status": None, "error": "%s: %s" % (type(e).__name__, e),
                "seconds": round(time.time() - t0, 2)}
    text = body.decode("utf-8", "replace").lower()
    return {
        "status": status,
        "final_url": final,
        "redirected": final.rstrip("/") != url.rstrip("/"),
        "seconds": round(time.time() - t0, 2),
        "bytes": len(body),
        "sha256_prefix": hashlib.sha256(body[:2048]).hexdigest()[:16],
        "server": h.get("server"),
        "via_cf_ray": bool(h.get("cf-ray")),
        "cf_mitigated": h.get("cf-mitigated"),
        "cloudflare_fronted": bool(h.get("cf-ray")) or "cloudflare" in (h.get("server") or "").lower(),
        "challenge_markers": [m for m in CHALLENGE_MARKERS if m in text],
        "weak_markers": [m for m in WEAK_MARKERS if m in text],
        "ad_markers": [m for m in AD_MARKERS if m in text],
    }


def load_domains(limit):
    out = []
    with open(DOMAINS) as f:
        for line in f:
            d = line.strip()
            if not d or d.startswith("#"):
                continue
            out.append(d)
            if len(out) >= limit:
                break
    return out


def verdict(a, c):
    """What the pair of readings says about this host, before any deadline."""
    if a.get("error") or c.get("error"):
        return "unreadable (%s)" % (a.get("error") or c.get("error"))
    if a["status"] == c["status"] and bool(a["challenge_markers"]) == bool(c["challenge_markers"]):
        if a["challenge_markers"]:
            return "both challenged"
        return "both served"
    if a["status"] != c["status"]:
        return "status differs: agent %s vs control %s" % (a["status"], c["status"])
    return "challenge differs: agent %s vs control %s" % (
        bool(a["challenge_markers"]), bool(c["challenge_markers"]))


def run(limit, label):
    domains = load_domains(limit)
    probe = {
        "pass": label,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "set": "first %d domains of %s" % (len(domains), os.path.basename(DOMAINS)),
        "why": ("a reading taken while the pre-2026-09-15 default still holds; the "
                "Cloudflare Agent lane is blocked by default from 2026-09-15 on "
                "ad-displaying pages for new and free-tier zones"),
        "declared_user_agent": AGENT_UA,
        "control_user_agent": CONTROL_UA,
        "control_is_not_neutral": ("the control differs from the declared agent in one "
                                   "thing only - the user agent string - and sends the same "
                                   "minimal header set. It is therefore not a browser: it is "
                                   "an undeclared client that is not pretending very hard. "
                                   "Where it is refused and the declared agent is served, "
                                   "the refusal is about the declaration and not about "
                                   "being a bot."),
        "instrument": ("v2. Pass 1 counted 'captcha' among the challenge markers and "
                       "reported seven of forty hosts challenged; four of those answered "
                       "200 with a page whose signup furniture contains the word, so the "
                       "marker was moved to a separately counted weak list. Pass 1 was "
                       "discarded rather than published."),
        "ad_marker_definition": AD_MARKERS,
        "challenge_marker_definition": CHALLENGE_MARKERS,
        "method": ("one request per host per user agent, sequential, 0.4 s apart, "
                   "no retries, redirects followed, TLS verification disabled"),
        "hosts": {},
    }
    for i, d in enumerate(domains, 1):
        url = "https://%s/" % d
        a = fetch(url, AGENT_UA)
        time.sleep(0.4)
        c = fetch(url, CONTROL_UA)
        rec = {"declared_agent": a, "control": c, "verdict": verdict(a, c),
               "cloudflare_fronted": bool(a.get("cloudflare_fronted") or c.get("cloudflare_fronted")),
               "ad_marked": bool(a.get("ad_markers") or c.get("ad_markers"))}
        probe["hosts"][d] = rec
        print("  %-32s %-28s status %s/%s cf=%s ads=%s"
              % (d, rec["verdict"], a.get("status"), c.get("status"),
                 rec["cloudflare_fronted"], rec["ad_marked"]), flush=True)
        time.sleep(0.4)

    hosts = probe["hosts"]
    cf = [d for d, r in hosts.items() if r["cloudflare_fronted"]]
    ad = [d for d, r in hosts.items() if r["ad_marked"]]
    probe["summary"] = {
        "hosts": len(hosts),
        "cloudflare_fronted": len(cf),
        "ad_marked": len(ad),
        "cloudflare_and_ad": len([d for d in cf if d in ad]),
        "agent_status_by_code": {},
        "verdicts": {},
        "agent_challenged": len([r for r in hosts.values() if r["declared_agent"].get("challenge_markers")]),
        "control_challenged": len([r for r in hosts.values() if r["control"].get("challenge_markers")]),
        "agent_weak_markers": len([r for r in hosts.values() if r["declared_agent"].get("weak_markers")]),
        "control_weak_markers": len([r for r in hosts.values() if r["control"].get("weak_markers")]),
        "readable": len([r for r in hosts.values()
                         if not (r["declared_agent"].get("error") or r["control"].get("error"))]),
        "unreadable": len([r for r in hosts.values()
                           if r["declared_agent"].get("error") or r["control"].get("error")]),
    }
    for r in hosts.values():
        code = str(r["declared_agent"].get("status"))
        probe["summary"]["agent_status_by_code"][code] = \
            probe["summary"]["agent_status_by_code"].get(code, 0) + 1
        probe["summary"]["verdicts"][r["verdict"]] = \
            probe["summary"]["verdicts"].get(r["verdict"], 0) + 1
    return probe


def compare():
    try:
        with open(STORE) as f:
            store = json.load(f)
    except Exception as e:
        print("no baseline to compare against (%s)" % e)
        return 1
    passes = store.get("passes") or []
    if len(passes) < 2:
        print("only one pass stored (%s); nothing to compare yet"
              % (passes[0].get("pass") if passes else "none"))
        return 0
    old, new = passes[-2], passes[-1]
    print("comparing %s (%s) -> %s (%s)"
          % (old.get("pass"), old.get("probed_at"), new.get("pass"), new.get("probed_at")))
    changed = 0
    for d, r in (new.get("hosts") or {}).items():
        o = (old.get("hosts") or {}).get(d)
        if not o:
            continue
        was, now = o.get("verdict"), r.get("verdict")
        if was != now:
            changed += 1
            print("  CHANGED %-30s %s -> %s" % (d, was, now))
    print("  %d of %d hosts changed" % (changed, len(new.get("hosts") or {})))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Read a fixed host set with two user agents, before the default changes.")

    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--label", default=None)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        return compare()

    label = args.label or time.strftime("pass-%Y%m%dT%H%M%SZ", time.gmtime())
    print("declared-agent baseline, pass %s, %d hosts, two user agents each" % (label, args.limit))
    print("declared: %s" % AGENT_UA)
    probe = run(args.limit, label)
    store = {}
    if os.path.exists(STORE):
        try:
            with open(STORE) as f:
                store = json.load(f)
        except Exception:
            store = {}
    store.setdefault("question", ("what does the open web answer a declared agent, "
                                  "measured before and after a default changes"))
    store["declared_user_agent"] = AGENT_UA
    store["control_user_agent"] = CONTROL_UA
    store.setdefault("passes", []).append(probe)
    with open(STORE, "w") as f:
        json.dump(store, f, indent=1)
    s = probe["summary"]
    print("stored %d hosts: %d behind Cloudflare, %d ad-marked (%d both); "
          "agent challenged %d, control challenged %d, unreadable %d"
          % (s["hosts"], s["cloudflare_fronted"], s["ad_marked"],
             s["cloudflare_and_ad"], s["agent_challenged"], s["control_challenged"],
             s["unreadable"]))
    print("wrote %s" % STORE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
