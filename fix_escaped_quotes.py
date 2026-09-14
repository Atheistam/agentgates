#!/usr/bin/env python3
"""Repair over-escaped quotes in the reach-page HTML literals.

The file is written in the usual style "text with \\" inside it": inside a Python string
literal a double quote is escaped by exactly one backslash. Earlier patches (this run and a
previous one) left runs of two or three backslashes before those quotes, which reach the
browser as literal backslashes: class=\\"note\\". A correction must also fire on substrings
of longer runs, so this uses a regex over runs of 2+ backslashes followed by a quote, and
prints the exact run lengths it finds before changing anything."""

import io
import re
import sys

PATH = "build_reach_correction.py"
BS = chr(92)
RUN = re.compile(re.escape(BS) + r'{2,}"')

src = io.open(PATH, encoding="utf-8").read()

for m in RUN.finditer(src):
    line_no = src.count("\n", 0, m.start()) + 1
    print("line %d: run of %d backslashes before a quote" % (line_no, len(m.group(0)) - 1))

if "--fix" not in sys.argv:
    print("dry run - pass --fix to repair")
    raise SystemExit(0)

fixed = RUN.sub(BS + '"', src)
io.open(PATH, "w", encoding="utf-8").write(fixed)
after = io.open(PATH, encoding="utf-8").read()
print("remaining over-escaped runs:", len(RUN.findall(after)))
print("runs of 3+ backslashes anywhere:", len(re.findall(re.escape(BS) + r'{3,}', after)))
