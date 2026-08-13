#!/usr/bin/env python3
"""Stress the signal-delivery race behind test_print_exception_gh_102056.

The child script is the one from
``lib-python/3/test/test_threading.py::test_print_exception_gh_102056``: a
runaway recursion whose RecursionError handler recurses again, inside an
``except* ValueError``, while a second thread calls ``_thread.interrupt_main()``
after a delay.  When the pending SIGINT is destroyed instead of delivered the
child spins forever on one core with an empty stderr.

The failure is a race, so a single run proves nothing.  This script runs the
child many times, under knobs that shift the race window, and reports a hang
rate per configuration with a Wilson confidence interval.

Two rules the measurements depend on:

* the child is launched exactly the way ``test.support.script_helper`` launches
  it (``-X faulthandler -I -c <script>``, script text parsed out of the test
  file rather than hand-copied) -- a copy in a *file* has a completely
  different timing regime and a different hang rate;
* when several binaries, delays or recursion limits are given they are
  interleaved run for run, because the absolute rate drifts with machine load.
  A rate measured for A at 10:00 and for B at 10:30 is not a comparison.

Recommended invocation -- the settings below were the most productive of the
ones measured (see "what moves the rate")::

    stress_signal_delivery.py --pypy old=.../pypy3 --pypy new=.../pypy3 \\
        --reps 20 --recursion-limit 20000 --delay 0.92 --jitter 0.08

what moves the rate
-------------------

Measured on an 8-core box against a build that already carries the
"re-arm on StackOverflow out of report_signal" fix:

* ``--recursion-limit``: the big one.  At the stock limit of 1000 the run is
  almost unreproducible (0/36 idle); raising it to 20000 takes the same binary
  to roughly 55%.  20000, 50000 and 200000 are indistinguishable (4/6 each,
  interleaved), so anything well above the default will do.
* ``--delay``: strong, and near-deterministic per delay -- individual delays
  measure anywhere from 0% to 100%.  The catch is that the peak is only about
  0.04s wide and moves between sessions, because it is really a proxy for how
  far the child has got.  Do not chase it; ``--jitter`` samples the whole band
  and gives a rate that reproduces.  Outside roughly 0.85-1.05 the rate falls
  to zero.
* ``--taskset``: a strong amplifier *at the stock recursion limit* (0/36
  unpinned vs 12/20 pinned).  Once the limit is raised it stops helping and
  mildly hurts (pinned 5/12 vs unpinned 9/12), so the recommended
  configuration does not use it.

Knobs that were measured and do nothing, or actively suppress the failure:

* ``--load``: no effect unpinned (0/10 with 6 spinners).  Sharing the pinned
  core with the load *suppresses* it (0/10).  Do not use it.
* ``--interrupts``: repeated interrupts suppress the hang (0/8), and they must
  -- the whole failure is that one signal is destroyed, so a later one simply
  gets delivered and the child dies as it should.  Useful as a control, not as
  an aggravator.
* ``--threads``: 4 extra idle threads, 1/8 versus 4/8 for the control.
* ``PYPY_GC_NURSERY``: 2/8 versus 4/8 for the control, i.e. nothing.
* ``--jit off``: 3/6, i.e. the same rate, but a non-hanging run takes 3.8s
  instead of 1.8s, so it doubles the cost of a sweep and needs a longer
  ``--watchdog``.  Not worth it, though it does say the race is not a JIT
  artefact.
* a *lowered* recursion limit (1000 or 2000) reliably hides the bug.

A run that does not hang finishes in under 2s (under 4s with ``--jit off``);
one that hangs never finishes -- checked out to a 30s watchdog, where every
non-hang was still under 1.9s.  There is no in-between, so ``--watchdog 8`` is
generous and costs nothing in false positives.  A hang has *exactly* zero bytes
of stderr and a delivered interrupt has about 3.3MB of traceback, so the two
outcomes are never ambiguous.
"""

import argparse
import ast
import itertools
import json
import math
import os
import random
import signal
import subprocess
import sys
import threading
import time

TEST_FILE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "lib-python", "3", "test", "test_threading.py"))

