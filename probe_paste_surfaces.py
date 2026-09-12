#!/usr/bin/env python3
"""Agent Gates - the account-free WRITE class. Offered -> accepted -> persisted -> surfaced.

Every surface this project censused before (36 runs) was a READ or a signup: a
robots.txt, an llms.txt, a form that wanted an email. The class nobody tested is
the one a stranger can walk into and leave something behind with no account at
all: pastebins, filebins, URL shorteners, audio hosts.

A person who watched this project fail in IRC (rizon #robots, run 36) named this
class as the one that actually works. So it gets the treatment everything else in
this project gets - four stages, each one a separate claim, because the previous
five runs of this project established that the stages do not follow from each
other:

  OFFERED     the service publishes an endpoint an agent can use with no account,
              no API key, no email, no captcha. Measured by attempt, not by docs.
  ACCEPTED    2xx AND a URL/ID came back that actually belongs to the service.
  PERSISTED   the returned URL still serves the exact bytes I wrote, minutes later.
  SURFACED    the service publishes the new item to strangers - a public recent
              list, or an ID space a stranger can walk without guessing creds.
              'Accepted' is not 'surfaced', exactly as 'published' was not 'read'.

CONTROLS. A refusal is not a finding until the same harness, same minute, gets a
different answer for a different reason. Every refusal is re-run twice:
  1. target swap   - a neutral target (example.com / neutral text) through the
                     same endpoint with the same agent UA.
  2. client swap   - a real browser User-Agent, and for transport-level failures
                     a second TLS stack (curl) instead of python-urllib.
That splits 'this service refuses agents' from 'this service refuses what I
offered' from 'this service refuses my TLS fingerprint' from 'this service is dead'.
Pass 1 of this probe was discarded for want of exactly this discipline: it
produced four accepted-looking results that were artifacts of the harness (a
w3.org doctype URL read as a paste URL, an ad-script URL off a parked domain,
and two refusals caused by the harness overwriting a service's own form fields).

Usage:
  python3 probe_paste_surfaces.py --phase upload --token ag37b-deadbeef
  python3 probe_paste_surfaces.py --phase verify     # run minutes later
  python3 probe_paste_surfaces.py --phase listing
  python3 probe_paste_surfaces.py --phase control
  python3 probe_paste_surfaces.py --phase report

Stdlib only. One upload per service per pass, ~400 bytes each, declared UA on
everything. A refusal is a result and is recorded verbatim, including the shape
of the refusal (readable text vs JS/captcha wall vs TLS-level), because a
previous run found that some venues say no in a way an agent cannot even read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "paste_surfaces.json")
SITE = "https://agentgates.surge.sh"
UA = "agentgates-probe/1.0 (+%s; one upload per service, no account)" % SITE
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
NEUTRAL = "https://example.com"
TIMEOUT = 20

URL_RE = re.compile(r"https?://[^\s\"'<>)\\\]]+")
OPAQUE = re.compile(r"(?i)(cf-chl|cloudflare|just a moment|recaptcha|g-recaptcha|h-captcha|"
                    r"turnstile|enable javascript|are you a robot|ddos-guard|incapsula|"
                    r"checking your browser|attention required)")
BS = "----agentgates-%s" % secrets.token_hex(6)


# ---------------------------------------------------------------- transport

def request(url, data=None, method=None, headers=None, timeout=TIMEOUT, ua=None):
    """Never raises. Returns (status, body_text, err_kind, err_text, final_url)."""
    h = {"User-Agent": ua or UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(200000)
            return r.status, body.decode("utf-8", "replace"), "", "", r.geturl()
    except urllib.error.HTTPError as e:
        try:
            body = e.read(200000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, "", "", getattr(e, "url", url)
    except urllib.error.URLError as e:
        return None, "", "network", "%s" % (e.reason,), url
    except socket.timeout:
        return None, "", "network", "timeout after %ds" % timeout, url
    except Exception as e:  # noqa: BLE001
        return None, "", "network", repr(e), url


def curl_status(url, ua=None, insecure=False, method=None, data=None):
    """Second opinion from a different TLS stack. Returns (status, body_or_error)."""
    cmd = ["curl", "-s", "-m", str(TIMEOUT), "-A", ua or UA, "-o", "-", "-w", "\n[%{http_code}]"]
    if insecure:
        cmd.append("-k")
    if method:
        cmd += ["-X", method]
    if data:
        cmd += ["--data", data]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 10)
        out = (p.stdout or b"").decode("utf-8", "replace")
        m = re.search(r"\[(\d{3})\]$", out.strip())
        return (int(m.group(1)) if m else None), out[:400]
    except Exception as e:  # noqa: BLE001
        return None, repr(e)[:200]


def multipart(fields, files):
    """files: list of (field, filename, content_type, bytes)."""
    out = []
    for k, v in (fields or {}).items():
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                    % (BS, k, v)).encode())
    for field, fname, ctype, blob in files:
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                    "Content-Type: %s\r\n\r\n" % (BS, field, fname, ctype)).encode())
        out.append(blob)
        out.append(b"\r\n")
    out.append(("--%s--\r\n" % BS).encode())
    return b"".join(out), "multipart/form-data; boundary=%s" % BS


def form(fields):
    return urllib.parse.urlencode(fields).encode()


# ---------------------------------------------------------------- URL honesty

def host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def belongs(url, endpoint):
    """Does a URL found in a response actually belong to the service that served it?

    Pass 1 accepted a w3.org doctype URL from paste.debian.net and an
    abovedomains.com ad-script URL from the parked envs.sh. Both were the
    harness congratulating itself. A returned URL counts only if its host is the
    service's host, a subdomain of it, or shares the registrable domain.
    """
    a, b = host_of(url), host_of(endpoint)
    if not a or not b:
        return False
    if a == b or a.endswith("." + b) or b.endswith("." + a):
        return True
    return ".".join(a.split(".")[-2:]) == ".".join(b.split(".")[-2:])


ASSET_RE = re.compile(r"\.(png|jpe?g|gif|svg|ico|css|js|webp|woff2?|webmanifest|xml)$", re.I)
# A 200 with a service-side error in the body is a refusal, not a write.
# is.gd and v.gd both answered "200 Error, database insert failed" and pass 2's
# harness counted them as accepted. That was my bug, not their contract.
REFUSAL_RE = re.compile(r"^\s*(error|failed|invalid|denied)\b", re.I)


def clean_url(u):
    """Strip the control bytes a raw socket hands back (termbin sends '\\n\\x00')."""
    u = re.sub(r"[\x00-\x20\x7f]", "", u or "")
    return u.rstrip(".,;)")


def is_item_url(url, endpoint):
    """Is this the URL of a written artifact, or just the service's own furniture?

    Pass 2 accepted three pieces of furniture: file.io's og:image (a Gatsby
    landing page), paste.debian.net's own root (its POST returned the homepage),
    and is.gd's request URL echoed back as its own redirect. None of those is a
    place where anything was written.
    """
    try:
        s = urllib.parse.urlsplit(url)
    except Exception:  # noqa: BLE001
        return False
    path = s.path or ""
    if path in ("", "/"):
        return False
    if ASSET_RE.search(path):
        return False
    if "/images/" in path.lower() or "/assets/" in path.lower():
        return False
    if url.rstrip("/") == (endpoint or "").rstrip("/"):
        return False
    return True


def first_url(body, endpoint, extra_ok=()):
    """First URL in the body that provably belongs to the service.

    Two exclusions learned the hard way: a marketing asset (.png in an og:image)
    is not an artifact, and a bare origin ("https://www.file.io/") is the
    homepage, not the thing I wrote.
    """
    text = (body or "").replace("\\/", "/")
    for m in URL_RE.finditer(text):
        u = clean_url(m.group(0))
        if ASSET_RE.search(u):
            continue
        if not urllib.parse.urlparse(u).path.strip("/"):
            continue
        if (belongs(u, endpoint) or any(belongs(u, e) for e in extra_ok)) \
                and is_item_url(u, endpoint):
            return u
    return ""


def json_url(body, endpoint, extra_ok=()):
    """JSON contracts put the answer in a key; uguu.se escapes its slashes."""
    try:
        d = json.loads((body or "").replace("\\/", "/"))
    except Exception:  # noqa: BLE001
        return ""
    stack = [d]
    keys = ("url", "link", "short_url", "result_url", "shorturl", "location", "files")
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, str) and k.lower() in keys:
                    u = clean_url(v.replace("\\/", "/"))
                    if u.startswith("http") and (belongs(u, endpoint) or
                                                 any(belongs(u, e) for e in extra_ok)) \
                            and is_item_url(u, endpoint):
                        return u
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""


# ---------------------------------------------------------------- the class

RAW = "raw"
FORM = "form"
MULTI = "multipart"
PUT = "put"
TCP = "tcp"
RENTRY = "rentry"
PASTEBIN = "pastebin"
AUDIO = "audio"
B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# kind=None means "trivial GET contract" (shorteners); 'target' is what the
# control pass swaps out to separate a content refusal from an agent refusal.
SPECS = [
    # --- pastebins / text bins
    dict(name="paste.rs", family="paste", kind=RAW, endpoint="https://paste.rs/",
         body="Agent Gates", listing=None, control_url=None,
         note="documented 'curl --data-binary @file' contract, no key"),
    dict(name="dpaste.org", family="paste", kind=FORM, endpoint="https://dpaste.org/api/",
         fields={"content": "Agent Gates", "format": "urlconf", "expires": "86400"},
         content_fields=["content"], listing="https://dpaste.org/recent/", control_url=None,
         note="documented anonymous JSON API (/api/) - found halted mid-run, see shutdown_notice"),
    dict(name="dpaste.com", family="paste", kind=FORM, endpoint="https://dpaste.com/api/v2/",
         fields={"content": "Agent Gates", "syntax": "text", "expiry_days": "1"},
         content_fields=["content"], listing=None, control_url=None,
         note="documented anonymous API, returns URL as text"),
    dict(name="sprunge.us", family="paste", kind=FORM, endpoint="https://sprunge.us",
         fields={"sprunge": "Agent Gates"}, content_fields=["sprunge"], listing=None,
         control_url=None, note="the classic 'curl -F sprunge=<-' endpoint"),
    dict(name="ix.io", family="paste", kind=FORM, endpoint="http://ix.io",
         fields={"f:1": "Agent Gates"}, content_fields=["f:1"], listing=None,
         control_url=None, note="curl -F 'f:1=<-' ix.io"),
    dict(name="termbin.com", family="paste", kind=TCP, endpoint="termbin.com:9999",
         listing=None, control_url=None, note="netcat contract: nc termbin.com 9999"),
    dict(name="rentry.co", family="paste", kind=RENTRY, endpoint="https://rentry.co/api/new",
         listing=None, control_url=None,
         note="anonymous API but needs a CSRF token harvested in a first call"),
    dict(name="paste.debian.net", family="paste", kind=FORM, endpoint="https://paste.debian.net/",
         fields={"content": "Agent Gates", "format": "text", "expiry": "604800", "submit": "Paste"},
         content_fields=["content"], listing=None, control_url=None,
         note="HTML form; is there a machine contract behind it?"),
    dict(name="pastebin.com", family="paste", kind=PASTEBIN,
         endpoint="https://pastebin.com/api/api_post.php", listing=None, control_url=None,
         note="the most famous of the class - control: known to require api_dev_key"),
    dict(name="privatebin.net", family="paste", kind=FORM, endpoint="https://privatebin.net/",
         fields={"data": "Agent Gates"}, content_fields=["data"],
         listing="https://privatebin.net/?page=recent", control_url=None,
         note="self-hosted family; the browser builds the payload client-side"),

    # --- filebins
    dict(name="0x0.st", family="file", kind=MULTI, endpoint="https://0x0.st/",
         files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")], listing=None,
         control_url=None, note="explicitly asks for an identifying User-Agent - tests UA honesty"),
    dict(name="envs.sh", family="file", kind=MULTI, endpoint="https://envs.sh/",
         files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")], listing=None,
         control_url=None, note="0x0 clone"),
    dict(name="x0.at", family="file", kind=MULTI, endpoint="https://x0.at/",
         files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")], listing=None,
         control_url=None, note="0x0-family"),
    dict(name="temp.sh", family="file", kind=MULTI, endpoint="https://temp.sh/upload",
         files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")], listing=None,
         control_url=None, note="POST /upload multipart (the PUT form 404s)"),
    dict(name="oshi.at", family="file", kind=MULTI, endpoint="https://oshi.at",
         fields={"expire": "60"}, files=[("f", "agentgates.txt", "text/plain", b"Agent Gates")],
         listing=None, control_url=None,
         note="upload form with an expiry field; TLS certificate fails verification"),
    dict(name="bashupload.com", family="file", kind=MULTI, endpoint="https://bashupload.com/",
         files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")], listing=None,
         control_url=None, note="curl bashupload.com -T file"),
    dict(name="transfer.sh", family="file", kind=PUT, endpoint="https://transfer.sh/agentgates.txt",
         listing=None, control_url=None, note="status uncertain in 2026 - recorded either way"),
    dict(name="catbox.moe", family="file", kind=MULTI, endpoint="https://catbox.moe/user/api.php",
         fields={"reqtype": "fileupload"},
         files=[("fileToUpload", "agentgates.txt", "text/plain", b"Agent Gates")],
         listing=None, control_url=None, note="permanent by policy, anonymous"),
    dict(name="litterbox", family="file", kind=MULTI,
         endpoint="https://litterbox.catbox.moe/resources/internals/api.php",
         fields={"reqtype": "fileupload", "time": "1h"},
         files=[("fileToUpload", "agentgates.txt", "text/plain", b"Agent Gates")],
         listing=None, control_url=None, note="catbox' temporary sibling, 1h"),
    dict(name="uguu.se", family="file", kind=MULTI, endpoint="https://uguu.se/upload",
         files=[("files[]", "agentgates.txt", "text/plain", b"Agent Gates")],
         listing=None, control_url=None, extra_ok=("https://uguu.se",),
         note="temporary host, 3h; answers in JSON with escaped slashes"),
    dict(name="file.io", family="file", kind=MULTI, endpoint="https://file.io/",
         fields={"expires": "1w"}, files=[("file", "agentgates.txt", "text/plain", b"Agent Gates")],
         listing=None, control_url=None, note="single-download by design - a read consumes it"),
    dict(name="vocaroo.com", family="audio", kind=AUDIO,
         endpoint="https://upload1.vocaroo.com/apps/main-api/upload",
         api="https://vocaroo.com/apps/main-api",
         upload_hosts=["https://upload1.vocaroo.com/apps/main-api/upload",
                       "https://upload2.vocaroo.com/apps/main-api/upload"],
         share_url="https://voca.ro/", extra_ok=("https://voca.ro/",),
         listing=None, control_url=None,
         note="audio class. The homepage advertises UPLOAD_URLS in plain HTML but "
              "every advertised route 404s to a from-scratch client; the working "
              "contract (chunk POST -> finalize -> status poll) was read out of their "
              "minified bundle. Also the audio leg of the 'one upload' rule: a real "
              "pcm wav, ~11kB, so a human opening the link hears something."),

    # --- URL shorteners (target = the URL being shortened)
    dict(name="is.gd", family="shortener", kind=None, endpoint="https://is.gd/create.php",
         get={"format": "simple", "url": SITE}, listing=None, target_field="url",
         control_url=NEUTRAL, note="GET contract, no key - the cleanest of the class"),
    dict(name="v.gd", family="shortener", kind=None, endpoint="https://v.gd/create.php",
         get={"format": "simple", "url": SITE}, listing=None, target_field="url",
         control_url=NEUTRAL, note="is.gd twin, same contract"),
    dict(name="tinyurl.com", family="shortener", kind=None, endpoint="https://tinyurl.com/api-create.php",
         get={"url": SITE}, listing=None, target_field="url", control_url=NEUTRAL,
         note="the one a human would name first"),
    dict(name="cleanuri.com", family="shortener", kind=FORM, endpoint="https://cleanuri.com/api/v1/shorten",
         fields={"url": SITE}, content_fields=[], listing=None, target_field="url",
         control_url=NEUTRAL, note="JSON POST contract"),
    dict(name="da.gd", family="shortener", kind=None, endpoint="https://da.gd/shorten",
         get={"url": SITE}, listing=None, target_field="url", control_url=NEUTRAL,
         note="GET contract"),
    dict(name="spoo.me", family="shortener", kind=FORM, endpoint="https://spoo.me/",
         fields={"url": SITE}, content_fields=[], headers={"Accept": "application/json"},
         listing=None, target_field="url", control_url=NEUTRAL,
         note="anonymous JSON API, and it publishes per-link stats"),
    dict(name="clck.ru", family="shortener", kind=None, endpoint="https://clck.ru/--",
         get={"url": SITE}, listing=None, target_field="url", control_url=NEUTRAL,
         note="network reachability is itself a result"),
]

BY_NAME = {s["name"]: s for s in SPECS}


def build_payload(spec, token, blob):
    """Fill the spec's placeholder content with the run's real payload."""
    body = ("%s\n\nAgent Gates run 37 - account-free write-surface probe.\n"
            "token: %s\nwritten: %s\nsource: %s\n"
            % (blob.decode("utf-8", "replace") if blob else "Agent Gates",
               token, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), SITE)).encode()
    return body


def upload(spec, token, ua=None, target=None):
    """Returns a record dict for one service. Never raises.

    ua/target exist for the control pass: same endpoint, same fields, one thing
    changed. Without that, a refusal is not separable from a harness mistake.
    """
    kind = spec.get("kind")
    extra_ok = tuple(spec.get("extra_ok") or ())
    rec = {"name": spec["name"], "family": spec["family"], "endpoint": spec["endpoint"],
           "documented_note": spec.get("note", ""), "offered": "", "status": None,
           "accepted": False, "returned": "", "refusal_shape": "", "refusal_text": "",
           "payload_token": token, "payload_bytes": 0, "detail": "", "listing": spec.get("listing"),
           "final_url": "", "url_rejected": "", "token_in_response": False, "ua_used": ua or UA}
    tgt = target or SITE
    req_url = spec["endpoint"]
    if kind is None:
        q = dict(spec["get"])
        if spec.get("target_field"):
            q[spec["target_field"]] = tgt
        req_url = spec["endpoint"] + "?" + urllib.parse.urlencode(q)
        status, body, ek, et, final = request(req_url, headers=spec.get("headers"), ua=ua)
    elif kind == RAW:
        blob = build_payload(spec, token, None)
        rec["payload_bytes"] = len(blob)
        status, body, ek, et, final = request(spec["endpoint"], data=blob, ua=ua,
                                              headers={"Content-Type": "text/plain"})
    elif kind == FORM:
        fields = dict(spec["fields"])
        cf = spec.get("content_fields")
        if cf is None:
            cf = list(fields)  # legacy behaviour: whole form carries the payload
        if cf:
            payload = build_payload(spec, token, None).decode()
            for k in cf:
                fields[k] = payload
        if spec.get("target_field"):
            fields[spec["target_field"]] = tgt
        blob = form(fields)
        rec["payload_bytes"] = len(blob)
        status, body, ek, et, final = request(
            spec["endpoint"], data=blob, ua=ua,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     **(spec.get("headers") or {})})
    elif kind == MULTI:
        files = []
        for field, fname, ctype, marker in spec["files"]:
            blob = make_wav() if fname.endswith(".wav") else build_payload(spec, token, marker)
            rec["payload_bytes"] += len(blob)
            files.append((field, fname, ctype, blob))
        blob, ctype = multipart(spec.get("fields"), files)
        status, body, ek, et, final = request(spec["endpoint"], data=blob, ua=ua,
                                              headers={"Content-Type": ctype,
                                                       **(spec.get("headers") or {})})
    elif kind == PUT:
        blob = build_payload(spec, token, None)
        rec["payload_bytes"] = len(blob)
        status, body, ek, et, final = request(spec["endpoint"], data=blob, method="PUT", ua=ua,
                                              headers={"Content-Type": "text/plain"})
    elif kind == TCP:
        return upload_tcp(spec, token, rec)
    elif kind == AUDIO:
        return upload_vocaroo(spec, token, rec, ua=ua)
    elif kind == RENTRY:
        return upload_rentry(spec, token, rec)
    elif kind == PASTEBIN:
        return upload_pastebin(spec, token, rec)
    else:
        raise ValueError(kind)

    rec["final_url"] = final or ""
    rec["status"] = status
    rec["requested_url"] = req_url
    rec["token_in_response"] = bool(token in (body or ""))
    if status is None:
        rec["offered"] = "no (transport)"
        rec["refusal_shape"] = "network / TLS handshake refused"
        rec["refusal_text"] = et[:300]
        rec["detail"] = et[:200]
        return rec
    rec["detail"] = body.strip().replace("\n", " ")[:200]
    u = json_url(body, spec["endpoint"], extra_ok) or first_url(body, spec["endpoint"], extra_ok)
    if not u and final and clean_url(final) != clean_url(req_url) \
            and belongs(final, spec["endpoint"]) and is_item_url(final, spec["endpoint"]):
        u = clean_url(final)  # redirect contract: the artifact is where it redirected me
    if u and not belongs(u, spec["endpoint"]) and not any(belongs(u, e) for e in extra_ok):
        rec["url_rejected"] = u
        u = ""
    if u and not is_item_url(u, spec["endpoint"]):
        rec["url_rejected"] = u
        u = ""
    plain = body.strip()
    if REFUSAL_RE.match(plain[:40]) or "database insert failed" in plain.lower()[:200]:
        rec["offered"] = "no"
        rec["accepted"] = False
        rec["returned"] = ""
        rec["refusal_shape"] = "readable? (%s with a service-side error body)" % status
        rec["refusal_text"] = plain.replace("\n", " ")[:300]
        return rec
    if u and 200 <= status < 300:
        rec["offered"] = "yes"
        rec["accepted"] = True
        rec["returned"] = u
    elif 200 <= status < 300 and re.match(r"^[A-Za-z0-9._/-]{4,}$", plain):
        rec["offered"] = "yes"
        rec["accepted"] = True
        rec["returned"] = plain  # bare token/short code, e.g. a shortener's own slug
    else:
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(status, body)
        rec["refusal_text"] = plain.replace("\n", " ")[:300]
        if not u and 200 <= status < 300:
            rec["refusal_shape"] = "no machine-readable contract (200 HTML, no service URL)"
    return rec


def classify(status, body):
    if status is None:
        return "network"
    if OPAQUE.search(body or ""):
        return "opaque (JS/captcha wall - not readable by an agent)"
    if status == 401:
        return "readable (401 credentials required)"
    if status == 403:
        return "readable? (403)"
    if 400 <= status < 500:
        return "readable (%d)" % status
    return "readable? (%d)" % status


def make_wav(seconds=0.7, rate=8000, freq=440):
    """A 0.7s tone. The audio class needs actual audio to be a fair test."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(12000 * (1 if (i // 40) % 2 == 0 else -1)))
                          for i in range(int(rate * seconds)))
        w.writeframes(frames)
    return buf.getvalue()


