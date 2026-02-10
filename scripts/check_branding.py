#!/usr/bin/env python3
"""
FORD-CAD Branding Ban Check
============================
Fails if 'BOSK' appears in user-facing files (templates, JS, CSS, Python UI strings).
Allowlisted: email addresses in config files, internal legacy comments marked [LEGACY-OK].

Usage:
    python scripts/check_branding.py          # exits 0 if clean, 1 if violations found
    python scripts/check_branding.py --fix    # shows suggested replacements
"""

import os
import re
import sys

# Directories to scan
SCAN_DIRS = ["templates", "static/js", "static/css", "app"]
# Additional root files to scan
SCAN_FILES = ["main.py", "reports.py"]
# Extensions to check
SCAN_EXTENSIONS = {".html", ".js", ".css", ".py"}
# Allowlisted paths (relative to repo root) — config/docs only
ALLOWLIST_PATHS = {
    "email_config.json",
    "EMAIL_SETUP.md",
    "FORD_CAD_EVALUATION_REPORT.md",
    "scripts/check_branding.py",  # this script itself
}

BOSK_PATTERN = re.compile(r'BOSK', re.IGNORECASE)
# Lines with this marker are exempt
LEGACY_OK_MARKER = "[LEGACY-OK]"


def find_repo_root():
    """Walk up from script location to find .git directory."""
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def scan_file(filepath, repo_root):
    """Return list of (line_number, line_text) violations."""
    rel = os.path.relpath(filepath, repo_root).replace("\\", "/")
    if rel in ALLOWLIST_PATHS:
        return []

    violations = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                if LEGACY_OK_MARKER in line:
                    continue
                if BOSK_PATTERN.search(line):
                    violations.append((i, line.rstrip()))
    except Exception:
        pass
    return violations


def main():
    repo_root = find_repo_root()
    show_fix = "--fix" in sys.argv
    total_violations = 0
    files_with_violations = 0

    # Collect files to scan
    files_to_scan = []
    for scan_dir in SCAN_DIRS:
        full_dir = os.path.join(repo_root, scan_dir)
        if not os.path.isdir(full_dir):
            continue
        for root, _, files in os.walk(full_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in SCAN_EXTENSIONS:
                    files_to_scan.append(os.path.join(root, fname))

    for fname in SCAN_FILES:
        full_path = os.path.join(repo_root, fname)
        if os.path.isfile(full_path):
            files_to_scan.append(full_path)

    # Scan
    for filepath in sorted(files_to_scan):
        violations = scan_file(filepath, repo_root)
        if violations:
            rel = os.path.relpath(filepath, repo_root).replace("\\", "/")
            files_with_violations += 1
            for line_num, line_text in violations:
                total_violations += 1
                print(f"  VIOLATION: {rel}:{line_num}: {line_text.strip()}")
                if show_fix:
                    fixed = line_text.replace("BOSK-CAD", "FORD-CAD")
                    fixed = fixed.replace("BOSK CAD", "FORD CAD")
                    fixed = fixed.replace("BOSK_", "CAD_")
                    fixed = fixed.replace("BOSK", "FORD")
                    if fixed != line_text:
                        print(f"       FIX: {fixed.strip()}")

    # Summary
    print()
    if total_violations == 0:
        print("BRANDING CHECK PASSED: No BOSK references found in user-facing code.")
        return 0
    else:
        print(f"BRANDING CHECK FAILED: {total_violations} violation(s) in {files_with_violations} file(s).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
