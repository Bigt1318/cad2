#!/usr/bin/env python3
"""
FORD-CAD — Single-Command Test Runner
======================================
Run:  python run_tests.py
      python run_tests.py --html       (with HTML report)
      python run_tests.py --quick      (API tests only, skip Playwright)
      python run_tests.py --verbose    (verbose output)
"""

import os
import sys
import subprocess
import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(ROOT_DIR, "test_artifacts")


def main():
    args = sys.argv[1:]
    quick = "--quick" in args
    html = "--html" in args
    verbose = "--verbose" in args or "-v" in args

    # Clean stale test DB
    test_db = os.path.join(ROOT_DIR, "cad_test.db")
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except OSError:
            pass

    # Build pytest command
    cmd = [sys.executable, "-m", "pytest"]

    # Test files
    test_files = [
        "tests/test_api_core.py",
        "tests/test_api_modules.py",
        "tests/test_e2e_workflows.py",
    ]
    if not quick:
        test_files.append("tests/test_ui_playwright.py")

    cmd.extend(test_files)

    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-v")

    cmd.append("--tb=short")

    # HTML report
    if html:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = os.path.join(ARTIFACTS_DIR, ts)
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, "test_report.html")
        cmd.extend(["--html", report_path, "--self-contained-html"])
        print(f"[FORD-CAD] HTML report will be saved to: {report_path}")

    print(f"[FORD-CAD] Running: {' '.join(cmd)}")
    print(f"[FORD-CAD] {'Quick mode (API only)' if quick else 'Full suite (API + UI)'}")
    print()

    result = subprocess.run(cmd, cwd=ROOT_DIR)

    if html and result.returncode == 0:
        print(f"\n[FORD-CAD] HTML report: {report_path}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
