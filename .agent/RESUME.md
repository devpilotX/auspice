# Resume here

If you are a new session with no memory of this work, read this file first, then run the commands in
"Verify before trusting anything". Do not trust this file over the test output.

Last updated 2026-08-31T11:15 (+05:30).

## The one line

An audit of the codebase turned into a repair and build run. Nineteen of twenty five planned tasks are
done plus six defects found during the run and not in the plan, all verified by execution. The branch is
`agent/permission-bureau-20260830-172555`. `main` is untouched at `2d8efdf`.

## Verify before trusting anything

```powershell
cd C:\Dev\apps\auspice
git log --oneline 2d8efdf..HEAD          # should show 39 commits
git rev-parse --short main               # must print 2d8efdf
uv run python -m pytest -q               # should print 624 passed
npm run test --workspace apps/web        # should print 72 passed
uv run python tools/check_line_endings.py
npm run audit:check                      # should print 0 advisories, 0 allowed
```

Test output is ground truth. This file is a summary and can be stale.

## Read these next, in this order

| File | What it holds |
|---|---|
| `AUDIT_REPORT.md` | The findings register, all corrections including two withdrawn findings, open gaps |
| `.agent/PLAN.md` | Every task with DONE, TODO or PARKED |
| `.agent/DONE.md` | Exit criteria with the real command output for each |
| `.agent/DECISIONS.md` | ADRs with rejected alternatives and unresolved dissents |
| `.agent/DEFERRED.md` | Parked items, and the sweep of 2026-08-31 |
| `.agent/BLOCKED.md` | The six things only the operator can do |
| `.agent/ASSUMPTIONS.md` | Assumptions and the cost of reversing each |
| `.agent/RESTORE.md` | How to undo everything, in two commands |

## Operator constraints that shaped every decision

1. **Never push to a remote.** A push was authorised on 2026-08-31 conditional on everything being
   verified end to end. Four tasks remain, so that condition is not met. When it is, push the agent
   branch, never `main`, never with force, and open a pull request.
2. **Never commit to `main`.** It has stayed at `2d8efdf` throughout.
3. **Never modify any constant in `src/auspice/models/eval/thresholds.py`.** Not one number. Held.
4. **Never fabricate a label.** No row enters `data/labels/decisions.yaml` without a real fetched source
   and a verbatim quote. Held, and it is why NEW-03 is deliberately left open.
5. **Do not start servers.** The operator runs them. Held. A headless browser fetching a remote page is
   not a server and was used, in `ingest/render.py`.
6. **Docker is not installed** on this machine.

## The state of the product, measured not assumed

| Measure | Value | How to check |
|---|---|---|
| Labelled terminal decisions | **1** of 400 required | `uv run auspice labels stats` |
| Citations verified | 17 of 21 | `uv run auspice labels verify` |
| Published ledger entries | 2, chain intact, none anchored | `uv run auspice ledger status`, `ledger anchors` |
| Ledger entries gradeable now | 0 | `uv run auspice ledger accrual` |
| Jurisdictions | 12, all with boundaries | `uv run auspice registry status` |
| Language model key | absent | `llm_provider` defaults to `none` |
| Python tests | 624 passing | `uv run python -m pytest -q` |
| Web unit tests | 72 passing, no server needed | `npm run test --workspace apps/web` |
| npm advisories | 0, and 0 on an allowlist | `npm run audit:check` |

The binding constraint on the business is still labelled decisions. Everything built in this run is
mechanism around a corpus that does not exist yet. That framing has not changed and should not be lost.

## What is done

Phases A, B and C complete. Tasks 12, 14, 17, 18, 20, 21 and 24 complete. Gate 6 passed twice.

- **Task 11**, ADR-002. The scoring savepoint is removed rather than capped: prospective scoring performs
  no write at all. A cap would have had to be at least 500 to leave the documented portfolio working.
- **Task 12**. The public brand reads Permission Bureau. Code namespace is Task 13 and is untouched.
- **Task 14**. The labelling console: `labels quote` and `labels add`. A quote is selected out of the
  parsed document rather than retyped, so exact transcription stops being something a human can get wrong.
