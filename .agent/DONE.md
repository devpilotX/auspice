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

Run twice. The first run found two defects and both were fixed rather than worked around, which is what
the gate is for.

First run: `tests/unit/test_backup.py::TestBinaryDiscovery::test_the_client_binaries_are_found` failed,
because it asserted an environment precondition. `.tools/` is ignored and created by
`infra/scripts/bootstrap-postgres.ps1`, so a clone that has not been bootstrapped has no client binaries
and no defect. It now skips with that reason and still fails if `pg_dump` is on PATH and undiscoverable.

Also first run: `pyproject.toml` checked out with CRLF despite `.gitattributes` declaring `eol=lf`.
Scanning stored blobs rather than the working tree showed why. Git will not convert a blob already stored
as CRLF, so two files that predated the policy survived the repository wide renormalisation.
`tools/check_line_endings.py` now scans blobs and runs in CI.

Second run, from a clone at `571883d`:

```
uv sync --all-extras                                  ok
uv run ruff check .                                   All checks passed!
uv run ruff format --check .                           148 files already formatted
uv run python -m mypy                                  Success: no issues found in 121 source files
uv run python tools/check_writing.py                   writing rules pass: 180 files checked
uv run python tools/check_line_endings.py              253 tracked text blobs, all stored LF
uv run python -m pytest -q                             532 passed, 1 skipped
npm ci                                                 ok
npm run types:generate && npm run types:check          openapi document and generated types are current
npm run lint                                           clean
npm run typecheck                                      clean
npm run check:tokens --workspace apps/web              77 defined, 34 files checked
npm run test --workspace apps/web                      43 passed
npm run build --workspace apps/web                     ok
npm run budget --workspace apps/web                    within budget
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
