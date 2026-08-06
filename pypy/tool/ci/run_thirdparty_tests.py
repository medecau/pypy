#!/usr/bin/env python3
"""Run third-party PyPI packages' own test suites against a translated PyPy binary.

Sibling of ``run_stdlib_tests.py``: a host-``python3`` orchestrator that, for
each package in ``thirdparty_test_lists.PACKAGES``, creates a per-package venv
with the *translated* PyPy under test, installs the package (from a pinned git
tag or from PyPI), installs its test-only deps, and runs its upstream suite.
Results fall into the same five buckets as the stdlib runner
(pass/fail/timeout/error/expected_fail); a package's ``status`` field drives the
xfail reclassification, and ``deselect``/``ignore`` document per-subtest gaps.

Typical use (from this directory)::

    python3 run_thirdparty_tests.py --pypy /path/to/pypy3-c            # all tiers
    python3 run_thirdparty_tests.py --pypy /path/to/pypy3-c --tiers 1  # one tier
    python3 run_thirdparty_tests.py --pypy /path/to/pypy3-c --only requests
    python3 run_thirdparty_tests.py --pypy /bin/false --dry-run        # no binary

Exit is 1 only on unexpected fail+error (timeouts and xfails do not fail the
build), matching the stdlib runner.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from thirdparty_test_lists import PACKAGES

# Keep the captured output that crosses the process boundary bounded --
# C/Rust build logs can be many megabytes.
MAX_OUTPUT_CHARS = 20000


def _venv_python(venv_dir):
    """Return the interpreter path inside a PyPy/CPython venv (posix layout)."""
    bindir = os.path.join(venv_dir, "bin")
    for name in ("python", "python3", "pypy3", "pypy"):
        cand = os.path.join(bindir, name)
        if os.path.exists(cand):
            return cand
    # Fall back to the conventional name even if it does not exist yet.
    return os.path.join(bindir, "python")


def package_commands(pkg, pypy, pkg_root):
    """Resolve the ordered command list for one package.

    Single source of truth shared by the worker (which executes) and
    ``--dry-run`` (which prints).  Each command is a dict with keys
    ``label``, ``argv``, ``cwd`` and ``kind`` ("setup" -> must succeed;
    "test" -> its exit code is the package result).
    """
    venv_dir = os.path.join(pkg_root, "venv")
    venv_py = _venv_python(venv_dir)
    source = pkg["source"]
    if source["kind"] == "git":
        checkout = os.path.join(pkg_root, "src")
    else:                                   # "pyargs": tests come with the install
        checkout = pkg_root

    cmds = []
    # --without-pip + explicit ensurepip: venv's own pip bootstrap swallows
    # ensurepip's traceback (CalledProcessError with no detail); as a separate
    # step its full output lands in our captured log.
    cmds.append({"label": "venv", "kind": "setup", "cwd": None,
                 "argv": [pypy, "-m", "venv", "--without-pip", venv_dir]})
    cmds.append({"label": "ensurepip", "kind": "setup", "cwd": None,
                 "argv": [venv_py, "-m", "ensurepip", "--upgrade",
                          "--default-pip"]})
    cmds.append({"label": "bootstrap", "kind": "setup", "cwd": None,
                 "argv": [venv_py, "-m", "pip", "install", "-U",
                          "pip", "setuptools", "wheel", "pytest"]})
    if source["kind"] == "git":
        cmds.append({"label": "clone", "kind": "setup", "cwd": None,
                     "argv": ["git", "clone", "--depth", "1",
                              "--branch", source["ref"], source["url"], checkout]})

    install = list(pkg.get("install", []))
    if install:
        argv = [venv_py, "-m", "pip", "install"]
        if pkg.get("no_build_isolation"):
            argv.append("--no-build-isolation")
        argv += install
        cmds.append({"label": "install", "kind": "setup", "cwd": checkout,
                     "argv": argv})

    test_deps = list(pkg.get("test_deps", []))
    if test_deps:
        cmds.append({"label": "test-deps", "kind": "setup", "cwd": None,
                     "argv": [venv_py, "-m", "pip", "install"] + test_deps})

    test_argv = [venv_py] + list(pkg["test_cmd"])
    if pkg.get("runner", "pytest") == "pytest":
        test_argv += ["-p", "no:cacheprovider"]
        for nid in pkg.get("deselect", []):
            test_argv += ["--deselect", nid]
        for path in pkg.get("ignore", []):
            test_argv += ["--ignore", path]
    # --pyargs must import the *installed* package, so run from a neutral cwd
    # rather than the source checkout (which would shadow the install).
    if "--pyargs" in test_argv:
        test_cwd = pkg_root
    else:
        test_cwd = checkout
    cmds.append({"label": "test", "kind": "test", "cwd": test_cwd,
                 "argv": test_argv})
    return cmds


def _partial(exc):
    out = exc.stdout or ""
    err = exc.stderr or ""
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return out + err


def _finish(name, status, start, log, keep, pkg_root):
    duration = time.monotonic() - start
    if not keep:
        shutil.rmtree(pkg_root, ignore_errors=True)
    output = "\n".join(log)
    if len(output) > MAX_OUTPUT_CHARS:
        output = "...(truncated)...\n" + output[-MAX_OUTPUT_CHARS:]
    return (name, status, duration, output)


def run_package(task):
    """Worker: build+install+test one package. Returns (name, status, dur, output)."""
    pypy, pkg, timeout, workdir, keep = task
    name = pkg["name"]
    start = time.monotonic()
    deadline = start + timeout
    pkg_root = os.path.join(workdir, name)
    log = []
    try:
        if os.path.isdir(pkg_root):
            shutil.rmtree(pkg_root, ignore_errors=True)
        os.makedirs(pkg_root)

        for cmd in package_commands(pkg, pypy, pkg_root):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.append("[deadline exceeded before '%s']" % cmd["label"])
                return _finish(name, "timeout", start, log, keep, pkg_root)
            log.append("$ " + " ".join(cmd["argv"]))
            try:
                res = subprocess.run(cmd["argv"], cwd=cmd["cwd"],
                                     capture_output=True, text=True,
                                     errors="replace", timeout=remaining)
            except subprocess.TimeoutExpired as e:
                log.append(_partial(e))
                log.append("[TIMEOUT in '%s']" % cmd["label"])
                return _finish(name, "timeout", start, log, keep, pkg_root)
            log.append(res.stdout or "")
            log.append(res.stderr or "")
            if cmd["kind"] == "setup" and res.returncode != 0:
                log.append("[setup step '%s' failed with code %d]"
                           % (cmd["label"], res.returncode))
                return _finish(name, "error", start, log, keep, pkg_root)
            if cmd["kind"] == "test":
                # pytest exit codes: 0 ok, 1 tests failed, 5 no tests collected.
                if res.returncode == 0:
                    status = "pass"
                elif res.returncode == 5:
                    log.append("[no tests collected -- check test_cmd path]")
                    status = "error"
                else:
                    status = "fail"
                return _finish(name, status, start, log, keep, pkg_root)

        log.append("[no test step ran]")
        return _finish(name, "error", start, log, keep, pkg_root)
    except Exception as e:                                  # noqa: BLE001
        log.append(repr(e))
        return _finish(name, "error", start, log, keep, pkg_root)


def get_cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _select(tiers, only):
    """Filter PACKAGES by tier / name, dropping skip-status entries."""
    selected, skipped = [], []
    for pkg in PACKAGES:
        if pkg.get("status") == "skip":
            skipped.append(pkg)
            continue
        if tiers and pkg["tier"] not in tiers:
            continue
        if only and only.lower() not in pkg["name"].lower():
            continue
        selected.append(pkg)
    return selected, skipped


def _print_plan(selected, pypy, workdir):
    print("Dry run: %d package(s)\n" % len(selected))
    for pkg in selected:
        pkg_root = os.path.join(workdir, pkg["name"])
        print("=== %s (tier %d, %s, %s) ==="
              % (pkg["name"], pkg["tier"], pkg["kind"],
                 pkg.get("status", "expected_pass")))
        if pkg.get("note"):
            print("  note: " + pkg["note"])
        for cmd in package_commands(pkg, pypy, pkg_root):
            cwd = ("  [cwd=%s]" % cmd["cwd"]) if cmd["cwd"] else ""
            print("  %-11s %s%s" % (cmd["label"] + ":", " ".join(cmd["argv"]), cwd))
        print()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pypy", required=True, help="Path to the PyPy binary")
    parser.add_argument("--tiers", "--tier", dest="tiers", default="",
                        help="comma/space separated tiers to run (default: all)")
    parser.add_argument("--only", default="",
                        help="substring filter on package name")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="per-package wall-clock timeout in seconds (default: 3600)")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="parallel workers (default: CPU count // 2)")
    parser.add_argument("--workdir", default="",
                        help="dir for clones+venvs (default: a fresh tempdir)")
    parser.add_argument("--keep", action="store_true",
                        help="do not delete per-package workdirs after running")
    parser.add_argument("--dry-run", "--list", dest="dry_run", action="store_true",
                        help="print the resolved plan for each package and exit")
    args = parser.parse_args()

    tiers = set()
    for tok in args.tiers.replace(",", " ").split():
        tiers.add(int(tok))

    selected, skipped = _select(tiers, args.only)
    if not selected:
        print("No packages selected.")
        sys.exit(0)

    if args.dry_run:
        _print_plan(selected, args.pypy, args.workdir or "<workdir>")
        return

    workdir = args.workdir or tempfile.mkdtemp(prefix="pypy-thirdparty-")
    os.makedirs(workdir, exist_ok=True)
    workers = args.jobs if args.jobs > 0 else max(1, get_cpu_count() // 2)
    pkgs_by_name = {p["name"]: p for p in selected}

    print("Running %d package(s) with %d workers (timeout %ds each)"
          % (len(selected), workers, args.timeout))
    if skipped:
        print("Skipping %d: %s"
              % (len(skipped), ", ".join(p["name"] for p in skipped)))
    print("Workdir: %s%s" % (workdir, " (kept)" if args.keep else ""))

    results = {"pass": [], "fail": [], "timeout": [], "error": [],
               "expected_fail": []}
    failure_outputs = {}

    tasks = [(args.pypy, pkg, args.timeout, workdir, args.keep) for pkg in selected]
    total = len(tasks)
    completed = 0
    start_time = time.monotonic()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_package, t): t[1]["name"] for t in tasks}
        for future in as_completed(futures):
            completed += 1
            name, status, duration, output = future.result()

            expected = pkgs_by_name[name].get("status", "expected_pass")
            if expected == "expected_fail" and status in ("fail", "error", "timeout"):
                status = "expected_fail"

            results[status].append((name, duration))
            if status in ("fail", "error", "timeout", "expected_fail"):
                failure_outputs[name] = output

            label = {"pass": "ok", "fail": "FAIL", "timeout": "TIMEOUT",
                     "error": "ERROR", "expected_fail": "xfail"}[status]
            elapsed = time.monotonic() - start_time
            print("[%d/%d] %s ... %s (%.1fs) [%.0fs elapsed]"
                  % (completed, total, name, label, duration, elapsed))
            sys.stdout.flush()

    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)

    # Summary
    elapsed = time.monotonic() - start_time
    print("\n" + "=" * 60)
    print("SUMMARY (completed in %.0fs with %d workers)" % (elapsed, workers))
    print("=" * 60)
    print("  Passed:           %d" % len(results["pass"]))
    print("  Failed:           %d" % len(results["fail"]))
    print("  Expected failures:%d" % len(results["expected_fail"]))
    print("  Timeouts:         %d" % len(results["timeout"]))
    print("  Errors:           %d" % len(results["error"]))

    if results["fail"]:
        print("\nUnexpected failures:")
        for name, _ in sorted(results["fail"]):
            print("  - " + name)
    if results["error"]:
        print("\nErrors (install/build/collection):")
        for name, _ in sorted(results["error"]):
            print("  - " + name)
    if results["timeout"]:
        print("\nTimeouts:")
        for name, _ in sorted(results["timeout"]):
            print("  - " + name)

    if failure_outputs:
        print("\n" + "=" * 60)
        print("FAILURE DETAILS")
        print("=" * 60)
        for name, output in sorted(failure_outputs.items()):
            print("\n--- %s ---" % name)
            lines = output.splitlines()
            if len(lines) > 50:
                print("  ... (%d lines omitted)" % (len(lines) - 50))
                lines = lines[-50:]
            for line in lines:
                print("  " + line)

    # Save results as JSON (sibling of stdlib-results.json)
    json_results = {
        "pass": [n for n, _ in results["pass"]],
        "fail": [n for n, _ in results["fail"]],
        "expected_fail": [n for n, _ in results["expected_fail"]],
        "timeout": [n for n, _ in results["timeout"]],
        "error": [n for n, _ in results["error"]],
        "packages": {
            p["name"]: {"tier": p["tier"], "kind": p["kind"],
                        "expected": p.get("status", "expected_pass")}
            for p in selected
        },
        "failure_details": {n: o[-4000:] for n, o in failure_outputs.items()},
    }
    with open("thirdparty-results.json", "w") as f:
        json.dump(json_results, f, indent=2)

    unexpected = len(results["fail"]) + len(results["error"])
    if unexpected:
        print("\n%d unexpected failure(s)" % unexpected)
        sys.exit(1)
    else:
        print("\nAll packages passed (or matched expected failures)")
        sys.exit(0)


if __name__ == "__main__":
    main()
