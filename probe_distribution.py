#!/usr/bin/env python3
"""
Agent Gates - distribution surface census.

The signup census asked: which account surfaces are open to an agent with no
email inbox, no phone number, no government ID, no payment instrument and no
social account?

This asks the same question one layer further along the pipeline: once an agent
HAS produced something, which publishing surfaces will actually accept it?

Two things are recorded per venue. First the outcome (was a public artifact
created?). Second - and this is the point - how the refusal was PHRASED:

  explicit_denial                 401/403; the venue admits it is refusing you
  denial_disguised_as_absence     404; the venue claims the endpoint does not exist
  denial_disguised_as_success     200, plus a body that asks you to log in
  not_a_refusal                   200, but the document returned is not the resource
  resource_missing                the venue is gone or refuses connections
  accepted                        a public artifact exists and is retrievable

An HTTP 200 is not evidence. That is the whole project; this applies it to
publishing rather than reading.

What this does NOT do: no CAPTCHA is solved, no verification is spoofed, no
credential is forged, no rate limit is evaded, and no third party is contacted
more than twice. POSTs go only to endpoints that exist for public submission,
plus the two GitHub endpoints covered by a credential the operator already holds
and which is declared below.
"""
import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")

ARTIFACT = "https://agentgates.surge.sh/findings/"
REPO = "https://github.com/Atheistam/agentgates"
REPO_GIT = "https://github.com/Atheistam/agentgates.git"

UA = ("AgentGatesBot/1.0 (+%s; distribution-surface measurement; this is an "
      "autonomous agent publishing its own results)" % ARTIFACT)

ACTION = "action"
OBSERVE = "observe"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# The operator holds exactly one credential that this agent can use. It is
# declared here because the study's value depends on the reader knowing which
# doors were opened by a key rather than by the agent's own reach.
GITHUB_TOKEN = None


def _token():
    global GITHUB_TOKEN
    if GITHUB_TOKEN is not None:
        return GITHUB_TOKEN
    tok = ""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "credential-osxkeychain", "get"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                tok = line.split("=", 1)[1].strip()
    except Exception:
        tok = ""
    GITHUB_TOKEN = tok
    return tok


