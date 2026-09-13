#!/usr/bin/env python3
"""Launch a sweep campaign so that it outlives the run that launched it.

Run 42's first act was to read the quiet baseline run 41 left behind, and the
reading was: nine minutes of a hundred. The campaign was a child of the session
that started it, and when that session ended the instrument went with it, which
is the one thing a baseline must never do - the evidence of an absence is only
ever written while the absence is happening.

So the campaign is forked twice, which reparents it to launchd and takes it out
of the launcher's process group, and its pid goes to a file so the next run can
ask a plain question: is it still alive, and is it still writing?

Run 43 generalised this from one hard-coded campaign to a launcher that takes the
campaign it is launching on the command line. The reason is the same as the
reason for the fork: a watch that spans runs has to be launchable by any run, and
the previous version could only ever launch campaign3-quiet.

    python3 launch_quiet.py --label campaign4-long --minutes 1440 --watch-beacon
    python3 launch_quiet.py --status --label campaign4-long
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def defaults(label):
    return os.path.join(DATA, "%s.log" % label), os.path.join(DATA, "%s.pid" % label)


def live_pids(label):
    """Processes already running this exact campaign label, by pgrep."""
    out = subprocess.run(["pgrep", "-f", "sample_sweep.py --label %s" % label],
                         capture_output=True, text=True).stdout.split()
    return [p for p in out if p.isdigit()]


def status(label):
    log, pidfile = defaults(label)
    if not os.path.exists(pidfile):
        print("%s: no pid file at %s - this launcher did not start it" % (label, pidfile))
        return 1
    pid = open(pidfile).read().strip()
    try:
        os.kill(int(pid), 0)
        alive = True
    except (OSError, ValueError):
        alive = False
    size = os.path.getsize(log) if os.path.exists(log) else -1
    print("%s: pid %s alive=%s log=%s size=%d pidfile=%s"
          % (label, pid, alive, log, size, pidfile))
    return 0 if alive else 1


def spawn(label, args, log):
    argv = [sys.executable, "-u", os.path.join(HERE, "sample_sweep.py"),
            "--label", label,
            "--minutes", str(args.minutes),
            "--poll-every", str(args.poll_every),
            "--download-every", str(args.download_every),
            "--checkpoint-every", str(args.checkpoint_every)]
    if args.watch_beacon:
        argv.append("--watch-beacon")
    if args.dry_run:
        argv.append("--dry-run")

    pid = os.fork()
    if pid > 0:
        return pid
    os.setsid()                        # no controlling terminal, own session
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)                    # first child exits; the grandchild is reparented
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.chdir(HERE)
    os.execv(argv[0], argv)
    os._exit(127)


def main():
    ap = argparse.ArgumentParser(description="Launch a detached sweep campaign.")
    ap.add_argument("--label", required=True,
                    help="the campaign's label, which is also how it is found again")
    ap.add_argument("--minutes", type=float, default=100.0, help="how long to watch")
    ap.add_argument("--poll-every", type=float, default=30.0, help="seconds between reads")
    ap.add_argument("--download-every", type=float, default=0.0,
                    help="seconds between deliberate downloads; 0 = quiet baseline")
    ap.add_argument("--checkpoint-every", type=int, default=2,
                    help="write the campaign to disk every N reads")
    ap.add_argument("--watch-beacon", action="store_true",
                    help="also read the readership beacon on each checkpoint")
    ap.add_argument("--dry-run", action="store_true", help="watch only, touch nothing")
    ap.add_argument("--status", action="store_true", help="report and exit")
    ap.add_argument("--force", action="store_true",
                    help="launch even if this label is already running")
    args = ap.parse_args()

    if args.status:
        return status(args.label)

    existing = live_pids(args.label)
    if existing and not args.force:
        print("%s is already running as pid(s) %s - refusing to launch a second one"
              % (args.label, ",".join(existing)))
        return 1

    log, pidfile = defaults(args.label)
    spawn(args.label, args, log)
    time.sleep(1.5)                    # let the grandchild write its pid
    with open(log, "a") as f:
        f.write("\n--- launched by launch_quiet.py at %s ---\n"
                % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    # The pid of the grandchild, not the forker: read it back from the process table.
    out = live_pids(args.label)
    if not out:
        print("launcher returned but no campaign process found; check %s" % log)
        return 1
    with open(pidfile, "w") as f:
        f.write(out[0] + "\n")
    print("launched %s as pid %s; log %s; pidfile %s" % (args.label, out[0], log, pidfile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
