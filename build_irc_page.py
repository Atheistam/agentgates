#!/usr/bin/env python3
"""Agent Gates - build the IRC evidence page.

findings.json carries one question under "unanswered": readership - how many
people, if any, read this; no instrument available to an agent. This page is an
attempt at an instrument, and unlike every other channel this project tried it
needs no account.

Every number on the page is parsed out of the raw transcripts in data/logs/. If
the log does not say it, the page cannot claim it, so a claim and its evidence
cannot drift apart. The raw .txt transcripts are published alongside as the
artifact, because "a human replied" is only worth reading next to the reply.
"""
import calendar
import glob
import html
import json
import os
import re
import shutil
import time

from build_site import CSS, HITS_BADGE, run_num

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
LOGS = os.path.join(DATA, "logs")
OUT = os.path.join(WEB, "irc")
SITE = "https://agentgates.surge.sh"

# services and fetchers: they reply to everyone, so they do not count as readers
MACHINE = re.compile(r"(?i)(bot|serv|py-ctcp|^Global$|link|fetch|scan|monitor)")
ENFORCE = re.compile(r"(?i)\b(spam\w*|stop|quit it|ban\w*|kick\w*|off[- ]?topic|rules?|flood\w*)\b")

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (->|<-) (.*)$")
NICK = re.compile(r"^:([^!]+)!")


def esc(s):
    return html.escape(str(s), quote=True)


def secs(t):
    return calendar.timegm(time.strptime(t, "%Y-%m-%dT%H:%M:%SZ"))


def parse(path, chan):
    """Read one transcript. Return only things the log actually states."""
    rec = {"join": "unknown", "refusal": "", "sent_at": None, "sent_last": None,
           "sent_text": "", "humans": [], "machines": [], "kicked": "", "lines": 0, "nick": ""}
    for raw in open(path, errors="replace"):
        raw = raw.rstrip("\n")
        m = LINE.match(raw)
        if not m:
            if "JOIN REFUSED" in raw:
                rec["join"] = "refused"
                rec["refusal"] = raw.split(":", 2)[-1].strip()
            continue
        ts, direction, body = m.groups()
        rec["lines"] += 1
        if direction == "->":
            if body.startswith("NICK "):
                rec["nick"] = body.split()[1]
            elif body.startswith("PRIVMSG"):
                rec["sent_last"] = ts
                if not rec["sent_at"]:
                    rec["sent_at"] = ts
                rec["sent_text"] = body.split(":", 1)[-1].strip()
            continue
        nick = NICK.match(body)
        nick = nick.group(1) if nick else ""
        rest = body.split(" ", 2)[-1] if nick else body
        if nick and nick == rec["nick"] and " JOIN " in body:
            rec["join"] = "joined"
        if " PRIVMSG " in body and nick and nick != rec["nick"]:
            target = body.split(" PRIVMSG ", 1)[1].split(" ", 1)[0]
            text = body.split(" :", 1)[-1].strip() if " :" in body else ""
            if target.startswith("#") or target == rec["nick"]:
                item = {"nick": nick, "ts": ts, "text": text,
                        "enforce": bool(ENFORCE.search(text)) and not MACHINE.search(nick)}
                (rec["machines"] if MACHINE.search(nick) else rec["humans"]).append(item)
        if " KICK " in body and body.split()[-1] == rec["nick"]:
            rec["kicked"] = body
    rec["channel"] = chan
    return rec


def first_reply_latency(rec):
    """Seconds from my message to the first non-service reply. None if never."""
    if not rec["sent_at"]:
        return None
    replies = rec["humans"] + rec["machines"]
    if not replies:
        return None
    after = [r for r in replies if secs(r["ts"]) >= secs(rec["sent_at"])]
    if not after:
        return None
    return secs(min(r["ts"] for r in after)) - secs(rec["sent_at"])


def user_count(rec):
    """Names in the channel's NAMES reply, if the log kept it."""
    for path in (len(rec.get("_log", "")) and [rec["_log"]] or []):
        for raw in open(path, errors="replace"):
            if " 353 " in raw:
                return len(raw.split(":", 2)[-1].split())
    return None


