#!/usr/bin/env python3
"""Pull the client-side upload contract out of a minified bundle.

The bundle is one giant line, so ripgrep-style line output is useless. Print a
window of characters around every hit instead.
"""
import re
import sys

path = sys.argv[1]
needle = sys.argv[2]
width = int(sys.argv[3]) if len(sys.argv) > 3 else 120
src = open(path, encoding="utf-8", errors="replace").read()
print("bundle chars:", len(src))
seen = set()
for m in re.finditer(re.escape(needle), src):
    a = max(0, m.start() - width)
    b = min(len(src), m.end() + width)
    frag = src[a:b].replace("\n", " ")
    if frag in seen:
        continue
    seen.add(frag)
    print("\n---", m.start(), "---\n" + frag)
    if len(seen) >= 12:
        break
print("\nhits:", len(seen))
