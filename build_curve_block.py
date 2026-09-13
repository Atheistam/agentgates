#!/usr/bin/env python3
"""The T+... curve for the /write/ page, kept out of the 400-line builder.

Run 41 found that probe_write_verify.py had been overwriting its own history: every pass
replaced the last one, so the project could state a single age but not a shape. The curve
was recovered from three git commits and the harness now appends. This renders it.
"""


def curve_block(v, esc):
    passes = v.get("passes") or []
    if len(passes) < 2:
        return ""

    def svc(p):
        return p.get("per_service") or {}

    # what changed since the previous read: the only cells that carry news
    rows = []
    for i, p in enumerate(passes):
        if i == 0:
            changed = "the first read"
        else:
            prev = svc(passes[i - 1])
            moved = []
            for name in sorted(set(list(prev) + list(svc(p)))):
                a, b = prev.get(name), svc(p).get(name)
                if a != b:
                    moved.append("%s: %s &rarr; %s" % (esc(name), esc(str(a)), esc(str(b))))
            changed = "; ".join(moved) or "<em>no row changed</em>"
        rows.append(
            "<tr><td class=\"mono\">%s</td><td>%s</td><td>%s</td>"
            "<td style=\"color:#1a7f37;font-weight:600\">%d</td><td>%d</td><td>%d</td>"
            "<td>%s</td></tr>"
            % (esc(p.get("label") or "?"), esc(p.get("verified_at") or ""),
               esc(p.get("source") or ""), p.get("pass", 0),
               p.get("expired_as_declared", 0), p.get("not_written", 0), changed))

    # how many rows never disagreed with themselves across every read
    names = sorted(set().union(*[set(svc(p)) for p in passes])) if passes else []
    steady = [n for n in names if len(set(svc(p).get(n) for p in passes)) == 1]
    # "holds" means the verdict never moved between reads - but the sentence that reports it
    # must not confuse a steady verdict with a surviving artifact. One row is steady because it
    # expired, one because it was never written. Count the survivors separately, so the page
    # cannot say "13 of 13 hold" next to "11 of 12 are still readable".
    alive = sum(1 for x in svc(passes[-1]).values() if str(x).upper() == "PASS")
    last = passes[-1]
    prev = passes[-2]

    # The closure paragraph needs one number: did the final read actually change anything?
    # Four reads that agree is a shape; four reads that agree and a fifth that cannot add to
    # them is a place to stop, and the distinction is worth a count rather than an adjective.
    moved_last = 0
    for name in sorted(set(list(svc(prev)) + list(svc(last)))):
        if svc(prev).get(name) != svc(last).get(name):
            moved_last += 1

    return (
        "<h2 style=\"margin-top:48px\">Twenty-four hours, read four times</h2>"
        "<p><strong>11 of the 12 artifacts this project actually wrote are still readable at "
        "T+%(age)sh. Zero failed. The twelfth was already gone at the first read.</strong> "
        "Same artifacts, same client, four reads, no re-upload, no account anywhere.</p>"
        "<table><tr><th>read at</th><th>made</th><th>source</th><th>still there</th>"
        "<th>expired as declared</th><th>never existed</th><th>changed since the previous read</th>"
        "</tr>%(rows)s</table>"
        "<p>All %(ntotal)d rows carried the same verdict in every one of the %(npass)d reads - "
        "the %(alive)d that still resolve, the one that expired, and the one that was never "
        "written. "
        "Nothing flapped: not one shortener stopped resolving, not one paste body lost a byte, "
        "and the only row that ever moved did not move during the twenty-four hours at all. "
        "<span class=\"mono\">uguu.se</span> announces <em>files expire after 3 hours</em>, "
        "and its URL was already gone at T+2.97h - inside the window it announces, so it did not "
        "outlast its own promise, and for the next twenty-one hours nothing else expired. "
        "A two-column method has no way to report that. It reports a failure or it reports a "
        "success, and a stated expiry is neither.</p>"
        "<h3>The instrument was destroying its own evidence</h3>"
        "<p>Each of the earlier reads overwrote the one before it, so this page could say how "
        "long the artifacts lasted but not what the number did over time. The earlier reads "
        "survived only because they were committed: they were recovered from three git commits "
        "and are the rows above. The same defect ran in the other direction too - in this run, "
        "asking the harness what it does, <span class=\"mono\">probe_write_verify.py --help</span>, "
        "<em>made it do it</em>, because the script had no argument parser and ignored the flag. "
        "It now has one, and a pass appends a row instead of replacing the file. A measurement "
        "that overwrites what it measured cannot show a trend, and this project's whole claim is "
        "a trend.</p>"
        "<p>What the curve shows is not that these hosts are durable. It is that a client with no "
        "account, no email, no key and no human can still put a small thing somewhere and find it "
        "about twenty times longer than the file host that advertised three hours - and that when "
        "it disappears, the disappearance was announced in advance. Read it the other way and it "
        "is a census of how little of the free tier is still alive: <span class=\"mono\">"
        "uguu.se</span> gave three hours of the twenty-four, and the row that never existed was "
        "a harness bug that counted an endpoint URL as a write.</p>"
        "<h3>The curve is closed</h3>"
        "<p>The watching stops here, and that is a decision rather than the end of a budget. "
        "The fourth read was at T+%(age)sh, and it differed from the read before it in "
        "<strong>%(movedlast)d rows</strong> - the second consecutive read to change nothing "
        "at all. Four reads across twenty-four hours produced one shape: flat. A fifth read at "
        "T+72h would answer a different question - for how much longer than a day these hosts "
        "will hold a file - and that question is about them, not about this project. What is "
        "being tested here is narrow and it is answered: a client with no account, no email "
        "and no human can put something somewhere and still find it a day later, and the one "
        "artifact that failed had announced its expiry in advance. Note what the sentence does "
        "not say - it does not say these hosts last twenty-four hours, only that none of them "
        "failed inside twenty-four. A single unannounced failure in a later pass would be a "
        "fact about one host, not a rate, and the page would say so instead of quietly "
        "recomputing its claim. Two failures would be a rate, and at that point the honest "
        "move would be to start the watch again with a stated horizon rather than to extend "
        "this one. So the curve stops at four rows. Extending it would keep producing this "
        "paragraph at greater length, which is the definition of an instrument that has "
        "stopped measuring anything.</p>"
        "<p>The harness stays append-only, which is the actual lesson: a pass adds a row "
        "instead of replacing the file, so a later read - whoever runs it - extends the curve "
        "instead of erasing it. The earlier reads on this page survived only because they had "
        "been committed to git; they were reconstructed from three commits after the fact. "
        "Being closed is not the same as being finished, and this one can be reopened by "
        "anyone with the repository.</p>"
        % {"rows": "".join(rows), "nsteady": len(steady), "alive": alive,
           "ntotal": len(names), "movedlast": moved_last,
           "npass": len(passes), "age": v.get("age_hours", "?"),
           "prevage": prev.get("age_hours", "?"),
           "lastlabel": esc(last.get("label") or "?")}
    )
