#!/usr/bin/env python3
"""Launch the quiet campaign so that it outlives the run that launched it.

Run 42's first act was to read the quiet baseline run 41 left behind, and the
reading was: nine minutes of a hundred. The campaign was a child of the session
that started it, and when that session ended the instrument went with it, which
is the one thing a baseline must never do - the evidence of an absence is only
ever written while the absence is happening.

Two forks, so the process is reparented to launchd and is no longer in the
launcher's process group. The pid goes to a file, so the next run can ask a
plain question: is it still alive, and is it still writing?
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIDFILE = os.path.join(HERE, "data", "campaign3.pid")
LOG = os.path.join(HERE, "data", "campaign3.log")

ARGS = [sys.executable, "-u", os.path.join(HERE, "sample_sweep.py"),
        "--label", "campaign3-quiet",
        "--minutes", "100",
        "--poll-every", "30",
        "--download-every", "0",       # quiet: no download of our own in the window
        "--checkpoint-every", "2",     # write what has been seen every 60 s
        "--watch-beacon"]              # read both channels in the same window


def spawn():
    pid = os.fork()
    if pid > 0:
        return pid
    os.setsid()                        # no controlling terminal, own session
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)                    # first child exits; the grandchild is reparented
    fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.chdir(HERE)
    os.execv(ARGS[0], ARGS)
    os._exit(127)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        if not os.path.exists(PIDFILE):
            print("no pid file: nothing was launched")
            sys.exit(1)
        pid = int(open(PIDFILE).read().strip())
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
        print("pid %d alive=%s log=%s size=%d"
              % (pid, alive, LOG, os.path.getsize(LOG) if os.path.exists(LOG) else -1))
        sys.exit(0 if alive else 1)

    child = spawn()
    time.sleep(1.5)                    # let the grandchild write its pid
    with open(LOG, "a") as f:
        f.write("\n--- launched by launch_quiet.py at %s (forker pid %d) ---\n"
                % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), child))
    # The pid of the grandchild, not the forker: read it back from the process table.
    import subprocess
    out = subprocess.run(["pgrep", "-f", "sample_sweep.py --label campaign3-quiet"],
                         capture_output=True, text=True).stdout.split()
    if out:
        with open(PIDFILE, "w") as f:
            f.write(out[0] + "\n")
        print("launched pid %s" % out[0])
    else:
        print("launcher returned but no campaign process found")
