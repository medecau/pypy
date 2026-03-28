#!/usr/bin/env python3
"""Run CPython stdlib tests against a translated PyPy binary."""

import argparse
import json
import subprocess
import sys
import time

from stdlib_test_lists import SMOKE_TESTS, SKIP_TESTS, EXPECTED_FAILURES


def run_test(pypy, test_name, timeout):
    """Run a single test module. Returns (test_name, status, duration, output)."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            [pypy, "-m", "test", "-v", test_name, f"--timeout={timeout}"],
            capture_output=True, text=True, timeout=timeout + 30)
        duration = time.monotonic() - start
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return (test_name, "pass", duration, output)
        else:
            return (test_name, "fail", duration, output)
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        output = (e.stdout or "") + (e.stderr or "")
        return (test_name, "timeout", duration, output)
    except Exception as e:
        duration = time.monotonic() - start
        print(f"  exception: {e}", file=sys.stderr)
        return (test_name, "error", duration, str(e))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pypy", required=True, help="Path to PyPy binary")
    parser.add_argument("--smoke-only", action="store_true",
                        help="Only run smoke tests (~60 modules)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout per test in seconds (default: 300)")
    args = parser.parse_args()

    if args.smoke_only:
        tests = sorted(SMOKE_TESTS)
        print(f"Running {len(tests)} smoke tests")
    else:
        # Discover all test modules from lib-python/3/test/
        import os
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
        print(f"Running {len(tests)} tests (skipping {len(SKIP_TESTS)})")

    skip_set = set(SKIP_TESTS)
    expected_fail_set = set(EXPECTED_FAILURES)

    results = {"pass": [], "fail": [], "timeout": [], "error": [],
               "expected_fail": []}
    failure_outputs = {}

    for i, test in enumerate(tests, 1):
        if test in skip_set:
            continue
        print(f"[{i}/{len(tests)}] {test} ... ", end="", flush=True)
        name, status, duration, output = run_test(args.pypy, test, args.timeout)

        if status == "fail" and name in expected_fail_set:
            status = "expected_fail"

        results[status].append((name, duration))
        if status in ("fail", "error", "timeout", "expected_fail"):
            failure_outputs[name] = output

        label = {"pass": "ok", "fail": "FAIL", "timeout": "TIMEOUT",
                 "error": "ERROR", "expected_fail": "xfail"}[status]
        print(f"{label} ({duration:.1f}s)")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Passed:           {len(results['pass'])}")
    print(f"  Failed:           {len(results['fail'])}")
    print(f"  Expected failures:{len(results['expected_fail'])}")
    print(f"  Timeouts:         {len(results['timeout'])}")
    print(f"  Errors:           {len(results['error'])}")

    if results["fail"]:
        print("\nUnexpected failures:")
        for name, dur in results["fail"]:
            print(f"  - {name}")

    if results["timeout"]:
        print("\nTimeouts:")
        for name, dur in results["timeout"]:
            print(f"  - {name}")

    # Print failure details
    if failure_outputs:
        print("\n" + "=" * 60)
        print("FAILURE DETAILS")
        print("=" * 60)
        for name, output in sorted(failure_outputs.items()):
            print(f"\n--- {name} ---")
            # Print last 50 lines of output to keep it manageable
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
        "failure_details": {n: o[-2000:] for n, o in failure_outputs.items()},
    }
    with open("stdlib-results.json", "w") as f:
        json.dump(json_results, f, indent=2)

    # Exit 1 if there are unexpected failures
    unexpected = len(results["fail"]) + len(results["error"])
    if unexpected:
        print(f"\n{unexpected} unexpected failure(s)")
        sys.exit(1)
    else:
        print("\nAll tests passed (or matched expected failures)")
        sys.exit(0)


if __name__ == "__main__":
    main()
