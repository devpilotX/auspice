# Plan

Status values: TODO, DOING, DONE, PARKED.

Resume rule: on any context loss, read all files in `.agent/`, then run `git log --oneline -20` and
`git tag -l "checkpoint/*"`, then run the battery. Test output is ground truth, not this file. Reconcile
this file against reality before continuing, and resume at the first TODO.

## Phase A, safety net

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Checkpoint and backup | DONE | bundle verified twice, scratch clone at `2d8efdf` with 218 files, 87 ignored files snapshotted |
| 1b | Baseline battery measured before any change | DONE | recorded in `PROGRESS.md`, 11 layers, one red (ENV-01) diagnosed and fixed |
| 2 | `.agent/` scaffold and `AUDIT_REPORT.md` | DONE | 9 files plus the report, committed at checkpoint/002 |
| 3 | Unit coverage for `site-list.ts` and `published-doc.ts` | DONE | tests already existed; Vitest attempt reverted, 14 cases ported, unit project 21 to 35 |
| 4 | Wire the Playwright suite into CI | DONE | web job runs the unit project; new visual job on windows-latest; YAML validated by parse |

## Phase B, ship blockers

| # | Task | Status | Evidence |
|---|---|---|---|
| 5 | `infra/Dockerfile.api`, production CORS, TLS proxy | DONE | Dockerfile, .dockerignore, Caddyfile, compose CORS. Build parked as D-001 |
| 6 | Define the `memo` extra | DONE | extra plus lock; StageUnavailableError path verified |
| 7 | Route handler so `/portfolio` works without a client side key | DONE | 8 guard tests; sentinel key absent from client output |

## Phase C, correctness

| # | Task | Status | Evidence |
|---|---|---|---|
| 8 | `healthz` reports a degraded database | DONE | three defects; proved tests fail against the original |
| 9 | Move blocking work off the event loop | DONE | 12 handlers, route table guard, proved by reverting one |
| 10 | Bound the cost of unauthenticated endpoints | DONE | three parts: verify_head, digest keyed cache, streamed export |
| 11 | Remove the scoring savepoint, drop unused `slowapi` | DONE | ADR-002. Savepoint removed rather than capped, 9 tests, checkpoint/020 |

## Phase D, rename

| # | Task | Status | Evidence |
|---|---|---|---|
| 12 | Brand surface to Permission Bureau | DEFERRED to last | ADR-001. See A-016: it is pure copy, it depends on a trademark opinion the operator does not have, and doing it after every feature exists is one pass over final copy instead of two |
| 13 | Code namespace rename | PARKED | A-002, deliberately last and parkable |

## Phase E, the binding constraint

| # | Task | Status | Evidence |
|---|---|---|---|
| 14 | Labelling console | DONE | `labels quote` and `labels add`, 32 tests, exercised against a live county source, checkpoint/021 |
| 15 | Extraction accuracy against the golden set | PARKED | D-003, no key available |
| 16 | Corpus backfill for the twelve counties | TODO | |
| 17 | Start the ledger accruing | TODO | |
| 18 | External ledger anchoring | TODO | |

## Phase F, product and operations

| # | Task | Status | Evidence |
|---|---|---|---|
| 19 | Rule change watch as a surface | TODO | |
| 20 | Alert delivery | TODO | |
| 21 | Error tracking, metrics, backups | TODO | |
| 22 | Portfolio as an async job | TODO | |
| 23 | Artefact serving seam, trust instrumentation | TODO | |
| 24 | Time to decision, remaining feature gaps | TODO | |
| 25 | Sweep, Gate 6, report closure | TODO | |

## Ordering note

Phase C precedes Phase D so the rename does not sit on top of unfixed bugs and make every later diff
unreadable. Task 13 is last because it is the riskiest and least valuable work in the plan.
