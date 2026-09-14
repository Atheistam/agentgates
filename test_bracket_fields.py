#!/usr/bin/env python3
"""Does the patched instrument actually store the bracket? Run 45.

The audit found that the read before a movement - the one value that turns a change row into
a bracket, and the value campaign4-long's beat ring threw away 1740 times - was stored
nowhere. The patch writes it. A patch that has not been run is a claim, so this drives
sample_sweep.main() end to end with a scripted counter and a frozen clock, and asserts on the
campaign that comes out the other side.

It touches nothing: the writer is replaced before the campaign starts, so
data/sweep_samples.json is not opened for writing and the live campaign's record is untouched.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sample_sweep as ss  # noqa: E402

BASE = 1789000000.0  # fixed; the clock only moves when the loop sleeps
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("   [%s]" % detail) if detail else ""))


class FrozenClock(object):
    """Stands in for the `time` module inside sample_sweep, so a ten-minute campaign runs in
    milliseconds and every interval is exact. time.sleep advances the clock instead of
    waiting, which means the bracket asserted below is the instrument's own arithmetic and not
    a measurement of how fast this machine happened to be."""

    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, seconds)


def fake_utc_for(clock):
    def utc():
        return datetime.fromtimestamp(clock.t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return utc


def run_scripted(counts, poll_every=30.0, minutes=10.0, checkpoint_every=10):
    """One full campaign against a scripted counter. Returns (final, every write seen)."""
    clock = FrozenClock(BASE)
    seq = list(counts)

    def fake_read_count(token):
        # The counter answers from the script, holding its last value once the script is spent,
        # so the length of the campaign cannot change what the campaign saw.
        value = seq.pop(0) if len(seq) > 1 else seq[0]
        return value, None

    writes = []
    saved = (ss.time, ss.utc, ss.read_count, ss._write, ss.pc.gh_token)
    ss.time = clock
    ss.utc = fake_utc_for(clock)
    ss.read_count = fake_read_count
    ss._write = lambda label, campaign: writes.append(json.loads(json.dumps(campaign)))
    ss.pc.gh_token = lambda: "scripted-token-so-the-poll-interval-is-not-raised"
    argv = sys.argv
    sys.argv = ["sample_sweep.py", "--label", "selftest-run45", "--minutes", str(minutes),
                "--poll-every", str(poll_every), "--download-every", "0",
                "--checkpoint-every", str(checkpoint_every)]
    try:
        rc = ss.main()
    finally:
        sys.argv = argv
        ss.time, ss.utc, ss.read_count, ss._write, ss.pc.gh_token = saved
    return rc, (writes[-1] if writes else None), writes


def columns(campaign):
    """The pair of gaps a reader of a change row has to tell apart: how long the number had
    held at its old value (the bracket) and how long since the last movement (gap_s)."""
    out = []
    for r in campaign["rows"]:
        out.append((r.get("at"), r.get("count"), r.get("delta"),
                    r.get("prev_read_at"), r.get("bracket_s"), r.get("gap_s")))
    return out


def main():
    samples = os.path.join(HERE, "data", "sweep_samples.json")
    before = os.stat(samples).st_mtime, os.stat(samples).st_size

    # 12, 12, then 13: one movement, one read that still saw the old value before it.
    rc, final, writes = run_scripted([12, 12, 13, 13, 14])
    print("\n--- campaign with two movements ---")
    for row in columns(final):
        print("   at=%s count=%s delta=%s prev_read_at=%s bracket_s=%s gap_s=%s" % row)
    print("")

    check("the campaign stored something", final is not None and rc in (0, None),
          "rc=%s" % rc)
    check("it polled more than five times", final["polls"] >= 5, "polls=%s" % final["polls"])

    rows = final["rows"]
    check("the first row is the baseline, not a movement",
          rows[0].get("delta") is None and rows[0].get("prev_read_at") is None)
    check("no row anywhere claims a bracket that was never read",
          all(r.get("prev_read_at") for r in rows[1:]),
          "rows without prev_read_at: %s" % [r.get("at") for r in rows[1:] if not r.get("prev_read_at")])

    moves = [r for r in rows if r.get("delta")]
    check("both movements were recorded", len(moves) >= 2, "movements=%d" % len(moves))
    if moves:
        m = moves[0]
        check("the first movement carries the read before it", bool(m.get("prev_read_at")),
              "prev_read_at=%s" % m.get("prev_read_at"))
        check("its bracket is one poll interval", m.get("bracket_s") == 30.0,
              "bracket_s=%s" % m.get("bracket_s"))
        check("it does not borrow the time since the previous change as its bracket",
              m.get("gap_s") is None or m.get("gap_s") != m.get("bracket_s"),
              "gap_s=%s" % m.get("gap_s"))
    if len(moves) >= 2:
        m2 = moves[1]
        check("the second movement keeps the two intervals apart",
              m2.get("gap_s") == 60.0 and m2.get("bracket_s") == 30.0,
              "gap_s=%s bracket_s=%s" % (m2.get("gap_s"), m2.get("bracket_s")))

    check("a finished campaign says that it finished",
          final.get("ended_at_kind") == "final write, the watch reached its deadline",
          "ended_at_kind=%r" % final.get("ended_at_kind"))
    check("the campaign remembers its last read", bool(final.get("last_read_at")),
          "last_read_at=%r" % final.get("last_read_at"))

    checkpoint_kinds = set(w.get("ended_at_kind") for w in writes[:-1])
    check("a write made mid-campaign says the campaign was still watching",
          checkpoint_kinds == {"checkpoint, campaign still watching"},
          "kinds seen in %d mid-campaign writes: %s" % (len(writes) - 1, checkpoint_kinds))
    check("the live write and the final write are not the same kind",
          len(set(w.get("ended_at_kind") for w in writes)) == 2,
          "%s" % set(w.get("ended_at_kind") for w in writes))

    # A campaign that produced no movement at all still has to survive as a readable record.
    rc2, quiet, writes2 = run_scripted([19, 19, 19, 19, 19, 19], minutes=4.0)
    check("a campaign that saw nothing stores a baseline row and a final write",
          rc2 in (0, None) and len(quiet["rows"]) == 1 and quiet["rows"][0].get("delta") is None
          and quiet["ended_at_kind"] == "final write, the watch reached its deadline",
          "rows=%d kind=%r" % (len(quiet["rows"]), quiet.get("ended_at_kind")))

    after = os.stat(samples).st_mtime, os.stat(samples).st_size
    check("the live record was not opened or written", before == after,
          "before=%s after=%s" % (before, after))

    failed = [n for n, ok in RESULTS if not ok]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
    if failed:
        for n in failed:
            print("  FAILED: %s" % n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