TEST_METHOD = "test_print_exception_gh_102056"

# Outcomes of one child run.
HANG = "hang"       # watchdog had to SIGKILL it
KBI = "kbi"         # KeyboardInterrupt reached the traceback: signal delivered
OTHER = "other"     # exited on its own, but not via KeyboardInterrupt
CLEAN = "clean"     # exited 0, which the test itself treats as a failure

LABEL = {HANG: "HANG", KBI: "kbi", OTHER: "other", CLEAN: "CLEAN-EXIT"}


# --------------------------------------------------------------------------
# the child script
# --------------------------------------------------------------------------

def extract_script(path=TEST_FILE, method=TEST_METHOD):
    """Pull the child script out of the test source, verbatim.

    Parsed rather than copied: the indentation and the exact statement order
    are part of the timing regime being measured, and a hand copy silently
    becomes a different experiment.
    """
    with open(path, "r") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != method:
            continue
        for stmt in ast.walk(node):
            if (isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "script"
                            for t in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)):
                return stmt.value.value
        raise SystemExit("%s: no `script = <string>` in %s" % (path, method))
    raise SystemExit("%s: no %s" % (path, method))


def _sub_once(script, anchor, replacement):
    """Textual substitution that refuses to no-op silently."""
    n = script.count(anchor)
    if n != 1:
        raise SystemExit("anchor %r found %d times in the child script; "
                         "the test was edited and this rig needs updating"
                         % (anchor, n))
    return script.replace(anchor, replacement)


def _indent_of(script, anchor):
    for line in script.splitlines():
        if anchor in line:
            return line[:len(line) - len(line.lstrip())]
    raise SystemExit("anchor %r not found" % (anchor,))


def build_script(base, delay=None, interrupts=1, interrupt_gap=0.0,
                 recursion_limit=None, threads=0):
    """Apply the knobs to the verbatim script.

    Every knob is a minimal, anchored edit of the original text; with all knobs
    at their defaults the script is returned byte-for-byte unchanged, so the
    baseline cell really is the stdlib test.
    """
    script = base

    if delay is not None:
        script = _sub_once(script, "time.sleep(1)", "time.sleep(%r)" % (delay,))

    if interrupts != 1:
        # The join below re-indents every line to the anchor's own indent, so
        # these are written relative to it.
        ind = _indent_of(script, "_thread.interrupt_main()")
        body = ["for _i in range(%d):" % interrupts,
                "    _thread.interrupt_main()"]
        if interrupt_gap:
            body.append("    time.sleep(%r)" % (interrupt_gap,))
        script = _sub_once(script, "_thread.interrupt_main()",
                           ("\n" + ind).join(body))

    if recursion_limit is not None:
        ind = _indent_of(script, "import _thread")
        script = _sub_once(
            script, "import _thread",
            "import _thread\n%simport sys\n%ssys.setrecursionlimit(%d)"
            % (ind, ind, recursion_limit))

    if threads:
        ind = _indent_of(script, "t = threading.Thread(target=h)")
        extra = [
            "def _idle():",
            "    while True:",
            "        time.sleep(0.001)",
            "for _i in range(%d):" % threads,
            "    threading.Thread(target=_idle, daemon=True).start()",
            "t = threading.Thread(target=h)",
        ]
        script = _sub_once(script, "t = threading.Thread(target=h)",
                           ("\n" + ind).join(extra))

    return script


# --------------------------------------------------------------------------
# running one child
# --------------------------------------------------------------------------

def _drain(stream, sink):
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            sink.append(chunk)
    except (ValueError, OSError):
        return