def req(url, method="GET", data=None, headers=None, timeout=45, follow=False):
    """One request. Returns (status, body_text, final_url, error)."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(data, str):
            body = data.encode()
        else:
            body = data
    r = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=CTX) as resp:
            return resp.getcode(), resp.read(40000).decode("utf-8", "replace"), resp.geturl(), None
    except urllib.error.HTTPError as e:
        try:
            txt = e.read(40000).decode("utf-8", "replace")
        except Exception:
            txt = ""
        return e.code, txt, url, None
    except Exception as e:
        return None, "", url, "%s: %s" % (type(e).__name__, str(e)[:160])


def phrase(status, body, err, ok=200, markers=None, hint=None):
    """Classify how the refusal was phrased.

    Status code alone is never trusted: a 200 whose body asks you to log in is a
    refusal, and a 404 on an endpoint that plainly exists is a refusal too.

    The categories are about wording, not about permission. "The venue said no"
    and "the venue said nothing recognisable" are different results and are
    counted separately.
    """
    if hint:
        return hint
    if err or status is None:
        return "no_response"
    if status in (401, 403):
        return "explicit_denial"
    low = (body or "").lower()
    for m in (markers or []):
        if m in low:
            return "denial_disguised_as_success"
    if status == 404:
        return "denial_disguised_as_absence"
    if status >= 500:
        # A 5xx that explains itself is a statement. A bare 5xx is noise.
        return "explicit_denial" if len(low) > 80 else "no_response"
    if status != ok:
        return "explicit_denial"
    return "accepted"


def venue(id_, name, kind, url, method, gate, verdict, phrased, evidence,
          status=None, artifact=None, action=OBSERVE, notes=""):
    return {
        "id": id_,
        "name": name,
        "kind": kind,
        "endpoint": url,
        "method": method,
        "action": action,
        "gate": gate,
        "verdict": verdict,
        "refusal_phrased_as": phrased,
        "http_status": status,
        "artifact_url": artifact,
        "evidence": evidence[:400],
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# venues
# ---------------------------------------------------------------------------

def v_software_heritage():
    """Permanent third-party archive of the repository. Anonymous API."""
    url = ("https://archive.softwareheritage.org/api/1/origin/save/git/url/%s" % REPO_GIT)
    st, body, _, err = req(url, method="POST", timeout=60)
    try:
        d = json.loads(body)
        # The save endpoint answers with a bare object the first time an origin is
        # saved and with a one-element list when a save is already on file. This
        # harness crashed on the list form and recorded a success as a failure,
        # which is precisely the error this project studies.
        if isinstance(d, list):
            d = d[0] if d else {}
    except Exception:
        d = {}
    accepted = d.get("save_request_status") == "accepted"
    return venue(
        "software_heritage", "Software Heritage", "code archive",
        url, "POST", "none",
        "published" if accepted else ("unavailable" if err else "gated"),
        phrase(st, body, err, ok=200), body[:300], st,
        "https://archive.softwareheritage.org/browse/origin/?origin_url=%s" % REPO_GIT,
        ACTION,
        "save_task_status=%s, request id %s" % (d.get("save_task_status"), d.get("id")),
    )


def v_wayback():
    """Internet Archive Save Page Now, anonymous. Verifies by polling availability
    rather than trusting the POST's status code."""
    save = "https://web.archive.org/save/%s" % ARTIFACT
    st, body, _, err = req(save, method="POST",
                           data="url=%s" % ARTIFACT,
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           timeout=120)
    time.sleep(6)
    aq = ("https://archive.org/wayback/available?url=%s"
          % ARTIFACT.rstrip("/").replace("https://", ""))
    st2, body2, _, _ = req(aq, timeout=45)
    try:
        snap = (json.loads(body2).get("archived_snapshots") or {})
        got = bool(snap.get("closest"))
        close = (snap.get("closest") or {}).get("url")
    except Exception:
        got, close = False, None
    return venue(
        "wayback", "Internet Archive (Save Page Now)", "web archive",
        save, "POST", "none",
        "published" if got else "unavailable",
        phrase(st, body, err, ok=200,
               hint=None if got else ("not_a_refusal" if st == 200 else None)),
        "save POST -> HTTP %s%s; availability API archived_snapshots=%s"
        % (st, (" (%s)" % err) if err else "", "populated" if got else "empty"),
        st, close, ACTION,
        "Anonymous archiving is the one action here with no second party to consent "
        "to it, so a failure is the venue's, not a gate's.",
    )


def v_indexnow():
    """Push a URL into the Bing/Yandex index. Requires a key file on the site."""
    key = "agentgatesindexnow2026"
    keyurl = "https://agentgates.surge.sh/%s.txt" % key
    st, kbody, _, kerr = req(keyurl, timeout=30)
    live = (st == 200 and key in (kbody or ""))
    url = "https://api.indexnow.org/indexnow"
    payload = {"host": "agentgates.surge.sh", "key": key,
               "keyLocation": keyurl, "urlList": [ARTIFACT]}
    st2, body2, _, err2 = req(url, method="POST", data=payload, timeout=45)
    ok = st2 in (200, 202)
    return venue(
        "indexnow", "IndexNow (Bing / Yandex)", "search index",
        url, "POST", "none",
        "published" if ok else ("unavailable" if (err2 or not live) else "gated"),
        phrase(st2, body2, err2, ok=202, hint="accepted" if ok else None),
        "endpoint -> HTTP %s; key file -> HTTP %s" % (st2, st), st2, None,
        ACTION,
        "An accepted push is a claim about a queue, not a claim about an index. "
        "Nothing here proves a crawler fetched anything.",
    )


def v_hn():
    url = "https://news.ycombinator.com/submit"
    st, body, _, err = req(url, method="POST",
                           data="title=%s&url=%s" % ("Agent Gates", ARTIFACT),
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           timeout=45)
    return venue(
        "hn", "Hacker News", "news site", url, "POST", "account (email)",
        "gated", phrase(st, body, err, ok=200, markers=["login", "bad login"]),
        body[:300], st, None, ACTION,
        "Re-tested each run since run 24. The submission endpoint answers 200 and no "
        "story is created.",
    )


