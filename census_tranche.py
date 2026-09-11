"""Agent Gates - tranche 2 census (Tranco ranks 201-500).

Runs the SAME content-validated standards census as probe_standards.py, but against
a second, independent sample of domains: Tranco ranks 201-500 rather than the top 200.

WHY THIS EXISTS
    Run 31's headline numbers (robots.txt 47.0%, AI-crawler rules 16.0%, key directory
    1/200 spec-shaped, llms.txt 10.5%) are single-point estimates on one sample of 200
    domains. One sample cannot distinguish "the deployment rate is X" from "this
    particular draw of 200 domains happened to contain X%". This script measures the
    next 300 ranks so the headline can be published with a stability band.

WHAT THIS DOES *NOT* PROVE
    Tranche 2 is NOT a random sample of the internet. It is the next 300 domains by
    traffic rank, which is a biased, heavy-tailed population (large platforms, CDNs,
    regional portals). The two tranches are also drawn from different Tranco list
    snapshots (Tranco regenerates the list daily), so tranche 2 is "an independent
    draw from the same ranked-list family", not the same list at a different offset.
    Agreement between tranches bounds *sampling* noise on this population; it does not
    license a claim about the web as a whole.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import probe_standards  # noqa: E402

NOTE = (
    "Tranche 2 = Tranco ranks 201-500, drawn 2026-09-11 from the same Tranco list "
    "family as tranche 1 but from a different daily list snapshot (Tranco regenerates "
    "daily; audit on 2026-09-11 found 199/200 of tranche 1's domains still present in "
    "today's top 200, so the drift is small but non-zero). Tranche 2 is an independent "
    "sample on the same biased population (top-traffic domains), NOT a random sample "
    "of the web."
)


def main():
    argv = [
        "--domains", os.path.join(HERE, "data", "tranche2_domains.txt"),
        "--out-prefix", "standards_census_t2",
        "--tranche-note", NOTE,
    ]
    print("== tranche 2 census (ranks 201-500) ==")
    rc = probe_standards.main(argv)
    # stamp the tranche block properly
    import json
    p = os.path.join(HERE, "data", "standards_census_t2.json")
    with open(p) as f:
        out = json.load(f)
    out["tranche"] = {
        "tranche": 2,
        "rank_range": "201-500",
        "source": "Tranco (https://tranco-list.eu), list id resolved at run time",
        "note": NOTE,
    }
    with open(p, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote %s" % p)
    return rc


if __name__ == "__main__":
    sys.exit(main())
