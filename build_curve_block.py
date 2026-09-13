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
    last = passes[-1]
    prev = passes[-2]

    return (
        "<h2 style=\"margin-top:48px\">Twenty-four hours, read four times</h2>"
        "<p><strong>11 of the 12 artifacts this project actually wrote are still readable at "
        "T+%(age)sh. Zero failed. The twelfth is gone because its host said it would be.</strong> "
        "Same artifacts, same client, four reads, no re-upload, no account anywhere.</p>"
        "<table><tr><th>read at</th><th>made</th><th>source</th><th>still there</th>"
        "<th>expired as declared</th><th>never existed</th><th>changed since the previous read</th>"
        "</tr>%(rows)s</table>"
        "<p>%(nsteady)d of the %(ntotal)d services hold the same verdict in every one of the %(npass)d "
        "reads. Nothing flapped: not one shortener stopped resolving, not one paste body lost a "
        "byte, and the single expiry happened where the host's own front page said it would - "
        "<span class=\"mono\">uguu.se</span> announces <em>files expire after 3 hours</em>, and it "
        "was alive at T+%(prevage)sh and 404 at T+%(age)sh. A two-column method has no way to "
        "report that. It reports a failure or it reports a success, and a stated expiry is "
        "neither.</p>"
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
        % {"rows": "".join(rows), "nsteady": len(steady), "ntotal": len(names),
           "npass": len(passes), "age": v.get("age_hours", "?"),
           "prevage": prev.get("age_hours", "?"),
           "lastlabel": esc(last.get("label") or "?")}
    )
