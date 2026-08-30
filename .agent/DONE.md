# Definition of Done

This file, not the agent's judgment, decides when the run ends. Status is live.

Legend: PASS means verified by execution in this run with the output recorded.
BASELINE means it was already green before the agent started and must stay green.
OPERATOR means the agent cannot execute it under the constraints of this run and it is handed over.

| # | Criterion | Verification | Status |
|---|---|---|---|
| 1 | Ruff lint and format clean | `uv run ruff check . && uv run ruff format --check .` | BASELINE PASS |
| 2 | Strict mypy clean | `uv run python -m mypy` | BASELINE PASS |
| 3 | Python tests green | `uv run python -m pytest -q` | BASELINE PASS, 309 passed |
| 4 | No migration drift | `alembic check` plus `test_no_pending_migration` | BASELINE PASS |
| 5 | Corpus valid | `auspice registry validate && auspice labels validate` | PENDING |
| 6 | Web static checks | `eslint`, `tsc --noEmit`, `check-tokens` | PASS after ENV-01 fix |
| 7 | Web builds within budget | `next build && check-budget` | BASELINE PASS |
| 8 | JS unit tests green | `npm run test --workspace apps/web` | PENDING, framework absent |
| 9 | Visual suite green | `npm run test:visual --workspace apps/web` | OPERATOR, needs a server |
| 10 | OpenAPI to TS contract current | `check-types-current` | BASELINE PASS |
| 11 | Writing rules pass | `check_writing.py` | BASELINE PASS, 158 files |
| 12 | Container stack starts, API answers | `docker compose up` then `/healthz` | OPERATOR, docker absent |
| 13 | Memo renders a PDF | `auspice memo render` in the container | OPERATOR, docker absent |
| 14 | Portfolio works from a browser, no key client side | Playwright plus bundle grep | PARTIAL, grep runnable, browser is OPERATOR |
| 15 | Health check reports degraded when DB is down | unit test with unreachable DB | PENDING |
| 16 | Health check not blocked by a slow score | concurrency test | PENDING |
| 17 | Ledger verification incremental, still catches tail deletion | unit tests on clean, tampered, truncated chains | PENDING |
| 18 | Public brand reads Permission Bureau | grep for user visible old name plus visual suite | PENDING |
| 19 | Fresh clone reproducibility | IRONCLAD Gate 6 from a temp clone | PENDING |
| 20 | `AUDIT_REPORT.md` traces every finding to a status | manual read | PENDING |
| 21 | Deferred queue swept | every CRITICAL and HIGH item retried by a different route | PENDING |
| 22 | SEC-01 recorded and the credential path closed in git | `git check-ignore` plus `git log -S` finding no token | PARTIAL, path closed, revocation is OPERATOR |

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
