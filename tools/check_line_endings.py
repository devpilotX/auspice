"""Enforce the line ending policy that `.gitattributes` declares.

`.gitattributes` says `* text=auto eol=lf`, and declaring it is not the same as it holding. Git will not
convert a blob that is already stored with CRLF: `text=auto` normalises a file whose index entry is LF or
absent, and leaves an existing CRLF entry alone so that a plain `git add` cannot silently rewrite a file
somebody meant to keep that way. So a file that was CRLF before the policy existed stays CRLF through
every subsequent edit unless someone runs `git add --renormalize` on it.

Two such files survived the repository wide renormalisation of 2026-08-31 and were found by scanning the
stored blobs rather than the working tree. That is the check this script performs, and the reason it
exists in CI: the symptom of the defect is not a failure, it is a diff that rewrites an entire file and
hides the actual change from review, which is a thing a reviewer notices only if they were going to read
the diff carefully anyway.

Run: `uv run python tools/check_line_endings.py`
Fix: `git add --renormalize <path>` then commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Declared binary in .gitattributes, so git never inspects or converts them.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".zip",
        ".gz",
        ".bundle",
        ".wav",
        ".mp3",
        ".m4a",
    }
)

# Declared CRLF in .gitattributes. The blob is still stored LF and converted on checkout, so a CRLF blob
# for one of these is the same defect as for anything else.
CRLF_ON_CHECKOUT = frozenset({".ps1", ".bat", ".cmd"})


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, check=True, text=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


def blob_of(path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{path}"], capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else b""


def main() -> int:
    offenders: list[tuple[str, int]] = []
    scanned = 0

    for path in tracked_files():
        if Path(path).suffix.lower() in BINARY_SUFFIXES:
            continue
        blob = blob_of(path)
        if not blob:
            continue
        scanned += 1
        count = blob.count(b"\r\n")
        if count:
            offenders.append((path, count))

    if not offenders:
        print(f"line endings pass: {scanned} tracked text blobs, all stored LF")
        return 0

    print(f"{len(offenders)} tracked blob(s) are stored with CRLF, against the declared policy:")
    for path, count in offenders:
        suffix = Path(path).suffix.lower()
        note = (
            " (checked out as CRLF by policy, but the blob must still be LF)"
            if suffix in CRLF_ON_CHECKOUT
            else ""
        )
        print(f"  {path}: {count} CRLF line(s){note}")
    print()
    print("Fix with:")
    print("  git add --renormalize " + " ".join(path for path, _ in offenders))
    print()
    print(
        "Why this matters: an editor that writes CRLF into one of these produces a diff rewriting "
        "every line, which hides the real change from review."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