def upload_tcp(spec, token, rec):
    host, port = spec["endpoint"].split(":")
    blob = build_payload(spec, token, None)
    rec["payload_bytes"] = len(blob)
    try:
        s = socket.create_connection((host, int(port)), timeout=TIMEOUT)
        s.sendall(blob)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        s.settimeout(10)
        while True:
            try:
                d = s.recv(4096)
            except socket.timeout:
                break
            if not d:
                break
            chunks.append(d)
        s.close()
        body = b"".join(chunks).decode("utf-8", "replace").strip()
        rec["status"] = 200
        rec["detail"] = body[:200]
        u = first_url(body, spec["endpoint"])
        if u:
            rec["offered"] = "yes"
            rec["accepted"] = True
            rec["returned"] = u
        else:
            rec["offered"] = "no"
            rec["refusal_shape"] = "readable (connection ok, no URL)"
            rec["refusal_text"] = body[:300]
    except Exception as e:  # noqa: BLE001
        rec["offered"] = "no (transport)"
        rec["refusal_shape"] = "network / TLS handshake refused"
        rec["refusal_text"] = repr(e)[:300]
    return rec


def upload_vocaroo(spec, token, rec, ua=None):
    """The audio class, reconstructed from vocaroo's own minified bundle.

    Their homepage advertises UPLOAD_URLS in plain HTML, but every advertised
    route answers 404 'Cannot POST /upload' to a from-scratch client: the real
    contract is chunked and undocumented. Read out of the bundle:
      HEAD  {upload}/alive                 -> which host is up (they race two)
      POST  {upload}/{uploadId}/chunk/{i}  -> field 'chunk', 100kB chunks
      POST  {upload}/{uploadId}/finalize   -> {status, mediaId, ownerToken}
      GET   {api}/upload/status/{mediaId}  -> 0 done, 2 processing failed
      share URL = https://voca.ro/<mediaId>
    """
    api = spec["api"]
    hosts = spec["upload_hosts"]
    rec["payload_token"] = token
    # 1. which upload host answers
    live = None
    for h in hosts:
        st, _, _, _, _ = request(h + "/alive", method="HEAD", ua=ua)
        if st and 200 <= st < 400:
            live = h
            break
    if not live:
        rec["offered"] = "no (transport)"
        rec["refusal_shape"] = "no upload host answered HEAD /alive"
        rec["detail"] = "HEAD %s" % ", ".join(h + "/alive" for h in hosts)
        return rec
    # 2. one chunk carrying a real wav, named so the artifact is findable
    wav = make_wav()
    rec["payload_bytes"] = len(wav)
    uid = "".join(secrets.choice(B62) for _ in range(22))
    cap = "%s/%s" % (live, uid)
    blob, ctype = multipart(None, [("chunk", "chunk", "application/octet-stream", wav)])
    st, body, ek, et, fin = request("%s/chunk/0" % cap, data=blob, ua=ua,
                                    headers={"Content-Type": ctype,
                                             "Origin": "https://vocaroo.com",
                                             "Referer": "https://vocaroo.com/"})
    rec["status"] = st
    rec["detail"] = "chunk -> %s | %s" % (st, (body or et or "").strip()[:120])
    if not (st and 200 <= st < 300):
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(st, body) if st else "network / TLS handshake refused"
        rec["refusal_text"] = (body or et or "")[:300]
        return rec
    # 3. finalize -> mediaId. this is the write happening.
    st2, body2, ek2, et2, _ = request(cap + "/finalize", data=b"", method="POST", ua=ua,
                                      headers={"Origin": "https://vocaroo.com",
                                               "Referer": "https://vocaroo.com/"})
    rec["status"] = st2
    try:
        j = json.loads(body2 or "{}")
    except Exception:  # noqa: BLE001
        j = {}
    rec["finalize_raw"] = (body2 or et2 or "")[:200]
    if not j.get("mediaId"):
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(st2, body2)
        rec["refusal_text"] = (body2 or et2 or "")[:300]
        rec["detail"] = "finalize -> %s | %s" % (st2, (body2 or et2 or "")[:150])
        return rec
    mid = j["mediaId"]
    rec["owner_token_present"] = "ownerToken" in j
    # 4. poll until it says the media is processed
    share = spec["share_url"] + mid
    for _ in range(6):
        time.sleep(2)
        stp, bodyp, _, _, _ = request("%s/upload/status/%s" % (api, mid), ua=ua)
        try:
            stt = json.loads(bodyp or "{}").get("status")
        except Exception:  # noqa: BLE001
            stt = None
        rec["status_polls"] = rec.get("status_polls", []) + [stt]
        if stt == 0:
            break
    rec["offered"] = "yes"
    rec["accepted"] = True
    rec["returned"] = share
    rec["media_id"] = mid
    rec["detail"] = "mediaId %s | status poll %s" % (mid, rec.get("status_polls"))
    return rec


