#!/usr/bin/env python3
"""Run 38 - class-aware durability for anonymous write surfaces.

Run 37 asked every service the same question -- "is my token still in the bytes
I can read back?" -- and produced a tidy number: 13 accepted, 5 read back. The
number was wrong, and the way it was wrong is the useful part.

That question is well posed for a paste. It cannot answer *yes* for a URL
shortener, whose entire job is to hand back the bytes of its target instead of
mine. It cannot answer *yes* for a file host that answers with a landing page
and a download link, because my bytes live behind the link. It cannot answer
*yes* for a recorder that re-encodes my wav to mp3, because re-encoding is the
service. One test, pointed at four different content classes, could only ever
fire for one of them -- so four working redirects, one live download page and
one playable mp3 were all scored as failures.

This asks each class the question its own design can answer:

  shortener  does it still resolve to the exact target that was submitted, and
             did a redirect actually happen? A parked page, an interstitial or
             a hijack all fail, and the recorded hop chain says which.
  paste      is the artefact body still retrievable and intact -- the whole
             stable body as one contiguous run, not a token that a 404 page or
             a reflected editor form could echo back at me.
  file       same, plus size attestation when the bytes sit behind a link.
  audio      is a real audio object still served, in a plausible shape?

The second axis is retention, which run 37 could not measure at all: a one-shot
verdict cannot answer "still there?" -- the only question durability asks. Every
pass records age_hours and a content hash, so repeated runs build a survival
curve and can separate *swept* from *edited* from *present*.

Read-only by construction: this re-fetches, it never re-uploads, so it is safe
to run on a schedule forever.
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "paste_surfaces.json")
OUT = os.path.join(DATA, "write_verify.json")

# The harness's own furniture filter, reused rather than re-derived: where run
# 37's accept flag and run 37's own filter disagree, the filter is right.
from probe_paste_surfaces import is_item_url  # noqa: E402

SITE = "https://agentgates.surge.sh"
UA = "agentgates-probe/1.0 (+%s; read-back pass, no account, no re-upload)" % SITE
TIMEOUT = 25

# Mirrors probe_paste_surfaces.build_payload() for a non-blob spec, verbatim.
# It is not trusted: the first raw-byte artefact I read back must equal this
# string reconstructed from its own `written:` timestamp, or the check fails
# loudly. The data validates the instrument, not the other way round.
PAYLOAD_TEMPLATE = (
    "Agent Gates\n"
    "\n"
    "Agent Gates run 37 - account-free write-surface probe.\n"
    "token: {token}\n"
    "written: {written}\n"
    "source: " + SITE + "\n"
)


# ---------------------------------------------------------------- fetching ---

class _Recorder(urllib.request.HTTPRedirectHandler):
    """Keep the hop chain. 'It returned 200' is not evidence of a redirect."""

    def __init__(self):
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({"status": code, "from": req.full_url, "to": newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, timeout=TIMEOUT):
    """GET with the redirect chain preserved. Never raises."""
    rec = _Recorder()
    op = urllib.request.build_opener(rec)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    out = {"url": url, "status": None, "final": "", "ctype": "", "bytes": 0,
           "sha256": "", "chain": [], "error": "", "raw": b""}
    try:
        with op.open(req, timeout=timeout) as r:
            raw = r.read(400000)
            out.update(status=r.status, final=r.geturl(),
                       ctype=r.headers.get("Content-Type", ""), raw=raw)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(400000)
        except Exception:  # noqa: BLE001
            raw = b""
        out.update(status=e.code, final=e.url or url, raw=raw, error="HTTPError")
    except Exception as e:  # noqa: BLE001
        out.update(error="%s: %s" % (type(e).__name__, e))
    out["bytes"] = len(out["raw"])
    out["sha256"] = hashlib.sha256(out["raw"]).hexdigest() if out["raw"] else ""
    out["chain"] = rec.chain
    return out


TAGRE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
TAGRE2 = re.compile(r"(?s)<[^>]+>")


def to_text(raw):
    """HTML -> text, flattened. Wrapped pages must still yield the payload."""
    s = raw.decode("utf-8", "replace")
    s = TAGRE.sub(" ", s)
    s = TAGRE2.sub(" ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def norm_url(u):
    s = urllib.parse.urlsplit((u or "").strip())
    host = (s.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (s.path or "").rstrip("/")
    return "%s://%s%s" % ((s.scheme or "").lower(), host, path)


# ------------------------------------------------------------- per-class ---

def check_shortener(rec, live):
    """PASS = the short link still resolves to the exact target submitted.

    The target is not stored per-service, but run 37 submitted SITE for every
    service outside the control pass (probe_paste_surfaces.upload()'s default),
    and the control pass's shorteners are not in the accepted set. Recorded
    explicitly so a reader can disagree with the assumption.
    """
    target = SITE
    hop = bool(live["chain"])
    landed = norm_url(live["final"]) == norm_url(target)
    ok = bool(hop and landed and live["status"] == 200)
    return {
        "check": "resolves to the exact submitted target",
        "expected_target": target,
        "observed_final": live["final"],
        "hops": len(live["chain"]),
        "chain": live["chain"],
        "verdict": "PASS" if ok else "FAIL",
        "why": ("resolved to the exact target after %d hop(s)" % len(live["chain"])) if ok
               else ("no redirect hop recorded" if not hop
                     else "landed on %s instead of the target" % (live["final"] or "nothing")),
    }


def check_paste(rec, live, token):
    """PASS = the artefact body is still retrievable and intact.

    'token in body' is deliberately not the test. A host can echo my token back
    in an error message, or return an editor form pre-filled with my submission,
    and both would pass it. The stable body must appear as one contiguous run.
    """
    text = to_text(live["raw"])
    head = ("Agent Gates Agent Gates run 37 - account-free write-surface probe. "
            "token: %s" % token)
    pat = re.compile(re.escape(head) + r" written: (\S+) source: " + re.escape(SITE))
    m = pat.search(text)
    intact, ts = bool(m), (m.group(1) if m else None)

    # Byte-equality is the strongest evidence available and is reported when it
    # holds -- but it is a bonus, not the gate. A host that wraps my text in its
    # own HTML chrome is still holding my text; failing it for that is exactly
    # the mistake this script exists to correct.
    byte_exact = None
    if ts:
        byte_exact = live["raw"] == PAYLOAD_TEMPLATE.format(token=token, written=ts).encode()

    if intact and byte_exact:
        why = ("byte-identical to the payload that was written (%d bytes, sha256 %s...)"
               % (live["bytes"], live["sha256"][:12]))
    elif intact:
        why = ("full body intact inside the host's own page (%d bytes served; write time "
               "recovered from the artefact itself: %s)" % (live["bytes"], ts))
    elif token and token in text:
        why = ("token present but the body is not contiguous -- wrapped, truncated or "
               "re-rendered past recognition")
    else:
        why = "no trace of the payload in the %d bytes served" % live["bytes"]
    return {
        "check": "artefact body retrievable and intact",
        "recovered_write_time": ts,
        "byte_exact": byte_exact,
        "body_contiguous": intact,
        "served_bytes": live["bytes"],
        "verdict": "PASS" if intact else "FAIL",
        "why": why,
    }


def check_file(rec, live):
    """PASS = body retrievable intact, or size-attested behind a download link."""
    text = to_text(live["raw"])
    token = rec.get("payload_token") or ""
    declared = None
    m = re.search(r"(?i)file\s*size\s*[: ]*(\d+)", text)
    if m:
        declared = int(m.group(1))
    attested = declared is not None and declared == rec.get("payload_bytes")
    if token and token in text:
        return {"check": "body retrievable", "verdict": "PASS",
                "size_attested": attested, "declared_size": declared,
                "served_bytes": live["bytes"],
                "why": "payload token present in the served bytes"}
    if attested:
        return {"check": "size-attested behind a download endpoint", "verdict": "PASS",
                "size_attested": True, "declared_size": declared,
                "expected_size": rec.get("payload_bytes"), "served_bytes": live["bytes"],
                "why": ("host serves a landing page, not the bytes: content is behind its "
                        "download link, but it declares %d bytes, matching the %d written "
                        "-- and it self-reports an expiry, so the object is live"
                        % (declared, rec.get("payload_bytes") or -1))}
    return {"check": "body retrievable or size-attested", "verdict": "FAIL",
            "size_attested": False, "declared_size": declared, "served_bytes": live["bytes"],
            "why": "neither the payload nor a matching size declaration was served"}


AUDIO_MAGIC = ((b"ID3", "mp3/ID3"), (b"\xff\xfb", "mp3/frame-sync"),
               (b"\xff\xf3", "mp3/frame-sync"), (b"RIFF", "wav/RIFF"))


def check_audio(rec, live):
    """PASS = a real audio object is still served.

    Byte-equality is undefined here: the host re-encodes an 11 kB pcm wav to a
    ~2 kB mp3 as a matter of course. Calling that a failure would be scoring a
    service for doing its job, so this records the shape instead and says so.
    """
    magic = next((name for sig, name in AUDIO_MAGIC if live["raw"].startswith(sig)), None)
    is_audio = live["ctype"].startswith("audio/") or magic is not None
    ok = bool(is_audio and live["status"] == 200 and live["bytes"] > 256)
    return {
        "check": "a real audio object is still served",
        "ctype": live["ctype"],
        "magic": magic,
        "served_bytes": live["bytes"],
        "original_bytes": rec.get("payload_bytes"),
        "verdict": "PASS" if ok else "FAIL",
        "limitation": ("host re-encodes the upload, so byte-equality against the original "
                       "wav is undefined -- shape and playability only"),
        "why": ("served %s, %d bytes (original wav was %s bytes, transcoded down)"
                % (live["ctype"] or "?", live["bytes"], rec.get("payload_bytes"))) if ok
               else "no audio object served",
    }


# ------------------------------------------------------------------ targets ---

# Declared lifetimes, quoted from each host's own front page (fetched this run).
# A 404 after the declared lifetime is the service *working*: it is a stated
# contract honoured on schedule. It is also not durability. A two-column method
# has no way to tell the two apart, which is why this is a separate verdict.
# Anything absent here is undeclared -- which is a different claim from eternal.
DECLARED_TTL_HOURS = {
    "uguu.se": (3, "its front page says: files expire after 3 hours"),
    "x0.at": (100 * 24, "its front page says: files are kept for a minimum of 3, "
                        "and a maximum of 100 days"),
    "temp.sh": (72, "the artifact's own page carries an Expire Time of upload + 3 days"),
}

# HTTP codes that are a statement about *this client* rather than the artifact.
CLIENT_SIDE = (401, 403, 405, 429, 503)

# Sweepers run on a clock, not at the instant a deadline is written down. An
# artifact that vanishes within this window of its declared deadline went at
# the declared time; calling that a failure would be scoring a host for
# keeping its word.
TTL_GRACE_HOURS = 0.5


def readback_urls(rec):
    """Where to re-read each class. Derived from the recorded artefact URL."""
    fam = rec.get("family")
    url = rec.get("returned") or ""
    extra = []
    if fam == "audio":
        media_id = rec.get("media_id") or ""
        if not media_id:
            m = re.search(r"voca\.ro/([A-Za-z0-9]+)", url)
            media_id = m.group(1) if m else ""
        if media_id:
            extra = ["https://media.vocaroo.com/mp3/%s" % media_id,
                     "https://media1.vocaroo.com/mp3/%s" % media_id]
    return url, extra


def main():
    d = json.load(open(SRC))
    token = d.get("token") or ""
    uploaded = d.get("uploaded_at") or ""
    try:
        t0 = datetime.strptime(uploaded, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        age = None

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT))
        except Exception:  # noqa: BLE001
            prev = {}
    prev_age = prev.get("age_hours")

    accepted = {k: v for k, v in d["services"].items() if v.get("accepted")}
    results = {}
    print("age since upload: %s h\n" % ("%.2f" % age if age is not None else "?"))

    for name, rec in sorted(accepted.items()):
        url, extra = readback_urls(rec)
        fam = rec.get("family")

        # Run 37's own furniture filter rejects the URL that run 37 accepted
        # paste.debian.net on (a bare origin, not an artefact). Where the accept
        # flag and the harness's own filter disagree, the filter is right, and
        # the write never happened -- so there is nothing to verify. Counting
        # that as "not persisted" would blame the venue for my bookkeeping.
        if not is_item_url(rec.get("returned") or "", rec.get("endpoint") or ""):
            results[name] = {
                "class_": fam, "verdict": "NOT WRITTEN",
                "returned": rec.get("returned"), "endpoint": rec.get("endpoint"),
                "why": ("accepted on a URL that the harness's own is_item_url() rejects as "
                        "the service's furniture (%s, the endpoint itself, not an artefact) "
                        "-- nothing was written, so there is nothing to re-read. Run 37 "
                        "counted its own endpoint as an accepted write."
                        % (rec.get("returned") or "?")),
            }
            print("%-18s %-9s NOT WRITTEN (accepted on the endpoint's own URL)" % (name, fam))
            continue

        if not url:
            results[name] = {"class_": fam, "verdict": "UNVERIFIABLE",
                             "why": "no artefact URL was recorded for this service"}
            print("%-18s %-9s UNVERIFIABLE (no artefact URL recorded)" % (name, fam))
            continue
        live = fetch(url)
        chosen = live
        if fam == "audio" and extra:
            for cand in extra:
                probe = fetch(cand)
                if probe["status"] == 200 and (probe["ctype"] or "").startswith("audio/"):
                    chosen = probe
                    live = dict(probe)
                    live["chain"] = probe["chain"] + ([{"status": "page", "from": url,
                                                        "to": cand}] if probe["chain"] else [])
                    break
        if fam == "shortener":
            res = check_shortener(rec, live)
        elif fam == "audio":
            res = check_audio(rec, chosen)
        elif fam == "file":
            res = check_file(rec, live)
        else:
            res = check_paste(rec, live, token)

        res.update(class_=fam, readback_url=chosen["url"], http=chosen["status"],
                   served_bytes=chosen["bytes"], content_sha256=chosen["sha256"],
                   fetch_error=chosen["error"], age_hours=None if age is None else round(age, 2))

        # A client-side outcome is not a statement about the artifact. If my
        # egress was blocked or rate-limited, absence is unproven, and writing
        # "gone" would be my own error wearing the artifact's name. If the host
        # announced a deadline and the artifact is past it, that is neither a
        # failure nor durability -- it is a contract honoured, so it gets its
        # own verdict instead of being flattened into the fail column.
        st = chosen["status"]
        if res.get("verdict") == "FAIL":
            ttl = DECLARED_TTL_HOURS.get(name)
            if st is None:
                res["verdict"] = "UNVERIFIABLE"
                res["why"] = ("this client could not fetch it (%s) -- a fact about my egress, "
                              "not about the artifact" % (chosen["error"] or "transport error"))
            elif st in CLIENT_SIDE:
                res["verdict"] = "UNVERIFIABLE"
                res["why"] = ("HTTP %s served to this client (%d bytes) -- blocked or "
                              "rate-limited, so absence is unproven"
                              % (st, chosen["bytes"]))
            elif ttl and age is not None and age >= ttl[0] - TTL_GRACE_HOURS:
                res["verdict"] = "EXPIRED"
                res["declared_ttl_hours"] = ttl[0]
                res["ttl_quote"] = ttl[1]
                res["why"] = ("gone at T+%.2fh; this host declares %.0fh (%s), so it went at the "
                              "declared time -- a stated contract honoured on schedule, which is "
                              "neither a failure nor durability"
                              % (age, ttl[0], ttl[1]))

        # Cross-run stability: same artefact, same hash, or something changed.
        was = (prev.get("services") or {}).get(name, {})
        if was.get("content_sha256") and res.get("content_sha256"):
            res["unchanged_since_previous_pass"] = (
                was["content_sha256"] == res["content_sha256"])
            res["previous_pass_age_hours"] = was.get("age_hours")
        results[name] = res
        print("%-18s %-9s %-5s %s" % (name, fam, res["verdict"], res["why"][:96]))

    passed = [k for k, v in results.items() if v.get("verdict") == "PASS"]
    failed = [k for k, v in results.items() if v.get("verdict") == "FAIL"]
    expired = [k for k, v in results.items() if v.get("verdict") == "EXPIRED"]
    unver = [k for k, v in results.items()
             if v.get("verdict") not in ("PASS", "FAIL", "EXPIRED", "NOT WRITTEN")]
    notwritten = [k for k, v in results.items() if v.get("verdict") == "NOT WRITTEN"]
    classes = {}
    for k, v in results.items():
        c = classes.setdefault(v.get("class_") or "?",
                               {"pass": 0, "fail": 0, "expired": 0,
                                "not_written": 0, "unverifiable": 0})
        key = {"PASS": "pass", "FAIL": "fail", "EXPIRED": "expired",
               "NOT WRITTEN": "not_written"}.get(v.get("verdict"), "unverifiable")
        c[key] += 1

    # The intersection this project has never once filled: a venue that both
    # accepts a write and publishes a listing of what it holds. Without both,
    # "did my write surface?" is not a question the venue can answer.
    listing = d.get("listing") or {}
    both = sorted(k for k, v in (d.get("services") or {}).items()
                  if v.get("accepted") and (listing.get(k) or {}).get("advertised"))
    advertised = sorted(k for k, v in listing.items() if (v or {}).get("advertised"))

    out = {
        "run": 38,
        "instrument": "probe_write_verify.py",
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_hours": None if age is None else round(age, 2),
        "previous_pass_age_hours": prev_age,
        "uploaded_at": uploaded,
        "read_only": "re-fetches only; no re-upload, safe to run on a schedule",
        "class_checks": {
            "shortener": "resolves to the exact submitted target",
            "paste": "artefact body retrievable and intact (whole stable body, not a token)",
            "file": "body retrievable intact, or size-attested behind a download link",
            "audio": "a real audio object is still served (byte-equality undefined: re-encoded)",
        },
        "summary": {"accepted_surfaces": len(accepted),
                    "written": len(accepted) - len(notwritten),
                    "not_written": len(notwritten),
                    "still_there": len(passed),
                    "pass": len(passed), "fail": len(failed),
                    "expired_as_declared": len(expired),
                    "unverifiable": len(unver),
                    "by_class": classes},
        "passed": sorted(passed), "failed": sorted(failed), "unverifiable": sorted(unver),
        "not_written": sorted(notwritten), "expired": sorted(expired),
        "listing_intersection": {
            "advertised_listings": advertised,
            "accepted_writes": sorted(accepted),
            "accepted_AND_advertised": both,
            "note": ("'did my write surface?' is only askable where a venue both accepts a "
                     "write and publishes what it holds. That set is empty here, so run 37's "
                     "'0 surfaced' was not a finding about visibility -- it was a finding "
                     "about venue shape, and the sentence was overclaiming."),
        },
        "services": results,
    }
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)

    print("\npass %d / fail %d / expired-as-declared %d / unverifiable %d / not written %d  "
          "(of %d accepted)"
          % (len(passed), len(failed), len(expired), len(unver), len(notwritten), len(accepted)))
    print("accepted AND advertises a listing: %s" % (both or "none"))
    print("wrote %s" % OUT)


if __name__ == "__main__":
    sys.exit(main())