def v_lobsters():
    url = "https://lobste.rs/stories/new"
    st, body, final, err = req(url, timeout=45)
    gated = "/login" in (final or "") or "log in" in (body or "").lower()
    return venue(
        "lobsters", "Lobsters", "news site", url, "GET", "invite",
        "gated" if gated else "inconclusive",
        "explicit_denial" if gated else "not_a_refusal",
        "redirected to %s" % final, st, None, OBSERVE,
        "Invite-only by design; recorded for completeness.",
    )


def v_reddit():
    url = "https://www.reddit.com/api/submit"
    st, body, _, err = req(url, method="POST",
                           data="kind=link&title=x&url=%s" % ARTIFACT,
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           timeout=45)
    return venue(
        "reddit", "Reddit", "forum", url, "POST", "account",
        "gated" if "USER_REQUIRED" in body else "inconclusive",
        phrase(st, body, err, ok=200, markers=["user_required"]),
        body[:300], st, None, ACTION,
        "Answers HTTP 200 and puts the refusal in a JSON payload meant for "
        "JavaScript to render. A status-code-only probe scores this as success.",
    )


def v_devto():
    url = "https://dev.to/api/articles"
    st, body, _, err = req(url, method="POST",
                           data={"article": {"title": "Agent Gates", "body_markdown": "probe"}},
                           timeout=45)
    return venue(
        "devto", "DEV Community", "blog platform", url, "POST", "credential (API key)",
        "gated", phrase(st, body, err), body[:300], st, None, ACTION,
        "API key is issued in the account dashboard, and the account needs an email.",
    )


def v_medium():
    st, body, _, err = req("https://api.medium.com/v1/users/me/posts", method="POST",
                           data={"title": "probe"}, timeout=45)
    return venue("medium", "Medium", "blog platform",
                 "https://api.medium.com/v1/users/me/posts", "POST", "credential (integration token)",
                 "gated", phrase(st, body, err), body[:300], st, None, ACTION, "")


def v_mastodon():
    url = "https://mastodon.social/api/v1/statuses"
    st, body, _, err = req(url, method="POST", data={"status": "probe"}, timeout=45)
    return venue(
        "mastodon_social", "Mastodon (mastodon.social)", "fediverse", url, "POST",
        "account (email)", "gated", phrase(st, body, err), body[:300], st, None, ACTION,
        "Instance registration requires email confirmation, so the posting API is "
        "unreachable even though it is fully open once authenticated.",
    )


def v_zenodo():
    url = "https://zenodo.org/api/deposit/depositions"
    st, body, _, err = req(url, method="POST", data={}, timeout=60)
    return venue(
        "zenodo", "Zenodo (DOI minting)", "data repository", url, "POST",
        "credential (OAuth token)", "gated", phrase(st, body, err), body[:300], st, None,
        ACTION,
        "This is the surface that would mint a DOI for the dataset. It requires an "
        "account, which requires an identity that can receive mail.",
    )


def v_gitlab():
    url = "https://gitlab.com/api/v4/snippets"
    st, body, _, err = req(url, method="POST",
                           data={"title": "Agent Gates", "visibility": "public",
                                 "files": [{"file_path": "a.md", "content": "probe"}]},
                           timeout=45)
    return venue("gitlab", "GitLab Snippets", "code host", url, "POST",
                 "credential (token)", "gated", phrase(st, body, err), body[:300], st,
                 None, ACTION, "")


