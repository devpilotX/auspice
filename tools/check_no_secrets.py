"""Pre-push credential scan. Looks for credential *values*, not the pattern strings that describe them.

The plain pickaxe search reports every file that mentions `github_pat_`, which includes this repository's
own security documentation and the secret scanning regex in the IRONCLAD skill file. Those are references,
not credentials. This looks for the shape of an actual value: the prefix followed by enough characters to
be a real token.

Scans every blob reachable from every ref, so a value on any branch or tag is found even if no branch tip
still contains it.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Value shapes, not mentions. Each requires the length a real credential has.
PATTERNS = {
    "github fine grained PAT": re.compile(rb"github_pat_[A-Za-z0-9_]{50,}"),
    "github classic PAT": re.compile(rb"ghp_[A-Za-z0-9]{36}"),
    "github oauth token": re.compile(rb"gho_[A-Za-z0-9]{36}"),
    "aws access key id": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "anthropic key": re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai key": re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    "slack token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "private key block": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

# A connection URL carrying a real password is a credential. One carrying a placeholder, a shell variable
# reference, or an ephemeral service credential bound to localhost is documentation, and flagging it makes
# this gate noise. A gate that cries wolf gets muted, which is how a secret eventually gets through.
#
# The rule: flag a postgres URL only when the password is not a variable reference and not a known
# placeholder. Measured against this repository, that removes all ten matches and every one of them was
# documentation: `auspice:password@127.0.0.1` in .env.example, `auspice:auspice@127.0.0.1` for the CI
# service container, and `${POSTGRES_PASSWORD}` in the compose file.
POSTGRES_URL = re.compile(rb"postgres(?:ql)?(?:\+\w+)?://([^\s:@/]+):([^\s@/]{6,})@([^\s:/]+)")

PLACEHOLDER_PASSWORDS = {
    b"password",
    b"changeme",
    b"secret",
    b"postgres",
    b"auspice",
    b"example",
    b"replaceme",
    b"yourpassword",
}


def postgres_credentials(content: bytes) -> list[str]:
    """Connection URLs whose password looks real rather than illustrative."""
    findings: list[str] = []
    for match in POSTGRES_URL.finditer(content):
        password = match.group(2)
        # A placeholder of any kind is not a credential: shell expansion, an f-string field, or a
        # template variable. Measured: `{target.password}` in ops/backup.py is where the code builds a
        # connection URL from configuration, which is the correct way to do it and is not a secret.
        if password[:1] in (b"$", b"{", b"<", b"%") or password.startswith(b"${"):
            continue
        if password.lower() in PLACEHOLDER_PASSWORDS:
            continue
        findings.append(f"postgres url with a non placeholder password, {len(password)} chars")
    return findings


def blobs() -> list[tuple[str, str]]:
    """Every blob reachable from every ref, as (sha, path)."""
    out = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    found = []
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            found.append((parts[0], parts[1]))
    return found


def main() -> int:
    candidates = blobs()
    hits: list[str] = []
    scanned = 0

    for sha, path in candidates:
        kind = (
            subprocess.run(["git", "cat-file", "-t", sha], capture_output=True, check=False)
            .stdout.decode()
            .strip()
        )
        if kind != "blob":
            continue
        content = subprocess.run(
            ["git", "cat-file", "blob", sha], capture_output=True, check=False
        ).stdout
        if not content or b"\x00" in content[:8000]:
            continue
        scanned += 1
        for name, pattern in PATTERNS.items():
            match = pattern.search(content)
            if match:
                # Report the location and the shape, never the value.
                hits.append(f"{name} in {path} (blob {sha[:12]}), {len(match.group(0))} chars")
        for finding in postgres_credentials(content):
            hits.append(f"{finding} in {path} (blob {sha[:12]})")

    print(f"scanned {scanned} text blobs across every ref")
    if hits:
        print(f"{len(hits)} credential shaped value(s) found:")
        for hit in hits:
            print(f"  {hit}")
        print()
        print("Do not push. A value in a commit object is in history forever.")
        return 1
    print("no credential shaped values in any blob. Safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
