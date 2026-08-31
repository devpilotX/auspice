# Definition of Done

This file, not the agent's judgment, decides when the run ends. Status is live.

Legend: PASS means verified by execution in this run with the output recorded.
BASELINE means it was already green before the agent started and must stay green.
OPERATOR means the agent cannot execute it under the constraints of this run and it is handed over.

| # | Criterion | Verification | Status |
|---|---|---|---|
| 1 | Ruff lint and format clean | `uv run ruff check . && uv run ruff format --check .` | PASS, 148 files formatted |
| 2 | Strict mypy clean | `uv run python -m mypy` | PASS, 121 source files |
| 3 | Python tests green | `uv run python -m pytest -q` | PASS, 533 passed |
| 4 | No migration drift | `alembic check` plus `test_no_pending_migration` | PASS, at 0004_alert_delivery |
| 5 | Corpus valid | `auspice registry validate && auspice labels validate` | PASS, registry and labels validate |
| 6 | Web static checks | `eslint`, `tsc --noEmit`, `check-tokens` | PASS |
| 7 | Web builds within budget | `next build && check-budget` | PASS, within budget |
| 8 | JS unit tests green | `npm run test --workspace apps/web` | PASS, 43, and the script now exists |
| 9 | Visual suite green | `npm run test:visual --workspace apps/web` | OPERATOR, needs a server |
| 10 | OpenAPI to TS contract current | `check-types-current` | PASS, regenerated after the anchor field |
| 11 | Writing rules pass | `check_writing.py` | PASS, 180 files |
| 12 | Container stack starts, API answers | `docker compose up` then `/healthz` | OPERATOR, docker absent |
| 13 | Memo renders a PDF | `auspice memo render` in the container | OPERATOR, docker absent |
| 14 | Portfolio works from a browser, no key client side | Playwright plus bundle grep | PARTIAL, grep runnable, browser is OPERATOR |
| 15 | Health check reports degraded when DB is down | unit test with unreachable DB | PASS, and proved to fail against the original handler |
| 16 | Health check not blocked by a slow score | concurrency test | PASS, asserted by walking the route table |
| 17 | Ledger verification incremental, still catches tail deletion | unit tests on clean, tampered, truncated chains | PASS, 49 ledger tests including the naive key collision |
| 18 | Public brand reads Permission Bureau | grep for user visible old name plus visual suite | PENDING, deferred to the end of the run. See A-016 |
| 19 | Fresh clone reproducibility | IRONCLAD Gate 6 from a temp clone | **PASS 2026-08-31.** See the evidence below |
| 20 | `AUDIT_REPORT.md` traces every finding to a status | manual read | PENDING |
| 21 | Deferred queue swept | every CRITICAL and HIGH item retried by a different route | PENDING |
| 22 | SEC-01 recorded and the credential path closed in git | `git check-ignore` plus `git log -S` finding no token | PARTIAL, path closed, revocation is OPERATOR |
| 23 | Line endings match the declared policy | `tools/check_line_endings.py` | PASS, 253 tracked text blobs all stored LF, wired into CI |
| 24 | Alerts are delivered, not just recorded | 32 tests plus `auspice monitor health` | PASS |
| 25 | Every 500 carries an identifier a customer can quote | 26 tests on the outermost handler | PASS |
| 26 | Backups restore, proved rather than checksummed | `auspice ops verify` | PASS, verdict pass on a 1.3 MB dump of the live database |
| 27 | The ledger head can be anchored externally | 22 tests plus `auspice ledger anchors` | PASS, mechanism built. No anchor held, and the page says so |

## Gate 6 evidence, 2026-08-31

Run four times. It found five defects that no local run could, which is the entire argument for the gate.
Every one was fixed rather than worked around.

1. `test_the_client_binaries_are_found` asserted an environment precondition rather than a code property.
   `.tools/` is ignored and created by the bootstrap script, so a clone that has not been bootstrapped has
   no client binaries and no defect. It now skips with that reason, and still fails if `pg_dump` is on
   PATH and undiscoverable.
2. `pyproject.toml` checked out CRLF despite `.gitattributes` declaring `eol=lf`. Git will not convert a
   blob already stored as CRLF, so two files predating the policy survived the repository wide
   renormalisation. `tools/check_line_endings.py` now scans stored blobs and runs in CI.
3. ruff had never run against `tools/check_line_endings.py`, because it was added and only the writing
   check was run against it.
4. `scripts/check-types-current.mjs` joined the repository root with `node_modules` to find the
   openapi-typescript CLI, which worked only while npm happened to hoist that package. Regenerating the
   lock for the postcss override moved it, and the check began failing with "Cannot find module". It now
   reads the package's own `bin` field.
5. `packages/shared-types/src/generated/` was gitignored while `types:check` compares against it and
   `tsc` compiles against it, so **the CI web job could not have been passing**. Now tracked. And
   `tools/export_openapi.py` wrote platform newlines, so a clone checked out LF and a regeneration
   produced CRLF and the document was reported stale when only the newlines differed.

Final run, from a clone at `cb200f2`, every command's exit code recorded:

```
uv sync --all-extras                                   0
npm ci                                                 0
uv run ruff check .                                    0
uv run ruff format --check .                           0
uv run python -m mypy                                  0
uv run python tools/check_writing.py                   0
uv run python tools/check_line_endings.py              0
uv run python -m pytest -q                             0   623 passed, 1 skipped
npm run audit:check                                    0   0 advisories, 0 allowed
npm run types:check                                    0
npm run lint                                           0
npm run typecheck                                      0
npm run check:tokens --workspace apps/web              0
npm run test --workspace apps/web                      0   72 passed
npm run build --workspace apps/web                     0
npm run budget --workspace apps/web                    0
```

The one skip is the client binary test above, with its reason printed. `.env` was copied in, because the
database tests need a connection string and the documented setup creates it from `.env.example`.


## Criteria the agent added

Criterion 22 is not in the original plan. It was added because the run found a live credential in the
working tree before its first commit, and closing that path is a real exit condition rather than an
incidental note. Revoking the token is the operator's action and cannot be done by the agent.

## What would make this run a failure even with everything above green

- Any commit on `main`.
- Any constant changed in `src/auspice/models/eval/thresholds.py`.
- Any row added to `data/labels/decisions.yaml` that does not pass `auspice labels verify`.
- Any contact with the remote.
- A criterion marked PASS without recorded command output.
