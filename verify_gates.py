#!/usr/bin/env python3
"""Verify the Agent Gates manifest: signature, and the four published standards.

    python3 verify_gates.py                # local files in web/
    python3 verify_gates.py --url https://agentgates.surge.sh
    python3 verify_gates.py --url ... --check-standards

Exits 0 only if every check passes; prints one line per check. No dependencies
beyond `cryptography` (for the signature) and the standard library.

The signature covers the exact bytes of gates.json, so any mirror that edits a
number in it fails verification.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
KEYNAME = "http-message-signatures-directory"
UA = "AgentGatesVerifier/0.1 (+https://agentgates.surge.sh/)"


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="base URL; omit to check web/ on disk")
    ap.add_argument("--check-standards", action="store_true",
                    help="also fetch robots.txt/llms.txt/ai.txt and validate shape")
    args = ap.parse_args(argv)

    base = (args.url or "").rstrip("/")
    checks, failed = [], 0

    def get(path):
        if base:
            return fetch(base + path)
        with open(os.path.join(WEB, path.lstrip("/")), "rb") as f:
            return f.read()

    try:
        raw = get("/gates.json")
        manifest = json.loads(raw.decode())
    except Exception as e:
        print("FAIL  gates.json unreadable: %s" % e)
        return 1

    sha = hashlib.sha256(raw).hexdigest()
    checks.append(("gates.json parsed, %d bytes" % len(raw), True))
    checks.append(("sha256 %s" % sha[:32], True))

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except Exception as e:
        print("FAIL  needs `cryptography`: %s" % e)
        return 1

    try:
        sigtext = get("/gates.json.sig").decode().strip()
        keyid, b64sig = sigtext.split()[0], sigtext.split()[1]
    except Exception as e:
        print("FAIL  gates.json.sig unreadable: %s" % str(e)[:80])
        return 1

    # canonical location first, then the plain-path mirror for hosts that refuse
    # to serve dot-directories (surge.sh does; see publish_identity.py)
    key, used = None, None
    for path in ("/.well-known/" + KEYNAME, "/agent-key.jwks"):
        try:
            jwks = json.loads(get(path).decode())
            keys = {k.get("kid"): k for k in jwks["keys"]}
            if keyid in keys:
                key, used = keys[keyid], path
                break
        except Exception:
            continue
    if key is None:
        checks.append(("public key %s not served at any known path" % keyid, False))
        failed += 1
    else:
        checks.append(("key %s found at %s" % (keyid, used), True))
        try:
            x = base64.urlsafe_b64decode(key["x"] + "=" * (-len(key["x"]) % 4))
            Ed25519PublicKey.from_public_bytes(x).verify(
                base64.b64decode(b64sig), raw)
            checks.append(("Ed25519 signature valid over %d bytes" % len(raw), True))
        except InvalidSignature:
            checks.append(("Ed25519 signature INVALID - file was modified", False))
            failed += 1
        except Exception as e:
            checks.append(("signature check errored: %s" % str(e)[:80], False))
            failed += 1

    for k in ("generated_at", "built_at", "census", "meta_finding"):
        ok = k in manifest
        checks.append(("manifest carries `%s`" % k, ok))
        failed += 0 if ok else 1

    # A verifying signature proves the bytes were not altered. It says nothing about
    # whether they are CURRENT - a CDN can serve a stale manifest together with its
    # matching stale signature and pass every check above. So the freshness stamp is
    # printed, not assumed, and a stale-looking one is called out.
    stamp = manifest.get("built_at")
    if stamp:
        age = None
        try:
            import datetime as _dt
            t = _dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
            age = (_dt.datetime.utcnow() - t).total_seconds() / 3600.0
        except Exception:
            pass
        if age is None:
            checks.append(("manifest built_at = %s" % stamp, True))
        else:
            fresh = age < 24
            checks.append(("manifest built_at = %s (%.1f h old)" % (stamp, age), fresh))
            if not fresh:
                failed += 1

    # Two links on this page once pointed at files that were never copied into web/:
    # a published 404 that survived two runs because nothing checked an href. This
    # gate exists so a third one cannot. Local run checks the disk; --url checks the
    # host, where a soft-404 would otherwise pass as content.
    dead, links, pages = [], 0, 0
    MIRROR = {".well-known/" + KEYNAME: "agent-key.jwks"}
    for root, _dirs, files in os.walk(WEB):
        for fn in sorted(files):
            if not fn.endswith(".html"):
                continue
            page = os.path.join(root, fn)
            rel = os.path.relpath(page, WEB).replace(os.sep, "/")
            try:
                with open(page, encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except Exception:
                continue
            pages += 1
            for href in sorted(set(re.findall(r'(?:href|src)="([^"#?]+)"', body))):
                if href.startswith(("http://", "https://", "//", "mailto:",
                                    "data:", "javascript:")):
                    continue
                target = os.path.normpath(os.path.join(os.path.dirname(rel),
                                                       href.lstrip("/")))
                links += 1
                if base:
                    url = base + "/" + target.lstrip("/")
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": UA})
                        with urllib.request.urlopen(req, timeout=15) as r:
                            status = r.status
                            head = r.read(300).lower()
                        ok = status == 200 and not (target.endswith(".json")
                                                    and head.lstrip().startswith(b"<"))
                    except urllib.error.HTTPError as e:
                        ok = False
                        status = e.code
                    except Exception as e:
                        ok = False
                        status = str(e)[:40]
                    if not ok and target in MIRROR:
                        # surge.sh will not serve a dot-directory, which is exactly why
                        # publish_identity.py writes this plain-path mirror. A link to the
                        # canonical location is satisfied by the mirror.
                        try:
                            req = urllib.request.Request(base + "/" + MIRROR[target],
                                                         headers={"User-Agent": UA})
                            with urllib.request.urlopen(req, timeout=15) as r:
                                ok = r.status == 200
                            if ok:
                                status = "via " + MIRROR[target]
                        except Exception as e2:
                            ok = False
                            status = "mirror %s: %s" % (MIRROR[target], str(e2)[:60])
                    if not ok:
                        dead.append("%s -> %s (%s)" % (rel, href, status))
                elif not os.path.exists(os.path.join(WEB, target)):
                    dead.append("%s -> %s (not on disk)" % (rel, href))
    checks.append(("every relative href in %d page(s) resolves (%d link(s))"
                   % (pages, links), not dead))
    failed += 0 if not dead else 1
    for d in dead[:6]:
        checks.append(("dead link: %s" % d, False))

    if args.check_standards:
        # the same shape rules validate_census.py applies to the 500 domains
        for path, kind in (("/robots.txt", "robots"), ("/llms.txt", "text"),
                           ("/ai.txt", "text"),
                           ("/agent-key.jwks", "jwks")):
            try:
                body = get(path)
                low = body[:400].lower()
                if kind == "robots":
                    ok = b"user-agent" in body.lower() and len(body) > 8
                elif kind == "jwks":
                    s = body.decode("utf-8", "replace")
                    c = json.loads(s)
                    ok = not low.lstrip().startswith(b"<") and any(
                        t in s.lower() for t in ("keys", "kty", "crv", "jwks"))
                    ok = ok and isinstance(c, dict) and "keys" in c
                else:
                    ok = (len(body) >= 8 and not low.lstrip().startswith(b"<")
                          and b"<html" not in low)
                checks.append(("%s looks valid (not a soft-404)" % path, ok))
                failed += 0 if ok else 1
            except Exception as e:
                checks.append(("%s fetch failed: %s" % (path, str(e)[:60]), False))
                failed += 1

    for label, ok in checks:
        print("%s  %s" % ("ok  " if ok else "FAIL", label))
    print("\n%d check(s), %d failure(s)" % (len(checks), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
