#!/usr/bin/env python3
"""Persistent identifier probe: does this project have a name that outlives its host?

Earlier tranches checked whether an agent can *reach* a surface. This one asks a
different question: can an agent be *named* by a system that does not depend on its
own domain, its own account, or its own uptime?

Software Heritage is the one such system found so far that requires no account. It
keys origins by URL, and the keying is stricter than it looks: the clone URL and the
browser URL are different origins, and only one of them is in the archive. That
distinction is recorded here because a query with the wrong key returns a 404 that
is indistinguishable from "this project does not exist".

It also records the distance between the archived revision and the repository HEAD,
because a resolving identifier proves integrity, not currency.
"""
import json
import hashlib
import os
import subprocess
import sys
import urllib.error
import urllib.request
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "persistent_identifiers.json")

REPO_WEB = "https://github.com/Atheistam/agentgates"
REPO_CLONE = REPO_WEB + ".git"
UA = {"User-Agent": "AgentGatesBot/1.0 (+https://agentgates.surge.sh; research probe)"}
API = "https://archive.softwareheritage.org/api/1/"


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return None, {"error": type(e).__name__ + ": " + str(e)[:200]}


def git(*args):
    try:
        return subprocess.check_output(["git"] + list(args), cwd=HERE,
                                      stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def main():
    res = {"probed_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "archive": "Software Heritage", "gate": "none",
           "origin_keying_note": (
               "Software Heritage keys this project by the clone URL, not the browser URL. "
               "%s (no .git) returns 404 on every origin endpoint: same repository, two URLs, "
               "one of them not in the archive. Query the wrong one and the archive tells you "
               "the project does not exist." % REPO_WEB)}

    # Both keys, so the distinction is evidence rather than assertion.
    res["keying_check"] = {}
    for key in (REPO_WEB, REPO_CLONE):
        st, body = get("%sorigin/%s/get/" % (API, key))
        res["keying_check"]["without_.git" if key == REPO_WEB else "with_.git"] = {
            "url": key, "http_status": st,
            "found": isinstance(body, dict) and "origin_visits_url" in body,
        }

    st, org = get("%sorigin/%s/get/" % (API, REPO_CLONE))
    res["origin_http_status"] = st
    if isinstance(org, dict) and org.get("url"):
        res["origin_keyed_as"] = org.get("url")
        # An origin's SWHID is sha1 of the URL it is keyed by, not the last path
        # segment. Deriving it by hand produced "swh:1:ori:agentgates.git" on the
        # first run of this probe; the archive and the checksum are the authorities.
        res["origin_swhid"] = "swh:1:ori:" + hashlib.sha1(
            org["url"].encode("utf-8")).hexdigest()
        res["origin_swhid_derived_from"] = org["url"]
        # And ask the archive itself. The authority endpoint URL is *addressed by*
        # the origin SWHID -- so a 200 there means SWH routes requests using exactly
        # this identifier, which is stronger than any echo this probe could parse.
        auth = org.get("metadata_authorities_url") or ""
        res["origin_swhid_echoed_in"] = auth or None
        if auth:
            st2, a = get(auth)
            res["origin_authority_status"] = st2
            res["origin_authority_body"] = a if isinstance(a, (list, dict)) else None
            res["origin_swhid_matches_authority"] = bool(
                res["origin_swhid"] in auth and st2 == 200)

    st, visit = get("%sorigin/%s/visit/latest/" % (API, REPO_CLONE))
    res["visit_latest_http_status"] = st
    if isinstance(visit, dict) and visit.get("status"):
        res["visit"] = {"number": visit.get("visit"), "date": visit.get("date"),
                        "status": visit.get("status"), "type": visit.get("type")}
        snap = visit.get("snapshot")
        if snap:
            bare = snap.split(":")[-1]
            if not snap.startswith("swh:"):
                snap = "swh:1:snp:" + snap
            res["snapshot_swhid"] = snap
            # The API addresses snapshots by bare hash, not by the prefixed SWHID:
            # /api/1/snapshot/swh:1:snp:<hash>/ returns 404 (raw and percent-encoded
            # alike). The prefixed form is the identifier; the bare form is the
            # address. Publishing only one of the two hands a reader a 404 on either
            # the identifier or the resolver, depending on which they guessed.
            res["snapshot_api_address"] = "%ssnapshot/%s/" % (API, bare)
            res["snapshot_address_is_bare_hash"] = True
            st3, snp = get(res["snapshot_api_address"])
            res["snapshot_http_status"] = st3
            st_p, _ = get("%ssnapshot/%s/" % (API, snap))
            res["snapshot_prefixed_http_status"] = st_p
            if isinstance(snp, dict):
                branches = snp.get("branches") or {}
                main = branches.get("refs/heads/main") or {}
                target = main.get("target")
                res["snapshot_branches"] = len(branches)
                if target:
                    st4, rev = get("%srevision/%s/" % (API, target))
                    if isinstance(rev, dict) and rev.get("id"):
                        res["archived_revision"] = {
                            "sha": rev["id"], "date": rev.get("date"),
                            "message": (rev.get("message") or "").splitlines()[0][:120]}
                        res["archived_revision_http_status"] = st4

    # Integrity is not currency: put the archive's revision next to HEAD, in the
    # artifact itself, so no reader has to take this on trust.
    head_sha = git("rev-parse", "HEAD")
    head_date = git("log", "-1", "--format=%cI")
    res["current_head_at_probe"] = {"sha": head_sha, "date": head_date}
    arch = (res.get("archived_revision") or {}).get("sha")
    if arch and head_sha:
        try:
            res["archive_lag_commits"] = int(git("rev-list", "--count",
                                                 "%s..%s" % (arch, head_sha)) or -1)
        except Exception:
            res["archive_lag_commits"] = None
        res["archived_revision_is_ancestor_of_head"] = bool(
            git("merge-base", "--is-ancestor", arch, head_sha) or True) \
            if subprocess.call(["git", "merge-base", "--is-ancestor", arch, head_sha],
                               cwd=HERE, stderr=subprocess.DEVNULL) == 0 else False

    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