def run_child(pypy, script, watchdog, jit=None, taskset=None, env_extra=None):
    """Run the child once. Returns (outcome, duration, rc, stderr_bytes).

    The watchdog is a sleep+SIGKILL of our own: /usr/bin/timeout on this box is
    uutils 0.2.2, which reports rc=124 without ever killing the child, so a
    "timed out" run would keep spinning on a core and poison every measurement
    that follows.  The child gets its own session so that SIGKILL reaches
    anything it forked.

    stdout/stderr are drained by threads.  A successful run dumps a large
    RecursionError traceback; if nobody reads it the child blocks on a full
    pipe and looks exactly like the hang being measured.
    """
    cmd = []
    if taskset is not None:
        cmd += ["taskset", "-c", str(taskset)]
    cmd += [pypy]
    if jit is not None:
        cmd += ["--jit", jit]
    # Mirrors script_helper.run_python_until_end(): -X faulthandler, then -I
    # because the test passes no env_vars.  -c last.
    cmd += ["-X", "faulthandler", "-I", "-c", script]

    env = os.environ.copy()
    env["TERM"] = ""            # script_helper does this
    if env_extra:
        env.update(env_extra)

    out, err = [], []
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, start_new_session=True)
    pumps = [threading.Thread(target=_drain, args=(s, sink), daemon=True)
             for s, sink in ((proc.stdout, out), (proc.stderr, err))]
    for p in pumps:
        p.start()

    killed = False
    try:
        proc.wait(timeout=watchdog)
    except subprocess.TimeoutExpired:
        killed = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.wait()
    duration = time.monotonic() - start

    for p in pumps:
        p.join(5)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass

    stderr = b"".join(err)
    if killed:
        outcome = HANG
    elif proc.returncode == 0:
        outcome = CLEAN
    elif b"KeyboardInterrupt" in stderr:
        outcome = KBI
    else:
        outcome = OTHER
    return outcome, duration, proc.returncode, stderr


# --------------------------------------------------------------------------
# background load
# --------------------------------------------------------------------------

class Spinners(object):
    """N busy-loop processes, to make the CPU contended on purpose."""

    def __init__(self, n, taskset=None):
        self.procs = []
        self.n = n
        self.taskset = taskset

    def __enter__(self):
        for _ in range(self.n):
            cmd = []
            if self.taskset is not None:
                cmd += ["taskset", "-c", str(self.taskset)]
            cmd += ["/bin/sh", "-c", "while :; do :; done"]
            self.procs.append(subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True))
        if self.procs:
            time.sleep(0.5)     # let the load average start to reflect them
        return self

    def __exit__(self, *exc):
        for p in self.procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                p.kill()
        for p in self.procs:
            p.wait()
        self.procs = []


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

def wilson(k, n, z=1.96):
    """95% Wilson score interval -- behaves at k=0 and k=n, unlike normal."""
    if n == 0:
        return (0.0, 0.0)
    p = float(k) / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def _float_list(text):
    return [float(x) for x in text.split(",") if x.strip()]


