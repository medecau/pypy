#!/usr/bin/env python3
"""Run CPython stdlib tests against a translated PyPy binary."""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from stdlib_test_lists import SMOKE_TESTS, SKIP_TESTS, EXPECTED_FAILURES


def _as_text(data):
    """Coerce subprocess output to str, whatever we were handed."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def _is_resource_denied(output):
    """Did regrtest decline to run the module for want of a resource?

    test_ttk needs the 'gui' resource, which CI does not enable, so regrtest
    skips it, reports NO TESTS RAN and exits non-zero -- which we were
    counting as a failure.  Nothing is wrong and there is nothing to fix; the
    module would run normally if the resource were available, so it does not
    belong in SKIP_TESTS either.  Matching on both markers keeps this narrow:
    a module that runs no tests for any other reason still counts as failed.
    """
    return "Result: NO TESTS RAN" in output and "resource_denied=" in output


def run_test(args):
    """Run a single test module. Returns (test_name, status, duration, output)."""
    pypy, test_name, timeout = args
    start = time.monotonic()
    try:
        result = subprocess.run(
            [pypy, "-m", "test", "-v", test_name, f"--timeout={timeout}"],
            capture_output=True, text=True, timeout=timeout + 30)
        duration = time.monotonic() - start
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return (test_name, "pass", duration, output)
        elif _is_resource_denied(output):
            return (test_name, "skipped", duration, output)
        else:
            return (test_name, "fail", duration, output)
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        # NB: TimeoutExpired carries raw bytes even when text=True was passed
        # to subprocess.run.  Left undecoded, these reach json.dump at the end
        # of the run and blow up with "Object of type bytes is not JSON
        # serializable", losing the results of the whole run.
        output = _as_text(e.stdout) + _as_text(e.stderr)
        return (test_name, "timeout", duration, output)
    except Exception as e:
        duration = time.monotonic() - start
        return (test_name, "error", duration, str(e))


def get_cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pypy", required=True, help="Path to PyPy binary")
    parser.add_argument("--smoke-only", action="store_true",
                        help="Only run smoke tests (~60 modules)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout per test in seconds (default: 300)")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="Number of parallel workers (default: CPU count)")
    args = parser.parse_args()

    workers = args.jobs if args.jobs > 0 else get_cpu_count()

    if args.smoke_only:
        tests = sorted(SMOKE_TESTS)
        print(f"Running {len(tests)} smoke tests with {workers} workers")
    else:
        test_dir = os.path.join(os.path.dirname(__file__),
                                "..", "..", "..", "lib-python", "3", "test")
        test_dir = os.path.normpath(test_dir)
        tests = set()
        for entry in os.listdir(test_dir):
            if entry.startswith("test_") and entry.endswith(".py"):
                tests.add(entry[:-3])
            elif entry.startswith("test_") and os.path.isdir(
                    os.path.join(test_dir, entry)):
                tests.add(entry)
        tests -= set(SKIP_TESTS)
        tests = sorted(tests)
        print(f"Running {len(tests)} tests with {workers} workers (skipping {len(SKIP_TESTS)})")

    skip_set = set(SKIP_TESTS)
    expected_fail_set = set(EXPECTED_FAILURES)

    results = {"pass": [], "fail": [], "timeout": [], "error": [],
               "expected_fail": [], "skipped": []}
    failure_outputs = {}

    test_args = [(args.pypy, t, args.timeout) for t in tests if t not in skip_set]
    total = len(test_args)
    completed = 0
    start_time = time.monotonic()

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_test, ta): ta[1] for ta in test_args}

        for future in as_completed(futures):
            completed += 1
            name, status, duration, output = future.result()

            # A module on the expected-failure list counts as xfail however it
            # goes wrong, not only when regrtest exits non-zero.  test_json
            # hangs rather than fails (see the note in stdlib_test_lists), and
            # whether that surfaces as "fail" or "timeout" depends on which
            # watchdog fires first -- regrtest's own --timeout, which relies on
            # faulthandler, or our outer subprocess one.  Keying off that race
            # would make the gate flap.
            if status in ("fail", "timeout", "error") and name in expected_fail_set:
                status = "expected_fail"

            results[status].append((name, duration))
            if status in ("fail", "error", "timeout", "expected_fail"):
                failure_outputs[name] = output

            label = {"pass": "ok", "fail": "FAIL", "timeout": "TIMEOUT",
                     "error": "ERROR", "expected_fail": "xfail",
                     "skipped": "skip"}[status]
            elapsed = time.monotonic() - start_time
            print(f"[{completed}/{total}] {name} ... {label} ({duration:.1f}s) [{elapsed:.0f}s elapsed]")
            sys.stdout.flush()

    # Summary
    elapsed = time.monotonic() - start_time
    print("\n" + "=" * 60)
    print(f"SUMMARY (completed in {elapsed:.0f}s with {workers} workers)")
    print("=" * 60)
    print(f"  Passed:           {len(results['pass'])}")
    print(f"  Failed:           {len(results['fail'])}")
    print(f"  Expected failures:{len(results['expected_fail'])}")
    print(f"  Timeouts:         {len(results['timeout'])}")
    print(f"  Errors:           {len(results['error'])}")
    print(f"  Skipped:          {len(results['skipped'])}")

    if results["fail"]:
        print("\nUnexpected failures:")
        for name, dur in sorted(results["fail"]):
            print(f"  - {name}")

    if results["timeout"]:
        print("\nTimeouts:")
        for name, dur in sorted(results["timeout"]):
            print(f"  - {name}")

    # Print failure details
    if failure_outputs:
        print("\n" + "=" * 60)
        print("FAILURE DETAILS")
        print("=" * 60)
        for name, output in sorted(failure_outputs.items()):
            print(f"\n--- {name} ---")
            lines = output.splitlines()
            if len(lines) > 50:
                print(f"  ... ({len(lines) - 50} lines omitted)")
                lines = lines[-50:]
            for line in lines:
                print(f"  {line}")

    # Save results as JSON
    json_results = {
        "pass": [n for n, _ in results["pass"]],
        "fail": [n for n, _ in results["fail"]],
        "expected_fail": [n for n, _ in results["expected_fail"]],
        "timeout": [n for n, _ in results["timeout"]],
        "error": [n for n, _ in results["error"]],
        "skipped": [n for n, _ in results["skipped"]],
        "failure_details": {n: o[-2000:] for n, o in failure_outputs.items()},
    }
    with open("stdlib-results.json", "w") as f:
        json.dump(json_results, f, indent=2)

    # Exit 1 if there are unexpected failures.  Timeouts count: a module that
    # hangs is not a module that passes, and leaving them out meant a new hang
    # was printed in the summary but still exited 0.
    unexpected = (len(results["fail"]) + len(results["error"])
                  + len(results["timeout"]))
    if unexpected:
        print(f"\n{unexpected} unexpected failure(s)")
        sys.exit(1)
    else:
        print("\nAll tests passed (or matched expected failures)")
        sys.exit(0)


if __name__ == "__main__":
    main()
