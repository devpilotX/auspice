"""Check the writing rules.

Every word in this product is meant to read as though a person wrote it. Some of that is judgement and
cannot be automated. A useful amount of it is mechanical, and the mechanical part is worth enforcing in CI
rather than remembering.

What this catches:

  em dashes and en dashes inside sentences
  the banned vocabulary: seamless, robust, leverage as a verb, unlock, delve, empower, and the rest
  "not just X, it is Y" and its variants
  emoji anywhere in the product or the docs
  three consecutive sentences opening with the same word
  the hedge phrases that replace an honest admission, like "insufficient data available at this time"

What it deliberately does not catch: sentence length variation, rhythm, whether a paragraph earns its
place. Those need a person reading it out loud, which is the actual rule.

Run: python tools/check_writing.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Everything a reader sees, plus the source comments, because a comment that reads like a press release
# is a comment nobody trusts.
INCLUDE_GLOBS = (
    "docs/*.md",
    "README.md",
    "src/auspice/**/*.py",
    "src/auspice/**/*.html",
    "apps/api/**/*.py",
    "apps/web/src/**/*.ts",
    "apps/web/src/**/*.tsx",
    "apps/web/src/**/*.css",
    "data/labels/*.md",
    "data/registry/*.yaml",
    "data/labels/*.yaml",
    "infra/scripts/*.ps1",
    "infra/migrations/**/*.py",
    "tests/**/*.py",
    "tools/*.py",
    "scripts/*.mjs",
    "apps/web/scripts/*.mjs",
)

EXCLUDE_PARTS = (
    "node_modules",
    ".next",
    ".venv",
    "AUSPICE_Master_Spec.md",
    "AUSPICE_BUILD_PROMPT.md",
    # This file necessarily contains the banned vocabulary, because it is the list.
    "check_writing.py",
)

# A line ending with this marker is exempt, and the marker is only for text that states the rule rather
# than breaking it. There are two legitimate uses in the codebase: the README section describing the
# writing rules, and the extraction prompt that tells a model which words to avoid. Anything else using
# it is someone arguing with the linter, which is visible in a diff.
ALLOW_MARKER = "writing-rules-allow"

BANNED_WORDS = (
    "seamless",
    "seamlessly",
    "robust",
    "robustly",
    "unlock",
    "unlocks",
    "unlocking",
    "delve",
    "delves",
    "delving",
    "empower",
    "empowers",
    "empowering",
    "revolutionise",
    "revolutionize",
    "revolutionary",
    "game changing",
    "game-changing",
    "cutting edge",
    "cutting-edge",
    "at the end of the day",
    "in today's fast paced world",
    "in today's fast-paced world",
    "best in breed",
    "best-in-breed",
    "supercharge",
    "turnkey",
    "synergy",
    "synergies",
    "paradigm shift",
)

# "leverage" is only banned as a verb. As a noun it is a real word with a real meaning in finance.
LEVERAGE_AS_VERB = re.compile(
    r"\b(?:to\s+leverage|leverages|leveraged|leveraging)\b|\bleverage\s+(?:the|our|its|their|a|this)\b",
    re.I,
)

NOT_JUST = re.compile(
    r"\b(?:not\s+(?:just|only|merely|simply)\s+\w+[^.;:!?]{0,60},?\s*(?:it|it's|it is|but)\s)",
    re.I,
)

HEDGES = (
    "insufficient data available at this time",
    "at this time",
    "please note that",
    "it is important to note",
    "it should be noted",
    "we are unable to provide",
    "for your convenience",
)

EM_DASH = "\u2014"
EN_DASH = "\u2013"

# An en dash is allowed only inside a markdown table rule or a long ASCII-art separator, neither of which
# occurs in this codebase. Anywhere else it is prose and it is banned.
SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]+)")


def files() -> list[Path]:
    found: list[Path] = []
    for pattern in INCLUDE_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            if any(part in str(path) for part in EXCLUDE_PARTS):
                continue
            found.append(path)
    return sorted(set(found))


# Emoji, narrowly. An earlier version tested for Unicode category "So" above U+2100, which flagged every
# box drawing character in the README's directory tree. Category is the wrong tool: the emoji planes start
# at U+1F000, and the handful of dingbats that read as emoji are listed explicitly.
EMOJI_DINGBATS = frozenset(
    {
        0x2705,  # white heavy check mark
        0x274C,  # cross mark
        0x2728,  # sparkles
        0x2757,  # heavy exclamation
        0x26A0,  # warning sign
        0x2B50,  # star
        0x2764,  # heavy black heart
        0x203C,  # double exclamation
        0x2049,  # exclamation question
        0x1F32D,
    }
)


def is_emoji(character: str) -> bool:
    codepoint = ord(character)
    if codepoint >= 0x1F000:
        return True
    return codepoint in EMOJI_DINGBATS


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return problems

    lines = text.splitlines()

    for number, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        lowered = line.lower()

        if EM_DASH in line:
            problems.append(
                f"{path}:{number}: em dash. Use a comma, a colon, a full stop, or split it."
            )
        if EN_DASH in line:
            problems.append(f"{path}:{number}: en dash. Write '25 to 44' rather than a dash.")

        for word in BANNED_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                problems.append(f"{path}:{number}: banned phrase '{word}'.")

        if LEVERAGE_AS_VERB.search(line):
            problems.append(f"{path}:{number}: 'leverage' as a verb.")

        if NOT_JUST.search(line):
            problems.append(f"{path}:{number}: 'not just X, it is Y'. Say the thing directly.")

        for hedge in HEDGES:
            if hedge in lowered:
                problems.append(
                    f"{path}:{number}: hedge phrase '{hedge}'. Say the uncomfortable thing."
                )

        for character in line:
            if is_emoji(character):
                problems.append(
                    f"{path}:{number}: emoji U+{ord(character):04X}. None in the product, none in the docs."
                )
                break

    problems.extend(_repeated_openings(path, text))
    return problems


def _repeated_openings(path: Path, text: str) -> list[str]:
    """Three consecutive sentences opening with the same word.

    Checked per paragraph rather than across the whole file, because a heading resets the rhythm and a
    table of one word cells is not prose.
    """
    problems: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        stripped = block.strip()
        if not stripped or stripped.startswith(("#", "|", "```", "-", "*", ">")):
            continue
        openings = [match.group(1).lower() for match in SENTENCE_START.finditer(stripped)]
        run = 1
        for index in range(1, len(openings)):
            if openings[index] == openings[index - 1]:
                run += 1
                if run >= 3:
                    problems.append(
                        f"{path}: three consecutive sentences open with '{openings[index]}'. Vary it."
                    )
                    break
            else:
                run = 1
    return problems


def main() -> int:
    problems: list[str] = []
    checked = 0
    for path in files():
        checked += 1
        problems.extend(check(path))

    if not problems:
        print(f"writing rules pass: {checked} files checked")
        return 0

    for problem in problems:
        print(problem)
    print(f"\n{len(problems)} problem(s) across {checked} files.")
    print("Read the offending line out loud. If it sounds like a press release, rewrite it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