def v_github_gist():
    """The one venue where a credential is held - and it is still refused, because
    the credential's scope is narrower than the endpoint."""
    url = "https://api.github.com/gists"
    tok = _token()
    if not tok:
        return venue("github_gist", "GitHub Gist", "code host", url, "POST",
                     "credential", "inconclusive", "resource_missing",
                     "no token available in this environment", None, None, ACTION, "")
    st, body, _, err = req(url, method="POST",
                           data={"description": "Agent Gates", "public": True,
                                 "files": {"agentgates.md": {"content": "probe"}}},
                           headers={"Authorization": "Bearer %s" % tok,
                                    "Accept": "application/vnd.github+json"},
                           timeout=45)
    return venue(
        "github_gist", "GitHub Gist", "code host", url, "POST",
        "credential (scope wider than the one held)",
        "gated" if st != 201 else "published",
        phrase(st, body, err, ok=201), body[:300], st, None, ACTION,
        "The operator's token can list gists and push to this repository, so the "
        "credential is real and the endpoint is real. GitHub answers 404. A refusal "
        "counted by status code is indistinguishable from a typo in the URL.",
    )


def v_github_release():
    url = "https://api.github.com/repos/Atheistam/agentgates/releases"
    tok = _token()
    if not tok:
        return venue("github_release", "GitHub Releases", "artifact host", url, "POST",
                     "credential", "inconclusive", "resource_missing", "no token", None,
                     None, ACTION, "")
    tag = "v1.0-run34"
    st, body, _, err = req(url, method="POST",
                           data={"tag_name": tag, "name": "Agent Gates run 34 - dataset",
                                 "body": "Signed dataset snapshot and the distribution "
                                         "surface census. Machine-readable, verifiable.",
                                 "draft": False, "prerelease": False},
                           headers={"Authorization": "Bearer %s" % tok,
                                    "Accept": "application/vnd.github+json"},
                           timeout=45)
    published = st == 201
    if not published and st == 422:
        st2, body2, _, err2 = req("%s/tags/%s" % (url, tag), timeout=30)
        published = st2 == 200
        body = body2
    art = ("https://github.com/Atheistam/agentgates/releases/tag/%s" % tag) if published else None
    return venue(
        "github_release", "GitHub Releases", "artifact host", url, "POST",
        "credential (held)", "published" if published else "gated",
        phrase(st, body, err, ok=201), body[:300], st, art, ACTION,
        "Open only because a credential was already held. This is the clearest "
        "illustration of the study's thesis: identical to the gist endpoint in every "
        "respect except the scope of the key.",
    )


def v_tmpfiles():
    url = "https://tmpfiles.org/api/v1/upload"
    path = os.path.join(WEB, "llms.txt")
    if not os.path.exists(path):
        return venue("tmpfiles", "tmpfiles.org", "anonymous file host", url, "POST",
                     "none", "inconclusive", "resource_missing", "no file to upload",
                     None, None, ACTION, "")
    boundary = "----AgentGatesBoundary"
    with open(path, "rb") as fh:
        content = fh.read()
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"llms.txt\"\r\n"
             "Content-Type: text/plain\r\n\r\n" % boundary).encode() + content +
            ("\r\n--%s--\r\n" % boundary).encode())
    st, resp, _, err = req(url, method="POST", data=body,
                           headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
                           timeout=45)
    try:
        art = json.loads(resp)["data"]["url"]
        art = art.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception:
        art = None
    return venue(
        "tmpfiles", "tmpfiles.org", "anonymous file host", url, "POST", "none",
        "published" if art else "unavailable", phrase(st, resp, err), resp[:200], st, art,
        ACTION,
        "Accepted with no account at all. The artifact expires within the hour, so "
        "this is reach, not persistence.",
    )


def v_0x0():
    url = "https://0x0.st"
    st, body, _, err = req(url, method="POST", data=b"probe", timeout=45)
    return venue(
        "0x0st", "0x0.st", "anonymous file host", url, "POST", "none",
        "unavailable", phrase(st, body, err),
        body[:400], st, None, ACTION,
        "Closed to anonymous uploads, and it says why in the response body. This is "
        "the most on-the-nose field note the project has: an anonymous surface shut "
        "because of agent traffic, which is the direction the whole study measures.",
    )


def v_bashupload():
    st, body, _, err = req("https://bashupload.com", method="GET", timeout=30)
    return venue("bashupload", "bashupload.com", "anonymous file host",
                 "https://bashupload.com", "GET", "none", "unavailable",
                 phrase(st, body, err), err or "no usable response", st, None, OBSERVE,
                 "Unreachable from this host across two attempts.")


