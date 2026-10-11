#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the public source inventory; this is not a security audit."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "downloads", "output", "validation"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "private workspace path": re.compile(r"/Users/xyz/|/var/folders/"),
}


def public_files():
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    if tracked.returncode == 0 and tracked.stdout:
        return [ROOT / p.decode() for p in tracked.stdout.split(b"\0") if p]
    return [p for p in ROOT.rglob("*") if p.is_file()
            and not any(part in IGNORED for part in p.relative_to(ROOT).parts)
            and p.relative_to(ROOT).parts[:2] not in
            (("build", "inputs"), ("build", "work"), ("build", "runtime"))
            and p.name != "dino-native" and p.suffix not in (".so", ".o", ".pyc")]


def main():
    errors = []
    files = public_files()
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            errors.append(f"{name}: symlink is outside the source preview policy")
        if path.suffix in (".img", ".gba", ".so", ".o", ".elf"):
            errors.append(f"{name}: executable/image/ROM input must not be committed")
        if path.stat().st_size > 2 * 1024 * 1024:
            errors.append(f"{name}: unexpected large source-preview file")
        if name == "tools/audit_public_tree.py":
            continue
        try:
            content = path.read_text()
        except UnicodeError:
            if path.suffix != ".png":
                errors.append(f"{name}: unexplained binary file")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{name}: {label} detected")
    for name in ("README.md", "LICENSE", "CREDITS.md", "NOTICE", "SECURITY.md"):
        if not (ROOT / name).is_file():
            errors.append(f"Missing required public document: {name}")
    print(json.dumps({"status": "FAIL" if errors else "PASS",
                      "source_files_checked": len(files), "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