- **Task 17**. `ledger reconcile` and `ledger accrual`. The record now accrues by itself.
- **Task 18**. `ledger anchor` and `ledger anchors`, exposed on the accuracy endpoint.
- **Task 20**. Alert delivery: three channels, migration 0004, four CLI commands.
- **Task 21**. Request identifiers, an outermost error handler, gated Prometheus metrics, and backups whose
  restore is proved rather than checksummed.
- **Task 24**. Both halves. The two parcel geometry features could not fire at all, and per member votes
  now give the board composition features a route to a value from hand labelling.

Found during the run and not in the audit: NEW-02 through NEW-06, four postcss advisories patched rather
than allowlisted, and a line ending policy that was declared and not held.

## What remains

| Task | State | Note |
|---|---|---|
| 13 | PARKED | Code namespace rename. Riskiest, least valuable, deliberately last. |
| 15 | PARKED | Extraction accuracy. Needs a language model key. |
| 16 | **next** | Corpus backfill across the twelve counties. Hours of polite crawling. |
| 19 | todo | Rule change watch as a product surface. |
| 22 | todo | Portfolio as an async job. |
| 23 | todo | Artefact serving seam, evidence drawer analytics. |
| 25 | todo | Final sweep and report closure. |

## Things a new session must not rediscover the hard way

**The test databases diverge locally.** `AUSPICE_DATABASE_URL` names `auspice` and
`AUSPICE_TEST_DATABASE_URL` names `auspice_test`. In CI both name `auspice_test`. Use the `api_client`
fixture in `tests/conftest.py`. An autouse guard raises with an explanation if you forget.

**Line endings are now mechanism, not vigilance.** `.gitattributes` declares `* text=auto eol=lf` and
`tools/check_line_endings.py` runs in CI. Git will not convert a blob already stored as CRLF, so a new
CRLF file needs `git add --renormalize`. The check tells you which.

**npm will not apply a new override to an existing tree.** `npm install` reports "up to date" and skips
resolution. Both `package-lock.json` and `node_modules` have to go first. This cost six attempts.

**PowerShell here-strings mangle backticks.** Writing `.agent` files through the shell produced two bell
characters. Use the file writer.

## Mistakes made in this run, kept on purpose

An audit that deletes its errors cannot be checked. Two findings from earlier runs are recorded in
`AUDIT_REPORT.md` under Corrections, and this run added a third.

**NEW-04 was wrong on both counts.** It claimed two cited sources cannot be verified because they render
client side, inferred from one measurement of extracted text length. wsbtv.com is geo-blocked and answers
HTTP 451. cbs2iowa.com was already verifying and its plain fetch produced 7636 characters against 7658
rendered. The evidence distinguishing the two causes was on screen and was not read.

**A test premise was wrong in `test_ledger_accrual.py`.** It asserted that manually grading an entry mid
queue produces a skip. The queue filters on `resolved_at`, so the entry is excluded and there is nothing to
skip. The replacement simulates the real race instead.

**Gate 6 caught two things local runs did not.** A test asserting an environment precondition, and ruff
never having run against a newly added tool file.

## What the operator should do next

In rough order of value.

1. **Revoke the GitHub personal access token** in `.kiro/settings/mcp.json` at
   https://github.com/settings/tokens. It never entered a commit, verified by pickaxe across all refs, and
   it sat in plain text in a working tree and was printed into a session transcript.
2. **Run the two gates the agent cannot.** `npm run test:visual --workspace apps/web`, which now needs its
   baselines re-recorded because the brand rename changed the header wordmark, and if Docker is installed,
   `docker compose -f infra/docker-compose.yml up -d`.
3. **Decide the corpus route.** Supply a language model key so extraction can be measured against
   `tests/golden/`, or accept hand labelling, for which the console now exists.
4. **Settle the Linn County adoption date**, B-005. The row cites a source that describes a different
   event and the agent would not guess a labelled fact.
5. **Register the domains** if ADR-001 stands, and **get a trademark clearance opinion** before spending
   on the brand. The rename is done in code and is one pass to redo if the opinion goes the other way.
