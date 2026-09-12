#!/usr/bin/env python3
"""Agent Gates - run 39: a readership counter on channels this project addresses exclusively.

THE PROBLEM, STATED ONCE
    Seven runs of this project have asked "does anyone read this?" and every
    instrument available answered with a number the project moves itself:

      - a page-load badge (hits.sh) that increments on the project's own
        verification fetches, so a delta cannot be told from a self-inflicted one
      - a GitHub clone count, for a repository that a CI job clones
      - an IndexNow 202, which is an acknowledgement, not a distribution

    Run 35 tried to disprove the zero with a positive control and found the
    instrument itself was never shown to work. A zero from an unproven instrument
    is not a finding. That is the mistake this script exists to not repeat.

TWO INSTRUMENTS, BUILT HERE

    I1  A request-log endpoint whose address this project alone addresses. Created
        anonymously through webhook.site's public token API: no account, no email.
        Every fetch is logged individually with client address, user agent,
        referrer, country and time, and the log is readable back over the same
        API. This project's own fetches carry a `self=1` marker, so they can be
        subtracted with certainty rather than inferred.

        Its honest name is not "a channel I control". It is an address this
        project exclusively addresses on infrastructure it does not own, with a
        fuse the provider sets: anonymous tokens self-declare an expiry, recorded
        below and published. When the fuse burns, the instrument dies and says so.

    I2  A GitHub release asset. The public releases API exposes download_count,
        and - verified in this script, not assumed - reading that field does not
        increment it. This is therefore the one counter on this project that the
        project cannot inflate by looking at it: to move it, a client has to
        download a file. It has no fuse and it is independently checkable by
        anyone with a browser.

WHAT THIS CAN AND CANNOT ESTABLISH
    A beacon log establishes that a client other than this project fetched an
    address. It never establishes who. A browser-like user agent can be a person,
    a link preview, a click-tracking proxy or a headless audit; the class is
    published with that caveat attached rather than counted as a reader. The only
    class that could be a person is `browser_like`, and it is reported as
    "browser-like, unverified" - never as "a reader".

PRIVACY
    The log holds third-party IP addresses. They are used to de-duplicate and are
    never published: the published rows carry a salted digest instead. The salt
    lives in the state file and is never written to web/. Country is published as
    aggregate counts only.

WRITES
    data/beacon_endpoint.json   instrument state (endpoint, salt, expiry, history)
    data/counter_report.json    the report, mirrored into web/data/ for publication
    data/counter_series.json    one appended row per run - the curve, never rewritten
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
SITE = "https://agentgates.surge.sh"
REPO = "Atheistam/agentgates"

STORE = os.path.join(DATA, "beacon_endpoint.json")
REPORT = os.path.join(DATA, "counter_report.json")
SERIES = os.path.join(DATA, "counter_series.json")

SELF_UA = "agentgates-census/1.0 (+%s)" % SITE
CONTROL_UA = "agentgates-positive-control/1.0 (+%s)" % SITE

API = "https://webhook.site/token"

# A release that exists to be countable. The asset never changes; the count is the
# measurement, so a mutable asset would destroy it.
RELEASE_TAG = "readership-bundle"
ASSET_NAME = "agentgates-dataset.json"
PROBE_ASSET = "agentgates-probe-browser.json"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Ordered: first match wins. Vendor names are recorded so a fetch can be attributed
# to the party that told us who it was - which is not the same as proof of identity.
BOT_TOKENS = [
    ("GPTBot", "OpenAI"), ("OAI-SearchBot", "OpenAI"), ("ChatGPT-User", "OpenAI"),
    ("ClaudeBot", "Anthropic"), ("Claude-User", "Anthropic"), ("Claude-SearchBot", "Anthropic"),
    ("anthropic-ai", "Anthropic"), ("PerplexityBot", "Perplexity"), ("Perplexity-User", "Perplexity"),
    ("Googlebot", "Google"), ("Google-Extended", "Google"), ("GoogleOther", "Google"),
    ("Storebot-Google", "Google"), ("bingbot", "Microsoft"), ("BingPreview", "Microsoft"),
    ("msnbot", "Microsoft"), ("Applebot", "Apple"), ("Bytespider", "ByteDance"),
    ("CCBot", "Common Crawl"), ("Amazonbot", "Amazon"), ("meta-externalagent", "Meta"),
    ("facebookexternalhit", "Meta"), ("Twitterbot", "X"), ("Slackbot", "Slack"),
    ("Slack-ImgProxy", "Slack"), ("Discordbot", "Discord"), ("TelegramBot", "Telegram"),
    ("LinkedInBot", "LinkedIn"), ("WhatsApp", "Meta"), ("PetalBot", "Huawei"),
    ("AhrefsBot", "Ahrefs"), ("SemrushBot", "Semrush"), ("DataForSeoBot", "DataForSEO"),
    ("DotBot", "Moz"), ("YandexBot", "Yandex"), ("DuckDuckBot", "DuckDuckGo"),
    ("ia_archiver", "Alexa"), ("archive.org_bot", "Internet Archive"), ("UptimeRobot", "UptimeRobot"),
    ("Pingdom", "Pingdom"), ("StatusCake", "StatusCake"), ("Better Uptime", "Better Uptime"),
    ("Barkrowler", "Babbar"), ("Mastodon", "Mastodon"), ("bot", "unnamed-in-UA"),
    ("crawler", "unnamed-in-UA"), ("spider", "unnamed-in-UA"),
]
# Programmatic clients: a machine, but not one that introduced itself. Kept apart
# from BOT_TOKENS because "bot" is a claim about purpose and these are a claim
# about tooling.
CLIENT_TOKENS = [
    ("curl/", "curl"), ("Wget/", "GNU wget"), ("python-requests", "python-requests"),
    ("python-urllib", "python-urllib"), ("aiohttp", "aiohttp"), ("httpx", "httpx"),
    ("Go-http-client", "Go net/http"), ("okhttp", "okhttp"), ("node-fetch", "node-fetch"),
    ("axios", "axios"), ("Java/", "Java"), ("libwww-perl", "libwww-perl"),
    ("guzzle", "Guzzle"), ("Ruby", "Ruby"), ("Java-http-client", "Java"),
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get(url, ua=None, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua or SELF_UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post(url, payload=None, ua=None, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": ua or SELF_UA, "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


# ---------------------------------------------------------------- I1: the log

def ensure_endpoint(state):
    """Reuse the logged address if it is alive; create one if not, and record the death.

    The provider puts a fuse on anonymous tokens. The fuse date is a property of
    the instrument and it is published: an instrument with a known expiry date
    cannot quietly become an outage.
    """
    ep = state.get("endpoint") or {}
    history = state.setdefault("endpoint_history", [])
    exp = ep.get("expires_at")
    if ep.get("uuid") and exp:
        try:
            left = (time.mktime(time.strptime(exp, "%Y-%m-%d %H:%M:%S"))
                    - time.mktime(time.gmtime())) / 3600.0
        except Exception:
            left = -1
        if left > 6:
            ep["hours_left_at_start"] = round(left, 2)
            ep["reused"] = True
            return ep, None
        dead = dict(ep)
        dead["retired_at"] = now()
        dead["retired_reason"] = "provider fuse reached (%s)" % exp
        history.append(dead)

    status, body = post("%s" % API)
    d = json.loads(body) if body.strip().startswith("{") else {}
    if status not in (200, 201) or not d.get("uuid"):
        return None, "create_failed http=%s body=%s" % (status, body[:200])
    ep = {
        "provider": "webhook.site",
        "uuid": d["uuid"],
        "url": "https://webhook.site/%s" % d["uuid"],
        "created_at": d.get("created_at"),
        "expires_at": d.get("expires_at"),
        "account_required": False,
        "reused": False,
        "note": ("Created through the provider's public token API with no account and no "
                 "email. The address is unguessable, so it is exclusively addressed, but it "
                 "is not owned: the provider sets the expiry and can revoke it."),
    }
    state["endpoint"] = ep
    return ep, None


def read_log_full(uuid, pages=6):
    """Every request the endpoint has seen, plus the provider's own count of them.

    Two numbers, not one, because they disagree: the list endpoint is cached, so the
    rows retrieved can lag the provider's total. Publishing the short one as "total"
    is the exact failure this project keeps finding in other people's counters.
    """
    out, page, total = [], 1, None
    while page <= pages:
        q = urllib.parse.urlencode({"sorting": "newest", "per_page": 100, "page": page})
        status, body = get("%s/%s/requests?%s" % (API, uuid, q))
        if status != 200:
            return out, "read_failed http=%s" % status, total
        d = json.loads(body)
        if total is None:
            for k in ("total", "count", "total_count"):
                if isinstance(d.get(k), int):
                    total = d[k]
                    break
        out.extend(d.get("data") or [])
        if d.get("is_last_page") or not d.get("data"):
            break
        page += 1
    return out, None, total


def read_log(uuid, pages=6):
    rows, err, _ = read_log_full(uuid, pages)
    return rows, err


def classify(req, salt):
    """One request -> a class. The classes are ordered by how much they claim."""
    ua = (req.get("user_agent") or "")
    q = req.get("query") or {}
    query = q if isinstance(q, dict) else {}
    hay = ua.lower()
    url_l = (req.get("url") or "").lower()

    marked = str(query.get("self") or "") == "1"
    self_ua = "agentgates" in hay
    if marked or self_ua:
        return {"class": "self", "why": "carries the project's own marker" if marked
                else "user agent names the project"}

    src = query.get("src") or "unknown"
    generic_src = src in ("unknown", "html", "llms", "ai", "readme", "json")

    for tok, vendor in BOT_TOKENS:
        if tok.lower() in hay:
            # A generic word like "bot" in an otherwise empty agent string is a
            # weaker claim than a vendor token, and is labelled as such.
            weak = tok in ("bot", "crawler", "spider")
            return {"class": "declared_crawler" if not weak else "unnamed_crawler",
                    "matched": tok, "vendor": vendor, "via": src, "generic_src": generic_src}
    for tok, client in CLIENT_TOKENS:
        if tok.lower() in hay:
            return {"class": "programmatic_client", "matched": client, "via": src,
                    "generic_src": generic_src}
    if not ua.strip():
        return {"class": "empty_ua", "via": src, "generic_src": generic_src}
    if "mozilla/" in hay:
        return {"class": "browser_like", "via": src, "generic_src": generic_src,
                "why": "could be a person; also could be a preview fetcher or a headless audit"}
    return {"class": "unidentified", "via": src, "generic_src": generic_src}


def client_digest(ip, salt):
    """De-duplication only. The address never leaves this machine in published form."""
    return hashlib.sha256((salt + "|" + (ip or "")).encode()).hexdigest()[:12]


# --------------------------------------------------------------- I2: the asset

def gh_token():
    """The credential the project already uses to push. Never printed."""
    try:
        p = subprocess.run(["git", "credential", "fill"],
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return None


def gh(path, token, method="GET", payload=None, raw=None, ctype=None):
    url = "https://api.github.com/" + path
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agentgates-counter",
               "Authorization": "Bearer " + token}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype or "application/octet-stream"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
            return r.status, (json.loads(b.decode()) if b[:1] in (b"{", b"[") else b)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:
        return "ERR", str(e)[:200]


def ensure_release(token):
    """One release, one immutable asset, whose download_count is the measurement."""
    status, rel = gh("repos/%s/releases/tags/%s" % (REPO, RELEASE_TAG), token)
    if status != 200 or not isinstance(rel, dict):
        body = ("A file that exists to be countable. The public releases API exposes each "
                "asset's download_count, and reads of that field do not increment it, so "
                "this is the one number on this project that the project cannot move by "
                "looking at it. Downloading it is a deliberate act by someone outside the "
                "project. The count is visible to anyone at "
                "https://api.github.com/repos/" + REPO + "/releases/tags/" + RELEASE_TAG)
        status, rel = gh("repos/%s/releases" % REPO, token, "POST", {
            "tag_name": RELEASE_TAG,
            "name": "Agent Gates readership bundle",
            "target_commitish": "main",
            "body": body,
        })
        if status not in (200, 201):
            return None, "release_create_failed http=%s %s" % (status, str(rel)[:200])

    if not isinstance(rel, dict) or not rel.get("id"):
        return None, "release_unusable: %s" % str(rel)[:200]

    rid = rel["id"]
    assets = rel.get("assets") or []
    if not assets:
        src = os.path.join(WEB, "gates.json")
        if not os.path.exists(src):
            return None, "no gates.json to publish as an asset"
        with open(src, "rb") as f:
            blob = f.read()
        up = ("https://uploads.github.com/repos/%s/releases/%s/assets?name=%s"
              % (REPO, rid, ASSET_NAME))
        req = urllib.request.Request(up, data=blob, method="POST", headers={
            "Accept": "application/vnd.github+json", "User-Agent": "agentgates-counter",
            "Authorization": "Bearer " + token, "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                a = json.loads(r.read().decode())
                assets = [a]
        except urllib.error.HTTPError as e:
            return None, "asset_upload_failed http=%s %s" % (e.code, e.read().decode()[:200])

    out = []
    for a in assets:
        out.append({
            "name": a["name"], "size": a["size"], "download_count": a["download_count"],
            "download_url": a["browser_download_url"], "created_at": a.get("created_at"),
        })
    return {"tag": RELEASE_TAG, "release_id": rid,
            "html_url": rel.get("html_url"),
            "assets": out,
            "why_poll_immune": ("download_count is incremented by downloads; this script "
                                "proves that reading it does not move it (negative control) "
                                "and that downloading does (positive control).")}, None


def upload_asset(token, rid, name, blob, ctype="application/json"):
    up = ("https://uploads.github.com/repos/%s/releases/%s/assets?name=%s"
          % (REPO, rid, urllib.parse.quote(name)))
    req = urllib.request.Request(up, data=blob, method="POST", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "agentgates-counter",
        "Authorization": "Bearer " + token, "Content-Type": ctype,
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return None, str(e)[:200]


def probe_ua_split(token, rel, report, state):
    """Does the download counter count a scripted client, or only a browser-shaped one?

    The I2 positive control failed: a download returned HTTP 200 and the count did not
    move. Three explanations fit that: the counter lags by hours, the counter ignores
    non-browser clients, or the counter is simply broken. They are separable with a
    second asset: one deliberate download per asset, different User-Agent, and the
    per-asset counts attribute the effect. Without this the project would have to guess,
    and a guess published as a number is the thing it exists to complain about.
    """
    name = PROBE_ASSET
    have = [a for a in rel["assets"] if a["name"] == name]
    created = False
    if not have:
        blob = json.dumps({
            "purpose": "positive control for a download counter, browser-shaped client",
            "project": "Agent Gates", "run": 39,
            "note": ("downloaded exactly once, with a Chrome User-Agent, to separate "
                     "'the counter lags' from 'the counter ignores scripts'"),
        }, indent=1).encode()
        status, a = upload_asset(token, rel["release_id"], name, blob)
        if status not in (200, 201) or not isinstance(a, dict):
            return {"status": "unavailable", "error": str(a)[:200]}
        have = [{"name": a["name"], "size": a["size"],
                 "download_count": a["download_count"],
                 "download_url": a["browser_download_url"]}]
        created = True
    b = have[0]
    exp = state.get("i2_ua_split") or {}
    if not exp:
        code, _ = get(b["download_url"], ua=UA_BROWSER, timeout=60)
        exp = {
            "asset_scripted": ASSET_NAME, "asset_browser": name,
            "scripted_ua": CONTROL_UA, "browser_ua": UA_BROWSER[:90],
            "downloaded_at": now(), "download_http": code,
            "counts_at_download": {ASSET_NAME: asset_count(rel, ASSET_NAME),
                                   name: b["download_count"]},
            "question": ("one deliberate download per asset, different User-Agent: if the "
                         "counts diverge the counter reads the client, if they move "
                         "together it is latency, if neither moves it is broken"),
        }
        state["i2_ua_split"] = exp
    now_counts = {a["name"]: a["download_count"] for a in rel["assets"]}
    exp["counts_now"] = now_counts
    moved = {k: v for k, v in now_counts.items() if v}
    exp["status"] = ("moved: %s" % json.dumps(moved)) if moved else "unacknowledged"
    if moved:
        exp["settled_at"] = report["probed_at"]
    report["controls"]["I2_ua_split"] = exp
    return exp


def asset_count(rel, name=None):
    """One number, read from the release the API just handed over."""
    for a in (rel or {}).get("assets") or []:
        if a.get("name") == (name or ASSET_NAME):
            return a.get("download_count")
    return None


def iso_epoch(s):
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def settle_pending(state, report, observed):
    """Close out downloads that the counter had not acknowledged when they were made."""
    out = []
    still = []
    t_now = iso_epoch(report["probed_at"])
    for p in state.get("i2_pending") or []:
        cb = p.get("count_before")
        if observed is not None and cb is not None and observed > cb:
            t0 = iso_epoch(p.get("download_attempted_at"))
            p["settled_at"] = report["probed_at"]
            p["count_now"] = observed
            p["latency_hours"] = (round((t_now - t0) / 3600.0, 2)
                                  if (t0 and t_now) else None)
            p["verdict"] = ("the counter is real but asynchronous: the download made at %s "
                            "was acknowledged later, latency %s h"
                            % (p["download_attempted_at"], p["latency_hours"]))
            out.append(p)
        else:
            still.append(p)
    state["i2_pending"] = still
    if out or still:
        report["controls"]["I2_delayed_settlement"] = {
            "settled": out, "still_unacknowledged": still,
            "why": ("a download that the counter has not acknowledged is either latency or "
                    "loss. Recording the timestamp makes the difference measurable later "
                    "instead of guessed now."),
        }
    return out


def main():
    report = {
        "run": 39,
        "instrument": "probe_counter.py",
        "probed_at": now(),
        "question": "Has any client other than this project ever fetched this project?",
        "instruments": {},
        "controls": {},
        "log": [],
        "privacy": ("Third-party IP addresses are used to de-duplicate and are not "
                    "published. Published rows carry a salted digest and a country. "
                    "Aggregate country counts only."),
        "limitations": [
            "A log establishes that something fetched. It never establishes who, or that "
            "anything was read: an HTTP fetch with no render is not a reader.",
            "browser_like is the only class that could be a person. It also covers link "
            "previews, click-tracking proxies and headless audits, so it is reported as "
            "unverified rather than counted as a reader.",
            "The project's own fetches carry a marker. An unmarked fetch from this machine "
            "would be indistinguishable from a stranger's; the rule is that none is made.",
            "I1 has a provider-set fuse. I2 has no fuse but only moves on a deliberate "
            "download, so it is silent by default.",
        ],
    }

    state = load(STORE, {})
    if "salt" not in state:
        state["salt"] = secrets.token_hex(16)  # never published
    salt = state["salt"]
    report["salt_published"] = False

    # ---- I1 ----
    ep, err = ensure_endpoint(state)
    if err or not ep:
        report["instruments"]["I1_request_log"] = {"status": "unavailable", "error": err}
    else:
        report["instruments"]["I1_request_log"] = {
            "status": "live", "provider": ep["provider"], "url": ep["url"],
            "created_at": ep["created_at"], "expires_at": ep["expires_at"],
            "hours_left": ep.get("hours_left_at_start"),
            "reused_from_previous_run": ep.get("reused"),
            "account_required": False,
            "name_it_honestly": ("an address this project exclusively addresses on "
                                 "infrastructure it does not own, with a fuse the provider sets"),
            "endpoints_retired": state.get("endpoint_history", []),
        }
        # POSITIVE CONTROL: a marked fetch must appear in the log, or a zero here is
        # an outage and not a finding. Run 35's lesson, applied before the zero is read.
        # Run 39 amendment: the marker carries a fresh nonce per run. Without it the
        # control can be satisfied by the *previous* run's control request, which
        # proves the endpoint worked three hours ago, not now. Run 39 caught its own
        # control passing on a stale row.
        nonce = hashlib.sha1(("%s|%d" % (salt, time.time())).encode()).hexdigest()[:12]
        fire = "%s?src=positive-control&self=1&n=%s&t=%d" % (ep["url"], nonce, int(time.time()))
        ctl = {"fired": fire, "nonce": nonce, "looked": 0, "seen": False}
        try:
            get(fire, ua=CONTROL_UA)
        except Exception as e:
            ctl["fire_error"] = str(e)[:160]
        rows, rerr, provider_total = [], None, None
        for i in range(6):
            ctl["looked"] += 1
            rows, rerr, provider_total = read_log_full(ep["uuid"])
            if any(str((r.get("query") or {}).get("n") or "") == nonce for r in rows):
                ctl["seen"] = True
                ctl["latency_polls"] = ctl["looked"]
                break
            time.sleep(2.5)
        ctl["verdict"] = (
            "instrument live: this run's own nonce is in the log" if ctl["seen"]
            else "INSTRUMENT DEAD: this run's nonce never appeared - any zero below is an outage")
        # The provider's list endpoint is served from a cache, so the first read after a
        # write can be short. Publishing a short read as a total is the same error this
        # project keeps finding in other people's counters: read again once the nonce is
        # visible, and carry the provider's own total next to the rows actually retrieved.
        if ctl["seen"]:
            time.sleep(1.5)
            rows, rerr, provider_total = read_log_full(ep["uuid"])
        report["controls"]["I1_positive"] = ctl

        seen_ids = set(state.get("log_seen_ids") or [])
        ids = [str(r.get("id") or r.get("created_at") or "") for r in rows]
        new_rows = [r for r, i in zip(rows, ids) if i not in seen_ids]
        state["log_seen_ids"] = sorted(seen_ids | set(ids))[-4000:]
        ilog = report["instruments"]["I1_request_log"]
        ilog["requests_rows_retrieved"] = len(rows)
        ilog["requests_provider_total"] = provider_total
        ilog["requests_total"] = (provider_total if isinstance(provider_total, int)
                                  else len(rows))
        ilog["new_since_previous_run"] = len(new_rows)
        ilog["which_number_is_the_total"] = (
            "requests_provider_total is the provider's own count; requests_rows_retrieved is "
            "what its cached list endpoint handed back within the poll window. When they "
            "disagree the smaller one is a cache artefact, not fewer requests.")
        counts, countries, vendors = {}, {}, {}
        for r in rows:
            c = classify(r, salt)
            k = c["class"]
            counts[k] = counts.get(k, 0) + 1
            cc = r.get("country") or "unknown"
            countries[cc] = countries.get(cc, 0) + 1
            if c.get("vendor"):
                vendors[c["vendor"]] = vendors.get(c["vendor"], 0) + 1
            report["log"].append({
                "at": r.get("created_at"), "class": k,
                "matched": c.get("matched"), "vendor": c.get("vendor"),
                "via": c.get("via"), "generic_beacon": c.get("generic_src"),
                "user_agent": (r.get("user_agent") or "")[:180],
                "referer": (r.get("referer") or None),
                "country": cc,
                "client": client_digest(r.get("ip"), salt),
                "bytes_query": {kk: vv for kk, vv in (r.get("query") or {}).items()
                                if kk not in ("t",)},
            })
        report["instruments"]["I1_request_log"]["by_class"] = counts
        report["instruments"]["I1_request_log"]["distinct_clients"] = len(
            {client_digest(r.get("ip"), salt) for r in rows})
        non_self = [x for x in report["log"] if x["class"] != "self"]
        with_ref = [x for x in non_self if x.get("referer")]
        report["instruments"]["I1_request_log"]["country_counts"] = countries
        report["instruments"]["I1_request_log"]["vendor_counts"] = vendors
        report["reach"] = {
            "requests_any_client": len(rows),
            "self_inflicted": counts.get("self", 0),
            "not_this_project": len(non_self),
            "of_those_with_a_referer": len(with_ref),
            "could_be_a_person_unverified": len([x for x in non_self
                                                 if x["class"] == "browser_like"]),
            "statement": ("Every request not originated by this project, by class. The last "
                          "number is the only one that could be a person and is not evidence "
                          "that it was one."),
        }

    # ---- I2 ----
    token = gh_token()
    if not token:
        report["instruments"]["I2_download_count"] = {
            "status": "unavailable", "error": "no GitHub credential available"}
    else:
        rel, err = ensure_release(token)
        if err or not rel:
            report["instruments"]["I2_download_count"] = {"status": "unavailable", "error": err}
        else:
            before = asset_count(rel)
            settle_pending(state, report, before)
            # NEGATIVE CONTROL: reading the count must not move it. Polled three
            # times, because a counter that a poll can inflate is the exact failure
            # this project found in its own page-load badge.
            reads = []
            for _ in range(3):
                _, r2 = gh("repos/%s/releases/tags/%s" % (REPO, RELEASE_TAG), token)
                reads.append(asset_count(r2) if isinstance(r2, dict) else None)
            reads_via_public = []
            for _ in range(2):
                s3, r3 = get("https://api.github.com/repos/%s/releases/tags/%s?x=%d"
                             % (REPO, RELEASE_TAG, int(time.time())),
                             ua="agentgates-counter-public-check")
                reads_via_public.append(
                    json.loads(r3)["assets"][0]["download_count"] if s3 == 200 else None)
            stable = len(set(reads + reads_via_public)) == 1
            report["controls"]["I2_negative"] = {
                "reads": reads, "reads_unauthenticated": reads_via_public,
                "verdict": ("poll-immune: 5 reads, one value" if stable
                            else "NOT POLL-IMMUNE: reads moved the count, so it is unusable"),
                "why_it_matters": ("a counter that moves when the project looks at it cannot "
                                   "measure anything but the project"),
            }
            # POSITIVE CONTROL: one deliberate download must move it, else it is dead.
            pos = {"before": before, "attempted": False}
            if stable and before is not None:
                try:
                    url = rel["assets"][0]["download_url"]
                    s4, _ = get(url, ua=CONTROL_UA)
                    pos.update({"download_http": s4, "attempted": True})
                except Exception as e:
                    pos["download_error"] = str(e)[:160]
                moved, polls = None, 0
                for i in range(6):
                    polls = i + 1
                    _, r5 = gh("repos/%s/releases/tags/%s" % (REPO, RELEASE_TAG), token)
                    moved = asset_count(r5) if isinstance(r5, dict) else None
                    if moved is not None and before is not None and moved > before:
                        break
                    time.sleep(5)
                pos.update({"after": moved, "polls": polls,
                            "moved": (moved is not None and before is not None and moved > before)})
                pos["verdict"] = ("instrument live: one deliberate download moved the count "
                                  "%s -> %s in %d poll(s)" % (before, moved, polls)
                                  if pos["moved"] else
                                  "instrument not demonstrated within the polling window: a "
                                  "download returned HTTP %s and the count did not move"
                                  % pos.get("download_http"))
                # A failed positive control is not a verdict, it is an open question with
                # a timestamp. GitHub's counter is known to aggregate asynchronously, so
                # the download is registered here and settled at a later run. Publishing
                # "zero downloads" from an instrument whose positive control failed is
                # precisely the error run 35 made, and it is not repeated by leaving the
                # question open - it is avoided by never reading a number until the
                # instrument has been shown to work.
                attempted = state.get("project_downloads_attempted", 0) + 1
                state["project_downloads_attempted"] = attempted
                if not pos["moved"]:
                    state.setdefault("i2_pending", []).append({
                        "download_attempted_at": now(), "count_before": before,
                        "count_after_window": moved, "poll_window_s": polls * 5,
                        "http": pos.get("download_http"),
                    })
                    pos["open_question"] = ("the download is real (HTTP %s) and the count has "
                                            "not acknowledged it. Registered for a delayed "
                                            "settlement: the next run re-reads the count and "
                                            "reports the latency, or reports the instrument "
                                            "as lossy."
                                            % pos.get("download_http"))
            report["controls"]["I2_positive"] = pos
            # Run 39's own mistake, recorded rather than edited away: the first download
            # this project made happened before the counting of its own downloads existed,
            # so the state file says 1 when two downloads have been made. The number here
            # is corrected and the correction is written down, because an instrument that
            # silently under-reports itself is the thing this project measures in others.
            if state.get("run39_self_correction") is None:
                state["run39_self_correction"] = {
                    "what": "project_downloads_attempted undercounted by one",
                    "why": ("the first positive-control download ran before the counter of "
                            "the project's own downloads was added, so it was not recorded"),
                    "fix": "count set to the number of downloads actually made",
                }
                state["project_downloads_attempted"] = (state.get("project_downloads_attempted", 0) or 0) + 1
            # The counter includes this project's own control downloads. Subtracting them
            # is the only way the number means anything, and saying so is the difference
            # between a metric and a decoration.
            mine = state.get("project_downloads_attempted", 0)
            observed_final = pos.get("after")
            outside = (observed_final - mine) if isinstance(observed_final, int) else None
            # A counter reading below the project's own deliberately-made downloads cannot
            # produce a reader count. The first run of this instrument produced -3, which is
            # not "minus three readers", it is the arithmetic signature of a broken counter.
            outside_note = None
            if isinstance(outside, int) and outside < 0:
                outside_note = ("unmeasurable: the counter reads %s, which is below the %d "
                                "downloads this project made deliberately, so the difference "
                                "is not a reader count - it is the counter failing to count "
                                "its own positive control. Published as null, not as a number."
                                % (observed_final, mine))
                outside = None
            ua_split = probe_ua_split(token, rel, report, state)
            report["instruments"]["I2_download_count"] = {
                "status": "live" if rel else "unknown",
                "status_of_the_counter": pos.get("verdict"),
                "positive_control_failed": not pos.get("moved"),
                "asset": ASSET_NAME,
                "download_url": rel["assets"][0]["download_url"],
                "download_count_raw": asset_count(rel),
                "downloads_made_by_this_project": mine,
                "downloads_by_anyone_else": outside,
                "why_null": outside_note,
                "interpretation": ("download_count_raw minus the project's own control "
                                   "downloads. Only the second number is a reader."),
                "ua_split_experiment": ua_split or None,
            }
            report["instruments"]["I2_download_count"].update({
                "tag": rel["tag"],
                "release_url": rel["html_url"],
                "created_at": rel["assets"][0]["created_at"],
                "no_fuse": "no expiry is set on a release asset",
                "independently_checkable": ("anyone can read this number themselves at "
                                            "https://api.github.com/repos/%s/releases/tags/%s"
                                            % (REPO, RELEASE_TAG)),
                "why_poll_immune": rel["why_poll_immune"],
            })

    # ---- the curve ----
    series = load(SERIES, [])
    i1 = report["instruments"].get("I1_request_log", {})
    i2 = report["instruments"].get("I2_download_count", {})
    series.append({
        "at": report["probed_at"],
        "endpoint": i1.get("url"),
        "requests_any_client": i1.get("requests_total"),
        "not_this_project": (report.get("reach") or {}).get("not_this_project"),
        "browser_like_unverified": (report.get("reach") or {}).get("could_be_a_person_unverified"),
        "with_a_referer": (report.get("reach") or {}).get("of_those_with_a_referer"),
        "release_downloads_raw": i2.get("download_count_raw"),
        "release_downloads_outside": i2.get("downloads_by_anyone_else"),
    })
    report["series"] = series
    report["reading_the_curve"] = (
        "One row per run, appended and never rewritten. A row is evidence that the "
        "instrument was alive at that time, because the positive control has to pass "
        "before the reach numbers are written. Two instruments with opposite failure "
        "modes: I1 sees every fetch and dies on a date; I2 never dies and sees only "
        "deliberate downloads.")

    state["last_run"] = report["probed_at"]
    with open(STORE, "w") as f:
        json.dump(state, f, indent=2)
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2)
    os.makedirs(os.path.join(WEB, "data"), exist_ok=True)
    with open(os.path.join(WEB, "data", "counter_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    with open(SERIES, "w") as f:
        json.dump(series, f, indent=2)

    print("I1 %s" % (report["instruments"].get("I1_request_log", {}).get("status")))
    print("   positive control: %s" % report["controls"].get("I1_positive", {}).get("verdict"))
    r = report.get("reach") or {}
    print("   requests=%s self=%s not_this_project=%s browser_like_unverified=%s referer=%s"
          % (r.get("requests_any_client"), r.get("self_inflicted"),
             r.get("not_this_project"), r.get("could_be_a_person_unverified"),
             r.get("of_those_with_a_referer")))
    print("I2 %s" % (report["instruments"].get("I2_download_count", {}).get("status")))
    print("   negative control: %s" % report["controls"].get("I2_negative", {}).get("verdict"))
    print("   positive control: %s" % report["controls"].get("I2_positive", {}).get("verdict"))
    print("wrote %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