def upload_rentry(spec, token, rec):
    """Two calls with a real cookie jar: harvest the CSRF token, then post.

    Pass 1 failed here for a harness reason, not a service reason: the CSRF
    token lives in a cookie as well as in the JSON body, and the probe had no
    cookie jar at all. A browser would always send it, so the fair test does too.
    """
    jar = urllib.request.HTTPCookieProcessor()
    op = urllib.request.build_opener(jar)
    hdr = {"User-Agent": UA, "Referer": "https://rentry.co/",
           "Origin": "https://rentry.co", "Accept": "application/json"}
    status = body = et = ""
    try:
        r = op.open(urllib.request.Request("https://rentry.co/", headers=hdr), timeout=TIMEOUT)
        status, body = r.status, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(200000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        status, et = None, repr(e)
    rec["status"] = status
    rec["detail"] = "step 1 (csrf from the form, not /api/new) %s" % status
    if status is None:
        rec["offered"] = "no (transport)"
        rec["refusal_shape"] = "network / TLS handshake refused"
        rec["refusal_text"] = et[:300]
        return rec
    try:
        csrf = json.loads(body).get("csrf_token") or ""
    except Exception:  # noqa: BLE001
        csrf = ""
    if not csrf:
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', body or "")
        csrf = m.group(1) if m else ""
    cookies = {}
    for c in getattr(jar, "cookiejar", []) or []:
        try:
            cookies[c.name] = c.value
        except Exception:  # noqa: BLE001
            pass
    rec["csrf_from"] = ("body" if csrf else "") + ("+cookie" if cookies.get("csrftoken") else "")
    csrf = csrf or cookies.get("csrftoken", "")
    if not csrf:
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(status, body)
        rec["refusal_text"] = (body or "")[:300]
        return rec
    payload = build_payload(spec, token, None).decode()
    data = urllib.parse.urlencode({"csrf_token": csrf, "text": payload,
                                   "edit_code": token[:8], "url": ""}).encode()
    hdr2 = dict(hdr)
    hdr2.update({"Content-Type": "application/x-www-form-urlencoded",
                 "X-CSRFToken": csrf,
                 "Cookie": "; ".join("%s=%s" % kv for kv in cookies.items())})
    st2, b2, et2, fin2 = None, "", "", ""
    try:
        r2 = op.open(urllib.request.Request(spec["endpoint"], data=data, headers=hdr2),
                     timeout=TIMEOUT)
        st2, b2, fin2 = r2.status, r2.read(100000).decode("utf-8", "replace"), r2.geturl()
    except urllib.error.HTTPError as e:
        st2, b2 = e.code, e.read(100000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        et2 = repr(e)
    rec["detail"] += " | step 2: %s %s" % (st2, (b2 or et2)[:160].replace("\n", " "))
    rec["final_url"] = fin2 or ""
    rec["token_in_response"] = bool(token in (b2 or ""))
    if st2 and 200 <= st2 < 300:
        rec["accepted"] = True
        rec["offered"] = "yes"
        rec["returned"] = first_url(b2, spec["endpoint"]) or ""
    else:
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(st2, b2)
        rec["refusal_text"] = (b2 or "")[:300]
    return rec


def upload_pastebin(spec, token, rec):
    """Control: the famous one, with no api_dev_key at all."""
    data = form({"api_dev_key": "", "api_option": "paste",
                 "api_paste_code": build_payload(spec, token, None).decode(),
                 "api_paste_private": "1"})
    rec["payload_bytes"] = len(data)
    status, body, ek, et, _ = request(spec["endpoint"], data=data,
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    rec["status"] = status
    rec["detail"] = (body or et)[:200].replace("\n", " ")
    rec["token_in_response"] = bool(token in (body or ""))
    if status and 200 <= status < 300 and first_url(body, spec["endpoint"]):
        rec["offered"] = "yes"
        rec["accepted"] = True
        rec["returned"] = first_url(body, spec["endpoint"])
    else:
        rec["offered"] = "no"
        rec["refusal_shape"] = classify(status, body)
        rec["refusal_text"] = (body or "").strip().replace("\n", " ")[:300]
    return rec


# ---------------------------------------------------------------- phases

def load():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save(d):
    os.makedirs(DATA, exist_ok=True)
    json.dump(d, open(OUT, "w"), indent=2, sort_keys=True)


def phase_upload(token, only=None):
    d = load()
    d["run"] = 37
    d["pass"] = "pass2 (pass1 discarded, see data/paste_surfaces_pass1_discarded.json)"
    d["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    d["token"] = token
    d["user_agent"] = UA
    d["services"] = d.get("services") or {}
    for spec in SPECS:
        if only and spec["name"] not in only:
            continue
        t0 = time.time()
        try:
            rec = upload(spec, token)
        except Exception as e:  # noqa: BLE001
            rec = {"name": spec["name"], "family": spec["family"], "endpoint": spec["endpoint"],
                   "offered": "probe error", "detail": repr(e)[:200], "accepted": False,
                   "returned": "", "refusal_shape": "probe error", "refusal_text": "", "status": None}
        rec["seconds"] = round(time.time() - t0, 2)
        d["services"][spec["name"]] = rec
        print("%-16s %-9s %-5s %-4s %s" % (rec["name"], rec["family"], rec.get("status"),
                                           "OK" if rec.get("accepted") else "--",
                                           (rec.get("returned") or rec.get("detail") or
                                            rec.get("refusal_text") or "")[:90]), flush=True)
        save(d)
    print("\nuploaded: %d services -> %s" % (len(d["services"]), OUT))


def phase_control():
    """Every refusal, re-run twice: swapped target, swapped client.

    This is the part pass 1 did not have, and its absence is why pass 1 was
    wrong: without a control, 'database insert failed' looks like the service
    refusing agents, when in fact the same request with example.com succeeds.
    """
    d = load()
    d.setdefault("control", {})
    token = d.get("token", "")
    for spec in SPECS:
        rec = d["services"].get(spec["name"], {})
        if rec.get("accepted"):
            continue
        entry = {"target_swap": None, "browser_ua": None, "curl_strict": None,
                 "curl_relaxed": None, "verdict": ""}
        # control 1: neutral target, same agent UA
        if spec.get("control_url"):
            r = upload(spec, token, ua=UA, target=spec["control_url"])
            entry["target_swap"] = {"target": spec["control_url"], "status": r.get("status"),
                                    "accepted": bool(r.get("accepted")),
                                    "returned": r.get("returned") or "",
                                    "detail": (r.get("detail") or r.get("refusal_text") or "")[:200]}
        # control 2: same everything, browser UA
        r2 = upload(spec, token, ua=BROWSER_UA, target=spec.get("control_url") or None)
        entry["browser_ua"] = {"status": r2.get("status"), "accepted": bool(r2.get("accepted")),
                               "returned": r2.get("returned") or "",
                               "detail": (r2.get("detail") or r2.get("refusal_text") or "")[:200]}
        # control 3: transport failures get a second TLS stack
        if rec.get("status") is None:
            st, body = curl_status(spec["endpoint"], insecure=False)
            entry["curl_strict"] = {"status": st, "body": body[:200]}
            st2, body2 = curl_status(spec["endpoint"], insecure=True)
            entry["curl_relaxed"] = {"status": st2, "body": body2[:200]}

        tgt_ok = bool((entry["target_swap"] or {}).get("accepted"))
        ua_ok = bool((entry["browser_ua"] or {}).get("accepted"))
        tls_ok = bool(entry["curl_strict"] and entry["curl_strict"]["status"] and
                      200 <= entry["curl_strict"]["status"] < 300)
        tls_relaxed_ok = bool(entry["curl_relaxed"] and entry["curl_relaxed"]["status"] and
                              200 <= entry["curl_relaxed"]["status"] < 300)
        if tgt_ok and not rec.get("accepted"):
            entry["verdict"] = ("target-specific: the same endpoint accepts a neutral target with the "
                                "same agent UA, so the refusal is about WHAT was offered, not WHO offered it")
        elif ua_ok:
            entry["verdict"] = "user-agent-specific: a browser UA is accepted where mine was not"
        elif rec.get("status") is None and tls_ok:
            entry["verdict"] = "client-stack-specific: refused python-urllib at the TLS handshake, curl reaches it"
        elif rec.get("status") is None and tls_relaxed_ok:
            entry["verdict"] = "certificate-specific: reachable only if certificate verification is skipped"
        elif rec.get("status") is None:
            entry["verdict"] = "dead or unreachable for every client tried"
        else:
            entry["verdict"] = "refused everything tried (no agent-specific cause isolated)"
        d["control"][spec["name"]] = entry
        print("%-16s %s" % (spec["name"], entry["verdict"][:110]), flush=True)
        save(d)
    d["controlled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(d)
    print("\ncontrol pass done -> %s" % OUT)


def phase_verify():
    d = load()
    d.setdefault("verify", {})
    tok = d.get("token", "")
    for name, rec in d["services"].items():
        url = rec.get("returned")
        if not rec.get("accepted") or not url:
            continue
        t0 = time.time()
        status, body, ek, et, _ = request(url)
        got = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": status,
               "token_present": bool(tok and tok in (body or "")),
               "bytes_seen": len(body or ""), "error": et[:120] if status is None else "",
               "seconds": round(time.time() - t0, 2)}
        if status is None:
            got["verdict"] = "gone (transport: %s)" % et[:60]
        elif got["token_present"]:
            got["verdict"] = "persisted (exact token read back)"
        elif 200 <= status < 300:
            got["verdict"] = "served something else (HTTP %s, token absent)" % status
        elif status in (404, 410):
            got["verdict"] = "gone (HTTP %s)" % status
        elif status == 429:
            got["verdict"] = "not verifiable (429 rate limit)"
        else:
            got["verdict"] = "HTTP %s" % status
        # second read: single-use services delete on first download
        if status and 200 <= status < 300:
            time.sleep(1)
            st2, b2, _, et2, _ = request(url)
            got["second_read"] = {"status": st2, "token_present": bool(tok and tok in (b2 or "")),
                                  "error": et2[:80] if st2 is None else ""}
        d["verify"][name] = got
        print("%-16s %-4s %s" % (name, status, got["verdict"]), flush=True)
        save(d)
    d["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(d)
    print("\nverify pass done -> %s" % OUT)


def phase_listing():
    """SURFACED: is the new item shown to strangers without knowing the URL?"""
    d = load()
    d.setdefault("listing", {})
    tok = d.get("token", "")
    for spec in SPECS:
        rec = d["services"].get(spec["name"], {})
        url = spec.get("listing")
        if not url:
            d["listing"][spec["name"]] = {
                "listing_url": None, "advertised": False, "found": None,
                "verdict": "no public recent-list advertised by the service"}
            continue
        status, body, ek, et, _ = request(url)
        found = bool(tok and tok in (body or ""))
        rid = (rec.get("returned") or "").rstrip("/").split("/")[-1]
        found_id = bool(rid and len(rid) > 3 and rid in (body or ""))
        entry = {"listing_url": url, "advertised": True, "status": status, "found": found,
                 "found_id": found_id, "bytes_seen": len(body or ""),
                 "error": et[:120] if status is None else ""}
        if status is None:
            entry["verdict"] = "listing unreachable (%s)" % et[:60]
        elif found or found_id:
            entry["verdict"] = "SURFACED - my own item appears in the public list"
        elif 200 <= status < 300:
            entry["verdict"] = ("listing is live but my item is not in it"
                                if len(body or "") > 400 else
                                "listing served %d bytes - not a list" % len(body or ""))
        else:
            entry["verdict"] = "listing HTTP %s" % status
        d["listing"][spec["name"]] = entry
        print("%-16s %-4s %s" % (spec["name"], status, entry["verdict"]), flush=True)
        save(d)
    d["listed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(d)
    print("\nlisting pass done -> %s" % OUT)


def summarise(d):
    svc, ver, lis, ctl = d["services"], d.get("verify", {}), d.get("listing", {}), d.get("control", {})
    fams = {}
    for name, rec in svc.items():
        f = fams.setdefault(rec["family"], {"n": 0, "accepted": 0, "persisted": 0, "surfaced": 0,
                                            "refused": 0, "readable_refusal": 0, "dead": 0})
        f["n"] += 1
        if rec.get("accepted"):
            f["accepted"] += 1
        else:
            f["refused"] += 1
            if (rec.get("refusal_shape") or "").startswith("readable") or rec.get("status") is not None:
                f["readable_refusal"] += 1
            if ctl.get(name, {}).get("verdict", "").startswith(("dead", "client-stack", "certificate")):
                f["dead"] += 1
        if (ver.get(name, {}).get("verdict") or "").startswith("persisted"):
            f["persisted"] += 1
        if (lis.get(name, {}).get("verdict") or "").startswith("SURFACED"):
            f["surfaced"] += 1
    return fams


def phase_report():
    d = load()
    fams = summarise(d)
    print(json.dumps(fams, indent=2, sort_keys=True))
    print("\naccepted: %s" % ", ".join(sorted(n for n, r in d["services"].items() if r.get("accepted"))))
    print("refused:  %s" % ", ".join(sorted(n for n, r in d["services"].items() if not r.get("accepted"))))
    return fams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    choices=["upload", "verify", "listing", "control", "report"])
    ap.add_argument("--token", default=None)
    ap.add_argument("--only", default=None, help="comma-separated service names")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    if a.phase == "upload":
        phase_upload(a.token or ("ag37b-" + secrets.token_hex(4)), only)
    elif a.phase == "verify":
        phase_verify()
    elif a.phase == "listing":
        phase_listing()
    elif a.phase == "control":
        phase_control()
    else:
        phase_report()


if __name__ == "__main__":
    main()
