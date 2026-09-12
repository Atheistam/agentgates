#!/usr/bin/env python3
"""Agent Gates - IRC probe. The transcript is the evidence.

Why IRC: every other channel this project tried needs an account. IRC is the last
human venue class where a declared, unregistered agent can walk in and be answered
by a person, with no email address, no captcha and no signup wall. Whether that is
still true in 2026 is itself a measurable claim, so the whole session is logged
verbatim to data/logs/ and summarised to data/<prefix>_summary.json.

Usage:
  python3 probe_irc.py --net libera --channel "#ai" --message "..." --lurk-seconds 900

Stdlib only. Never sends more than one PRIVMSG unless a --follow-up-file is given
and new lines appear in it (max one per 20s). Answers PING. Records KICK/ban
verbatim, because a refusal is a result too.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LOGS = os.path.join(DATA, "logs")

NETS = {
    "libera": ("irc.libera.chat", 6697),
    "oftc": ("irc.oftc.net", 6697),
    "rizon": ("irc.rizon.net", 6697),
}

LINK_RE = re.compile(r"agentgates\.surge\.sh", re.I)


def ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", default="libera", choices=sorted(NETS))
    ap.add_argument("--channel", required=True)
    ap.add_argument("--message", default=None)
    ap.add_argument("--lurk-seconds", type=int, default=600)
    ap.add_argument("--out-prefix", default="irc")
    ap.add_argument("--follow-up-file", default=None)
    ap.add_argument("--port", type=int, default=None)
    a = ap.parse_args(argv)

    host, port = NETS[a.net]
    if a.port:
        port = a.port
    nick = "agprobe%d" % ((int(time.time()) % 1000) * 1000 + (os.getpid() % 1000))
    nick_tries = 0
    chan = a.channel if a.channel.startswith("#") else "#" + a.channel

    os.makedirs(LOGS, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    tpath = os.path.join(LOGS, "%s_%s_%s.transcript" % (a.out_prefix, chan.strip("#"), stamp))
    tg = open(tpath, "a", encoding="utf-8")

    summ = {
        "network": a.net, "host": host, "port": port, "channel": chan, "nick": nick,
        "started_at": ts(), "connect_ok": False, "join_ok": False, "send_ok": False,
        "kicked": False, "notices": [], "messages_seen": 0, "messages_mentioning_us": 0,
        "lines_linking_to_us": 0, "human_nicks": [], "errors": [], "ended_at": None,
        "transcript": tpath,
    }

    def log(line, tag="<-"):
        with open(tpath, "a", encoding="utf-8") as fh:
            fh.write("%s %s %s\n" % (ts(), tag, line))
        if tag == "->":
            print(">>> %s" % line, flush=True)

    ctx = ssl.create_default_context()
    try:
        raw = socket.create_connection((host, port), timeout=20)
        s = ctx.wrap_socket(raw, server_hostname=host)
    except Exception as e:
        summ["errors"].append("connect failed: %r" % (e,))
        json.dump(summ, open(os.path.join(DATA, "%s_summary.json" % a.out_prefix), "w"), indent=2)
        print("CONNECT FAILED: %r" % (e,))
        return 1
    summ["connect_ok"] = True
    s.settimeout(2.0)

    def send(msg):
        s.sendall((msg + "\r\n").encode("utf-8", "replace"))
        log(msg, "->")

    send("NICK %s" % nick)
    send("USER %s 0 * :declared agent probe (agentgates.surge.sh) - GET-only measurement" % nick)

    buf = ""
    registered = False
    follow_up = []
    next_follow_ok = 0.0
    end = time.time() + a.lurk_seconds
    follow_path = a.follow_up_file
    seen_follow = 0

    while True:
        now = time.time()
        if now > end:
            break
        try:
            data = s.recv(8192)
            if not data:
                log("(connection closed by server)")
                summ["errors"].append("server closed connection")
                break
        except socket.timeout:
            data = b""
        except Exception as e:
            summ["errors"].append("recv failed: %r" % (e,))
            break

        if data:
            buf += data.decode("utf-8", "replace")
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                if not line.strip():
                    continue
                log(line)
                if line.startswith("PING"):
                    send("PONG " + line.split(" ", 1)[1])
                    continue
                parts = line.split(" ")
                cmd = parts[1] if len(parts) > 1 and line.startswith(":") else parts[0]
                rest = " ".join(parts[2:])
                if cmd == "001":
                    registered = True
                    send("JOIN %s" % chan)
                elif cmd in ("471", "473", "474", "475", "477"):
                    summ["notices"].append("join refused: %s" % rest)
                    print("JOIN REFUSED: %s" % rest, flush=True)
                    break
                elif cmd == "353":
                    nicks = [n.lstrip("@+%~&") for n in rest.split(":")[-1].split()]
                    summ["human_nicks"] = sorted(set(summ["human_nicks"]) | set(nicks))
                elif cmd == "433":
                    nick_tries += 1
                    if nick_tries <= 3:
                        nick = nick + str(nick_tries)
                        send("NICK %s" % nick)
                    else:
                        summ["errors"].append("could not register any nick (433 x%d)" % nick_tries)
                        break
                elif cmd == "366":
                    summ["join_ok"] = True
                    if a.message:
                        send("PRIVMSG %s :%s" % (chan, a.message))
                        summ["send_ok"] = True
                    else:
                        print("joined %s as %s (no message)" % (chan, nick), flush=True)
                elif cmd == "KICK" and (" %s " % nick) in line:
                    summ["kicked"] = True
                    summ["notices"].append("KICK: %s" % rest)
                    print("KICKED: %s" % rest, flush=True)
                    break
                elif cmd == "PRIVMSG" and rest.startswith(chan + " "):
                    summ["messages_seen"] += 1
                    body = rest.split(":", 1)[-1]
                    who = line.split("!", 1)[0].lstrip(":")
                    if nick.lower() in body.lower():
                        summ["messages_mentioning_us"] += 1
                    if LINK_RE.search(body):
                        summ["lines_linking_to_us"] += 1
                    if not who.lower().startswith("agprobe"):
                        print("%s: %s" % (who, body), flush=True)
                elif cmd == "PRIVMSG" and nick in rest:
                    body = rest.split(":", 1)[-1]
                    who = line.split("!", 1)[0].lstrip(":")
                    summ["messages_mentioning_us"] += 1
                    print("(dm) %s: %s" % (who, body), flush=True)
                elif cmd == "NOTICE" and ("cannot" in rest.lower() or "error" in rest.lower()
                                          or "denied" in rest.lower()):
                    summ["notices"].append(rest.split(":", 1)[-1])

        # follow-up queue
        if follow_path and os.path.exists(follow_path):
            try:
                lines = [l.strip() for l in open(follow_path, encoding="utf-8").read().splitlines() if l.strip()]
            except Exception:
                lines = []
            if len(lines) > seen_follow and time.time() >= next_follow_ok:
                msg = lines[seen_follow]
                seen_follow = min(seen_follow + 1, len(lines))
                if registered and summ["join_ok"]:
                    send("PRIVMSG %s :%s" % (chan, msg))
                    next_follow_ok = time.time() + 20

    try:
        send("QUIT :probe complete")
    except Exception:
        pass
    try:
        s.close()
    except Exception:
        pass
    tg.close()

    summ["ended_at"] = ts()
    summ["human_nicks"] = [n for n in summ["human_nicks"] if not n.lower().startswith("agprobe")]
    out = os.path.join(DATA, "%s_summary.json" % a.out_prefix)
    json.dump(summ, open(out, "w"), indent=2, sort_keys=True)
    print("\n--- summary ---")
    print(json.dumps({k: v for k, v in summ.items() if k != "human_nicks"}, indent=2, sort_keys=True))
    print("transcript: %s" % tpath)
    print("summary:    %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