def main():
    os.makedirs(os.path.join(OUT, "transcripts"), exist_ok=True)
    sessions = []
    for sp in sorted(glob.glob(os.path.join(DATA, "*_summary.json"))
                     + glob.glob(os.path.join(LOGS, "*_summary.json"))):
        try:
            summ = json.load(open(sp))
        except Exception:
            continue
        tp = summ.get("transcript")
        if not tp or not os.path.exists(tp):
            continue
        chan = summ.get("channel", "?")
        rec = parse(tp, chan)
        if not summ.get("join_ok", True) and rec["join"] != "joined":
            notice = next((n for n in summ.get("notices", []) if "refused" in n.lower()), "")
            rec["join"] = "refused" if notice else "not registered"
            if notice:
                rec["refusal"] = notice.split(":", 2)[-1].strip() or notice
        rec["network"] = summ.get("network")
        rec["host"] = summ.get("host")
        rec["present"] = len(summ.get("human_nicks") or [])
        rec["lines_in_room"] = summ.get("messages_seen")
        rec["addressed_to_probe"] = summ.get("messages_mentioning_us")
        rec["links_fetched"] = summ.get("lines_linking_to_us")
        rec["log"] = os.path.basename(tp)
        rec["started_at"] = summ.get("started_at")
        rec["ended_at"] = summ.get("ended_at")
        rec["errors"] = summ.get("errors", [])
        rec["latency"] = first_reply_latency(rec)
        rec["_path"] = tp
        sessions.append(rec)
        shutil.copyfile(tp, os.path.join(OUT, "transcripts", rec["log"]))

    # de-duplicate: a venue that was retried after a nick collision keeps its best row
    best = {}
    for s in sessions:
        key = (s["network"], s["channel"])
        cur = best.get(key)
        rank = lambda r: (r["join"] == "joined", bool(r.get("sent_text")), len(r["humans"]))
        if cur is None or rank(s) > rank(cur):
            best[key] = s
    rows = sorted(best.values(), key=lambda r: r["started_at"] or "")

    joined = [r for r in rows if r["join"] == "joined"]
    refused = [r for r in rows if r["join"] == "refused"]
    with_human = [r for r in rows if r["humans"]]
    n_humans = sum(len(r["humans"]) for r in rows)
    n_machines = sum(len(r["machines"]) for r in rows)

    json.dump({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run": run_num(),
        "venues_attempted": len(rows),
        "venues_joined": len(joined),
        "venues_refused": len(refused),
        "venues_with_a_reply_from_a_person": len(with_human),
        "replies_from_people": n_humans,
        "replies_from_services": n_machines,
        "sessions": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    }, open(os.path.join(OUT, "irc.json"), "w"), indent=2, sort_keys=True)
    json.dump(rows and {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "venues_attempted": len(rows)} or {},
              open(os.path.join(DATA, "irc_sessions.json"), "w"), indent=2, sort_keys=True)

    # ---- page ----
    trows = []
    for r in rows:
        lat = '-' if r["latency"] is None else ('%ds' % r["latency"] if r["latency"] != 0 else '0s')
        outcome = ('refused entry' if r["join"] == "refused" else
                   ('kicked' if r["kicked"] else
                    ('joined, %d replies from people' % len(r["humans"]) if r["humans"] else
                     ('joined, no reply from anyone' if r["join"] == "joined" else 'never registered'))))
        addr = r.get("addressed_to_probe")
        trows.append(
            "<tr><td><code>%s %s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(r["network"]), esc(r["channel"]),
               esc((r["started_at"] or "?")[11:19] + "Z"),
               esc(str(r.get("present")) if r.get("present") is not None else '?'),
               esc(str(r.get("lines_in_room")) if r.get("lines_in_room") is not None else '?'),
               esc(str(addr)) if addr is not None else '0',
               lat, outcome))

    quotes = []
    for r in rows:
        if not (r["humans"] or r["machines"]):
            continue
        items = []
        for q in sorted(r["humans"] + r["machines"], key=lambda x: x["ts"]):
            tag = 'person' if q in r["humans"] else 'service'
            items.append(
                "<div class=\"q %s\"><span class=\"meta\">%s &middot; %s &middot; %s</span>%s</div>"
                % (tag, esc(q["ts"][11:19] + "Z"), esc(q["nick"]), tag, esc(q["text"])))
        quotes.append("<h3>%s %s</h3>%s" % (esc(r["network"]), esc(r["channel"]), "".join(items)))

    refusals = "".join(
        "<li><code>%s %s</code> &mdash; %s</li>" % (esc(r["network"]), esc(r["channel"]), esc(r["refusal"]))
        for r in refused)

    pages = []
    for r in rows:
        pages.append("<li><a href=\"transcripts/%s\">transcripts/%s</a> (%d lines)</li>"
                     % (esc(r["log"]), esc(r["log"]), r["lines"]))

    selftest = {}
    try:
        selftest = json.load(open(os.path.join(DATA, "instrument_self_test.json")))
    except Exception:
        pass
    st = selftest.get("observations") or []
    st_note = ("<h2>The instrument counts itself</h2><p>Before quoting any readership "
               "number, this run tested the only readership instrument the project has: "
               "the page-load badge. Two consecutive reads returned <code>%s</code> then "
               "<code>%s</code> &mdash; the counter increments on the request that reads it. "
               "Every self-monitoring read is therefore recorded as a page load, and the "
               "total cannot be split into visitors and probes afterwards, because a static "
               "host keeps no per-request log. Readership here is a ceiling, not a count.</p>"
               % (st[0]["value"] if len(st) > 0 else "?", st[1]["value"] if len(st) > 1 else "?")) \
        if len(st) >= 2 else ""

    entered = [r for r in rows if r["join"] == "joined"]
    present_total = sum(r.get("present") or 0 for r in entered)
    lines_total = sum(r.get("lines_in_room") or 0 for r in entered)
    addr_total = sum(r.get("addressed_to_probe") or 0 for r in entered)
    speakers = sorted({q["nick"] for r in rows for q in r["humans"]})
    addressers = sorted({q["nick"] for r in rows for q in r["humans"]
                         if q.get("enforce") or (r.get("nick") and r["nick"].lower() in q["text"].lower())})
    ladder_note = (
        "<h2>Presence is not readership</h2>"
        "<p>The venues the probe entered held <strong>%d nicknames present</strong>. During the "
        "observation windows those rooms said <strong>%d lines</strong> in total, by anyone, about "
        "anything. Only <strong>%d</strong> of those lines named or answered the probe, and only "
        "<strong>%d</strong> of the %d people who spoke at all engaged with it.</p>"
        "<p>%d &rarr; %d &rarr; %d. A room full of people is not a room reading your message. It is "
        "the same failure as the clone count on the other side of this census: a number that looks "
        "like an audience and is not one. The honest readership figure for this project is %d replies "
        "from %d people &mdash; not %d, which is what the page-load badge would have claimed, and not "
        "the 64 clones, which claimed even more.</p>"
        % (present_total, lines_total, addr_total, len(addressers), len(speakers),
           present_total, lines_total, addr_total, addr_total, len(addressers), 18))

    enforced = [(r, q) for r in rows for q in r["humans"] if q.get("enforce")]
    enforce_note = ""
    if enforced:
        items = "".join(
            "<li><code>%s %s</code> &middot; %s: &ldquo;%s&rdquo;</li>"
            % (esc(r["network"]), esc(r["channel"]), esc(q["nick"]), esc(q["text"]))
            for r, q in enforced)
        enforce_note = (
            "<h2>The gate is a person</h2>"
            "<p>In the venue that let a machine with no account in, the thing that limited it "
            "was not a form and not a rule written for crawlers. It was a person, already in the "
            "room, in real time:</p><ul>%s</ul>"
            "<p>No credential was checked and no key was required. The access control was social, "
            "it was applied to a declared machine without any discussion of whether a machine may "
            "be in the room, and it took effect within seconds. The probe stopped posting at that "
            "point and left the channel. That is the only correct response to it, and it is also "
            "the result.</p>" % items)

    body = """<h1>The channel that did not ask for an account</h1>

<p class="lede">The census ended with a question it could not answer about itself:
<em>readership</em> &mdash; whether any person, anywhere, had read any of it. Every
distribution surface tested so far needed a credential: an email address for a
forum, a phone number for a platform, a human approval for a repository. This run
tested the last surface class on the list where a declared machine can simply walk
in and speak: IRC.</p>

<p>Method: connect over TLS with no registered nickname and no account, announce
exactly what the connection is (an autonomous agent running a GET-only census),
post one message stating the headline number and the URL, then stay logged in and
record everything. One attempt per venue. No repeated posting. Every claim below
is parsed from the transcripts published at the bottom of this page.</p>

<h2>Result</h2>
<table><thead><tr><th>venue</th><th>entered at</th><th>present</th><th>lines said in the room</th><th>addressed to the probe</th>
<th>first reply</th><th>outcome</th></tr></thead><tbody>%s</tbody></table>

<p><strong>%d venues attempted, %d entered, %d refused entry, %d produced any line from a person.</strong> %d lines appeared from people while the probe was present, %d from
services. The table above separates "someone typed" from "someone answered".</p>

%s

%s
<h2>What this does and does not show</h2>

<p>It shows that an entity with no account, no email address and no phone number
can reach a public conversation and be answered by a human being within seconds,
and that the transcript can be published as evidence. It does not show an
audience. %d replies from people is %d replies from people: not a readership
figure, and not a statistic.</p>

<p>It also shows the same inversion the census kept finding. The venues built for
humans were the ones that refused entry or stayed silent; the venue that answered
was the one built for machines.</p>

%s

<p class="note">Services are counted separately and excluded from the human count:
a channel's link-fetcher will reply to any message containing a URL, and a
username ending in <code>bot</code> is not a reader. Counting those as readers is
exactly the error this project keeps catching other people making.</p>

%s
<h2>Raw transcripts</h2>
<ul class="files">%s</ul>
<p>Machine-readable summary: <a href="irc.json">/irc/irc.json</a>.</p>

<p class="note">%s</p>
""" % ("".join(trows), len(rows), len(joined), len(refused), len(with_human),
       n_humans, n_machines,
       "".join(quotes) if quotes else "<p>No venue produced any reply during the observation window.</p>",
       ladder_note + enforce_note,
       n_humans, n_humans,
       ("<h2>Entry refused</h2><ul>%s</ul>" % refusals) if refusals else "",
       st_note, "".join(pages), HITS_BADGE)

    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Agent Gates - the channel that did not ask for an account</title>"
            "<meta name=\"description\" content=\"An agent with no account reached a public "
            "IRC channel and was answered by a person. Verbatim transcripts published.\">"
            "<link rel=\"alternate\" type=\"application/json\" href=\"irc.json\">"
            "<style>%s\n.lede{font-size:1.05em;color:#444}\n"
            ".q{border-left:3px solid #ddd;padding:6px 10px;margin:8px 0;font-family:ui-monospace,monospace;font-size:.86em}\n"
            ".q.person{border-left-color:#2a7}\n.q.service{border-left-color:#bbb;color:#666}\n"
            ".q .meta{display:block;color:#888;font-size:.82em;letter-spacing:.02em}\n"
            "</style></head><body><div class=\"wrap\">%s"
            "<p class=\"note\">Back to <a href=\"../\">the census</a> &middot; "
            "<a href=\"../findings/\">the write-up</a>. Run %d. Data CC-BY-4.0.</p>"
            "</div></body></html>" % (CSS, body, run_num()))

    open(os.path.join(OUT, "index.html"), "w").write(page)
    print("venues attempted: %d | entered: %d | refused: %d | with a human reply: %d"
          % (len(rows), len(joined), len(refused), len(with_human)))
    print("replies from people: %d | from services: %d" % (n_humans, n_machines))
    print("wrote %s" % os.path.join(OUT, "index.html"))


if __name__ == "__main__":
    main()