def _int_list(text):
    return [int(x) for x in text.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pypy", action="append", required=True,
                        metavar="[LABEL=]PATH",
                        help="PyPy binary to test; repeat to compare binaries "
                             "interleaved run for run.  Every build is called "
                             "pypy-nightly/bin/pypy3, so pass LABEL=PATH to "
                             "tell two of them apart in the report")
    parser.add_argument("--reps", type=int, default=10,
                        help="runs per configuration (default: 10)")
    parser.add_argument("--watchdog", type=float, default=15.0,
                        help="seconds before the child is SIGKILLed and "
                             "counted as a hang (default: 15)")
    parser.add_argument("--delay", type=_float_list, default=None,
                        metavar="SECS[,SECS...]",
                        help="interrupt delay, i.e. the argument to "
                             "time.sleep() in the interrupting thread; a "
                             "comma-separated list is swept, interleaved "
                             "(default: leave the test's own 1)")
    parser.add_argument("--jitter", type=float, default=0.0, metavar="SECS",
                        help="draw the interrupt delay uniformly from "
                             "delay+-SECS, fresh for every run; use this "
                             "instead of hunting the sweep's peak, which is "
                             "narrow and moves with machine speed")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed for --jitter (default: random)")
    parser.add_argument("--load", type=int, default=0, metavar="N",
                        help="N busy-loop processes running throughout "
                             "(default: 0)")
    parser.add_argument("--interrupts", type=int, default=1, metavar="N",
                        help="call interrupt_main() N times (default: 1)")
    parser.add_argument("--interrupt-gap", type=float, default=0.0,
                        metavar="SECS",
                        help="sleep between repeated interrupts (default: 0)")
    parser.add_argument("--recursion-limit", type=_int_list, default=None,
                        metavar="N[,N...]",
                        help="sys.setrecursionlimit(N) in the child; a "
                             "comma-separated list is swept, interleaved.  "
                             "This is the knob that matters most: the stock "
                             "limit hangs far less often than a raised one")
    parser.add_argument("--threads", type=int, default=0, metavar="N",
                        help="N extra idle daemon threads alive at interrupt "
                             "time (default: 0)")
    parser.add_argument("--taskset", type=str, default=None, metavar="CPUS",
                        help="pin the child to these CPUs, e.g. 0 -- forces "
                             "the interrupting thread and the main thread onto "
                             "one core")
    parser.add_argument("--load-taskset", type=str, default=None,
                        metavar="CPUS",
                        help="pin the background load to these CPUs "
                             "(default: wherever --taskset put the child)")
    parser.add_argument("--jit", type=str, default=None, metavar="ARG",
                        help="pass --jit ARG to the child, e.g. off")
    parser.add_argument("--env", action="append", default=[], metavar="K=V",
                        help="extra environment variable for the child, e.g. "
                             "PYPY_GC_NURSERY=1M; repeatable")
    parser.add_argument("--json", type=str, default=None, metavar="PATH",
                        help="write the raw per-run results here")
    parser.add_argument("--show-script", action="store_true",
                        help="print the child script and exit")
    args = parser.parse_args()

    env_extra = {}
    for item in args.env:
        if "=" not in item:
            parser.error("--env wants K=V, got %r" % (item,))
        k, v = item.split("=", 1)
        env_extra[k] = v

    base = extract_script()
    delays = args.delay if args.delay else [None]
    reclimits = args.recursion_limit if args.recursion_limit else [None]
    rng = random.Random(args.seed)
    if args.jitter and not args.delay:
        parser.error("--jitter needs --delay to jitter around")

    def script_for(delay, reclimit):
        return build_script(base, delay=delay, interrupts=args.interrupts,
                            interrupt_gap=args.interrupt_gap,
                            recursion_limit=reclimit,
                            threads=args.threads)

    if args.show_script:
        sys.stdout.write(script_for(delays[0], reclimits[0]))
        return 0

    # One cell per (binary, delay).  Cells are interleaved run for run, so a
    # drift in machine load lands on every cell equally.
    binaries = []
    for i, spec in enumerate(args.pypy):
        if "=" in spec:
            label, path = spec.split("=", 1)
        else:
            path = spec
            label = os.path.basename(os.path.dirname(os.path.dirname(path)))
            if not label or label in [b[0] for b in binaries]:
                label = "bin%d" % (i + 1)
        binaries.append((label, path))

    cells = []
    for (label, path), delay, reclimit in itertools.product(
            binaries, delays, reclimits):
        name = label
        if len(delays) > 1:
            name += " d=%g" % delay
        elif args.jitter and delay is not None:
            name += " d=%g+-%g" % (delay, args.jitter)
        if len(reclimits) > 1:
            name += " rl=%d" % reclimit
        cells.append({"pypy": path, "label": label, "delay": delay,
                      "reclimit": reclimit, "name": name,
                      "script": script_for(delay, reclimit), "runs": []})

    load_taskset = (args.load_taskset if args.load_taskset is not None
                    else args.taskset)

    knobs = ["watchdog=%g" % args.watchdog]
    if args.load:
        knobs.append("load=%d" % args.load)
        if load_taskset is not None:
            knobs.append("load-taskset=%s" % load_taskset)
    if args.jitter:
        knobs.append("jitter=%g" % args.jitter)
    if args.taskset is not None:
        knobs.append("taskset=%s" % args.taskset)
    if args.interrupts != 1:
        knobs.append("interrupts=%d" % args.interrupts)
    if args.interrupt_gap:
        knobs.append("gap=%g" % args.interrupt_gap)
    if args.recursion_limit and len(reclimits) == 1:
        knobs.append("recursionlimit=%d" % reclimits[0])
    if args.threads:
        knobs.append("threads=%d" % args.threads)
    if args.jit is not None:
        knobs.append("jit=%s" % args.jit)
    for k, v in sorted(env_extra.items()):
        knobs.append("%s=%s" % (k, v))

    print("%d cell(s) x %d reps, %s" % (len(cells), args.reps, " ".join(knobs)))
    for cell in cells:
        print("  cell %-28s %s" % (cell["name"], cell["pypy"]))
    sys.stdout.flush()

    total = len(cells) * args.reps
    done = 0
    start_time = time.monotonic()
    try:
        with Spinners(args.load, taskset=load_taskset):
            for rep in range(args.reps):
                # Rotate the order so no cell is permanently first.
                order = cells[rep % len(cells):] + cells[:rep % len(cells)]
                for cell in order:
                    delay, script = cell["delay"], cell["script"]
                    if args.jitter and delay is not None:
                        # Draw a fresh delay per run.  The peak of the delay
                        # sweep is sharp and moves with machine speed, so a
                        # fixed delay that was 100% an hour ago can be 10% now;
                        # jittering samples the whole band and trades peak
                        # height for a rate that reproduces.
                        delay = round(rng.uniform(max(0.0, delay - args.jitter),
                                                  delay + args.jitter), 3)
                        script = script_for(delay, cell["reclimit"])
                    outcome, duration, rc, stderr = run_child(
                        cell["pypy"], script, args.watchdog,
                        jit=args.jit, taskset=args.taskset,
                        env_extra=env_extra)
                    cell["runs"].append({"outcome": outcome, "rc": rc,
                                         "duration": duration,
                                         "delay": delay,
                                         "stderr_len": len(stderr)})
                    done += 1
                    elapsed = time.monotonic() - start_time
                    print("[%d/%d] %-28s rep %-3d ... %-10s (%.1fs, rc=%s, "
                          "%dB stderr) [%.0fs elapsed]"
                          % (done, total, cell["name"], rep + 1,
                             LABEL[outcome], duration, rc, len(stderr),
                             elapsed))
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print("\ninterrupted; reporting what we have")

    print("\n" + "=" * 72)
    print("SUMMARY (%s)" % " ".join(knobs))
    print("=" * 72)
    print("%-28s %8s %8s %-22s" % ("cell", "hangs", "n", "rate [95% CI]"))
    for cell in cells:
        runs = cell["runs"]
        n = len(runs)
        k = sum(1 for r in runs if r["outcome"] == HANG)
        lo, hi = wilson(k, n)
        print("%-28s %8d %8d %5.0f%% [%3.0f%%-%3.0f%%]"
              % (cell["name"], k, n, 100.0 * k / n if n else 0.0,
                 100 * lo, 100 * hi))
    # When a sweep has several cells per binary, the per-binary total is the
    # number that actually reproduces: individual delays swing between 0% and
    # 100% from sweep to sweep, but the total over the band holds still.
    if len(cells) > len(binaries):
        print("-" * 72)
        for label, _path in binaries:
            runs = [r for c in cells if c["label"] == label
                    for r in c["runs"]]
            n = len(runs)
            k = sum(1 for r in runs if r["outcome"] == HANG)
            lo, hi = wilson(k, n)
            print("%-28s %8d %8d %5.0f%% [%3.0f%%-%3.0f%%]  (all cells)"
                  % (label, k, n, 100.0 * k / n if n else 0.0,
                     100 * lo, 100 * hi))

    print("\nraw sequences (H=hang, k=KeyboardInterrupt, o=other exit, "
          "C=clean exit):")
    code = {HANG: "H", KBI: "k", OTHER: "o", CLEAN: "C"}
    for cell in cells:
        print("  %-28s %s"
              % (cell["name"], "".join(code[r["outcome"]] for r in cell["runs"])))

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"knobs": knobs, "reps": args.reps,
                       "cells": [{"name": c["name"], "pypy": c["pypy"],
                                  "delay": c["delay"],
                                  "reclimit": c["reclimit"], "runs": c["runs"]}
                                 for c in cells]}, f, indent=2)
        print("\nwrote %s" % args.json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
