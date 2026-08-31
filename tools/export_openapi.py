"""Write the OpenAPI document to disk.

Reads it out of the FastAPI application object rather than over HTTP, so generating types needs no
running server and no port. That matters for CI, where booting the API to describe itself is an extra
failure mode for no benefit, and it means the document cannot disagree with the code that produced it.

The output is sorted and written with a trailing newline so a regeneration that changes nothing produces
no diff. ``npm run generate --workspace packages/shared-types`` consumes it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESTINATION = REPO_ROOT / "packages" / "shared-types" / "openapi.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DESTINATION,
        help="Where to write. Defaults to the committed location.",
    )
    arguments = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from app.main import app

    document = app.openapi()
    destination: Path = arguments.out
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    previous = destination.read_text(encoding="utf-8") if destination.exists() else None
    # newline="" so "\n" is written as one byte rather than translated to the platform's line ending.
    # Without it this file is CRLF on Windows and LF everywhere else, while .gitattributes stores the blob
    # as LF, so a fresh clone checks out LF and a regeneration produces CRLF. `npm run types:check` then
    # compares the two and reports the document as stale when only the newlines differ. That is exactly
    # what happened: the check passed on the machine that wrote the file and failed on a clean clone, which
    # is the worst shape a check can have. Found by the IRONCLAD Gate 6 run.
    destination.write_text(rendered, encoding="utf-8", newline="\n")

    paths = len(document.get("paths", {}))
    schemas = len(document.get("components", {}).get("schemas", {}))
    state = "unchanged" if previous == rendered else "written"
    print(f"{state}: {destination}  {paths} paths, {schemas} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