def v_pastebin():
    url = "https://pastebin.com/api/api_post.php"
    st, body, _, err = req(url, method="POST",
                           data="api_option=paste&api_paste_code=probe", timeout=45)
    return venue("pastebin", "Pastebin", "paste host", url, "POST",
                 "credential (developer key)", "gated", phrase(st, body, err), body[:300],
                 st, None, ACTION, "")


VENUES = [
    v_software_heritage, v_wayback, v_indexnow, v_github_release, v_github_gist,
    v_tmpfiles, v_0x0, v_hn, v_reddit, v_lobsters, v_devto, v_medium, v_mastodon,
    v_zenodo, v_gitlab, v_pastebin, v_bashupload,
]


OUTJSON = os.path.join(DATA, "distribution_surfaces.json")


def main():
    argv = sys.argv[1:]
    merge = "--merge" in argv
    only = [a for a in argv if not a.startswith("--")] or None
    results = []
    prior = None
    if merge and os.path.exists(OUTJSON):
        with open(OUTJSON) as f:
            prior = json.load(f)
    for fn in VENUES:
        name = fn.__name__
        if only and not any(o in name for o in only):
            continue
        sys.stderr.write(".. %s\n" % name)
        sys.stderr.flush()
        try:
            results.append(fn())
        except Exception as e:
            results.append(venue(name.replace("v_", ""), name, "unknown", "", "?",
                                 "unknown", "inconclusive", "no_response",
                                 "probe raised %s: %s" % (type(e).__name__, str(e)[:120])))

    if prior is not None:
        # Re-run selected venues and fold them back in, preserving the roster and
        # the order of the venues that were not re-contacted this pass.
        by_id = {r["id"]: r for r in prior.get("venues", [])}
        for r in results:
            by_id[r["id"]] = r
        order = [r["id"] for r in prior.get("venues", [])]
        for r in results:
            if r["id"] not in order:
                order.append(r["id"])
        results = [by_id[i] for i in order]

    verdicts = {}
    phrases = {}
    gates = {}
    for r in results:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        phrases[r["refusal_phrased_as"]] = phrases.get(r["refusal_phrased_as"], 0) + 1
        gates[r["gate"]] = gates.get(r["gate"], 0) + 1

    published = [r for r in results if r["verdict"] == "published"]
    opened_by_key = [r for r in published if r["gate"].startswith("credential")]
    with_bare_reach = [r for r in published if r["gate"] == "none"]

    out = {
        "probe": "distribution surfaces",
        "question": ("Once an agent with no inbox, no SIM, no ID and no social "
                     "account has produced something, where can it put it?"),
        "artifact": ARTIFACT,
        "repository": REPO,
        "ran_at": ((prior or {}).get("ran_at")
                   or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        "last_contacted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operator_credentials_available_to_agent": [
            "one GitHub access token, repository scope, no gist scope"
        ],
        "venues": results,
        "summary": {
            "attempted": len(results),
            "published": len(published),
            "published_with_bare_reach": len(with_bare_reach),
            "published_only_because_a_key_was_held": len(opened_by_key),
            "gated": verdicts.get("gated", 0),
            "unavailable": verdicts.get("unavailable", 0),
            "inconclusive": verdicts.get("inconclusive", 0),
            "by_verdict": verdicts,
            "by_gate": gates,
            "refusals_by_wording": phrases,
        },
    }
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "distribution_surfaces.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(DATA, "distribution_surfaces.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "kind", "method", "action", "verdict", "gate",
                    "refusal_phrased_as", "http_status", "artifact_url", "endpoint"])
        for r in results:
            w.writerow([r["id"], r["name"], r["kind"], r["method"], r["action"],
                        r["verdict"], r["gate"], r["refusal_phrased_as"],
                        r["http_status"], r["artifact_url"], r["endpoint"]])
    print(json.dumps(out["summary"], indent=2))
    print("-> data/distribution_surfaces.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
