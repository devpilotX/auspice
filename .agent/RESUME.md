# Resume here

If you are a new session with no memory of this work, read this file first, then run the four commands in
"Verify before trusting anything" below. Do not trust this file over the test output.

Last updated 2026-08-31T07:55 (+05:30).

## The one line

An audit of the Auspice codebase turned into a repair run. Ten of twenty five planned tasks are done, plus one defect found during the run and not in the plan,
all verified by execution. The branch is `agent/permission-bureau-20260830-172555`. `main` is untouched at
`2d8efdf`.

## Verify before trusting anything

```powershell
cd C:\Dev\apps\auspice
git log --oneline 2d8efdf..HEAD          # should show 18 commits
git tag -l "checkpoint/*"                # should show 18 tags
git rev-parse --short main               # must print 2d8efdf
uv run python -m pytest -q               # should print 351 passed
```

Test output is ground truth. This file is a summary and can be stale.

## Read these next, in this order

| File | What it holds |
|---|---|
| `AUDIT_REPORT.md` | The findings register, all corrections, the domain and trademark record, open gaps |
| `.agent/PLAN.md` | Every task with DONE, TODO or PARKED |
| `.agent/PROGRESS.md` | Timestamped log of what happened and why, including mistakes |
| `.agent/DECISIONS.md` | Architectural decisions with rejected alternatives and unresolved dissents |
| `.agent/DEFERRED.md` | Parked items with impact ratings and alternate routes |
| `.agent/BLOCKED.md` | The four things only the operator can do |
| `.agent/ASSUMPTIONS.md` | Assumptions and the cost of reversing each |
| `.agent/RESTORE.md` | How to undo everything, in two commands |

## Operator constraints that shaped every decision

1. **Never push to a remote** was a hard prohibition for most of the run. On 2026-08-31 the operator
   authorised a push conditional on everything being verified end to end. That condition is not met.
   When it is, push the agent branch, never `main`, never with force, and open a pull request.
2. **Never commit to `main`.** It has stayed at `2d8efdf` throughout.
3. **Never modify any constant in `src/auspice/models/eval/thresholds.py`.** Not one number.
4. **Never fabricate a label.** No row enters `data/labels/decisions.yaml` without a real fetched source
   and a verbatim quote that passes `auspice labels verify`.
5. **Do not start servers.** The operator runs them. Stated 2026-08-30T18:30.
6. **Docker is not installed** on this machine.

## The state of the product, measured not assumed

| Measure | Value | How to check |
|---|---|---|
| Labelled terminal decisions | **1** of 400 required | `uv run auspice labels stats` |
| Distinct outcome classes | 1 | same |
| Published ledger entries | **2**, chain intact | `uv run auspice ledger status` |
| Jurisdictions in `auspice` | 12, all with boundaries | `uv run auspice registry status` |
| Jurisdictions in `auspice_test` | 0 | see the database divergence note below |
| Language model key | absent | `llm_provider` defaults to `none` |
| Python tests | 351 passing | `uv run python -m pytest -q` |
| Web unit tests | 43 passing | `npx playwright test --project=unit` inside `apps/web` |

The binding constraint on the business is labelled decisions. Everything repaired so far is plumbing
around a corpus that does not exist yet. That framing has not changed and should not be lost.

## What is done

Phases A, B and C are complete except Task 11.

- **Phase A**, safety net. Local bundle backup verified twice by cloning it. `.agent/` artifacts.
  `AUDIT_REPORT.md`. Playwright wired into CI for the first time, plus a `visual` job on windows-latest
  because every committed baseline is `-win32.png` and Playwright suffixes snapshots by platform.
- **Phase B**, all four P0 blockers. `infra/Dockerfile.api` written, plus a `.dockerignore` that took the
  build context from about 4000 MB to 7.8 MB, and a Caddy TLS proxy. Production CORS no longer inherits
  the localhost default. The `memo` extra now exists, so the instruction `generator.py` always printed is
  finally true. A server side route handler means the portfolio screen works in a browser without a key
  in the client bundle.
- **Phase C**, three of four. The health check reports a degraded database instead of a 500. Twelve
  handlers moved off the event loop. All three unbounded cost problems on the unauthenticated endpoints
  closed.
- **NEW-01**, not in the original audit and more consequential than most of it. See below.

## What remains

| Task | State | Note |
|---|---|---|
| 11 | **next** | Cap scoring savepoints, drop unused `slowapi`. Closes Phase C. |
| 12 | todo | Brand rename to Permission Bureau. See ADR-001. |
| 13 | parked | Code namespace rename. Riskiest, least valuable, deliberately last. |
| 14 | todo | **The labelling console. The only task that moves 1 label toward 400.** |
| 15 | parked | Extraction accuracy. Needs a language model key. |
| 16 | todo | Corpus backfill across the twelve counties. Hours of polite crawling. |
| 17 | todo | Scheduled publishing and grading. Note the ledger already holds 2 entries. |
| 18 | todo | External anchoring. `AUSPICE_LEDGER_ANCHOR_URL` exists and is unused. |
| 19 | todo | Rule change watch as a product surface. Strongest new product finding. |
| 20 | todo | Alert delivery. `monitor/watcher.py` writes rows and nothing sends them. |
| 21 | todo | Error tracking, metrics, tested backups. |
| 22 | todo | Portfolio as an async job. |
| 23 | todo | Artefact serving seam, evidence drawer analytics. |
| 24 | todo | Time to decision surfacing, per member votes, parcel geometry. |
| 25 | todo | Sweep, Gate 6 fresh clone, report closure. |

## Two things a new session must not rediscover the hard way

**The test databases diverge locally.** `AUSPICE_DATABASE_URL` names `auspice` and
`AUSPICE_TEST_DATABASE_URL` names `auspice_test`. In CI both name `auspice_test`. A `TestClient` request
resolves `app.deps.get_connection`, which uses the non test engine, so without an override an endpoint test
reads a different database from the one the fixtures write to. This made the tile tests pass against
boundaries no test created. Use the `api_client` fixture in `tests/conftest.py`. An autouse guard now
raises with an explanation if you forget.

**The file writer emits CRLF.** The repository is predominantly LF, with `pyproject.toml`, `public.py`,
`score.py`, `test_abstention_and_score.py` and `conftest.py` as CRLF. Editing a file without preserving
its endings produces a diff that rewrites every line and hides the real change. This happened four times.
Check `git diff --numstat` after every edit and repair before committing. See D-DEV-02.

## Mistakes made in this run, kept on purpose

An audit that deletes its errors cannot be checked.

1. **Finding P1-6 was false.** Claimed apps/web had no JavaScript tests. It had 242 lines of them in
   `apps/web/tests/unit/`, running in Playwright's `unit` project, whose config explicitly rejects a second
   test framework. I added Vitest anyway, then reverted it in `e5b0559` and ported the 14 genuinely new
   cases into the existing specs. Cause: asserted from a dependency grep instead of a directory listing.
2. **Claimed the ledger was empty.** It holds 2 entries. Cause: read the README and a code path instead of
   running the query.
3. **Introduced a bug while fixing one.** Catching the ledger exception in `healthz` made a previously
   unreachable state reachable, where `chain_ok is not False` reported `status: ok` alongside a detail line
   saying verification had failed. The test caught it on its first full run.
4. **Wrote a test that passed for the wrong reason.** The ledger health test passed in isolation only
   because `app.state.models` was absent. It would have kept passing with the ledger logic deleted.

## What the operator should do next

In rough order of value.

1. **Revoke the GitHub personal access token** in `.kiro/settings/mcp.json` at
   https://github.com/settings/tokens. It never entered a commit, verified by pickaxe across all refs, but
   it sat in plain text in a working tree and was printed into a session transcript.
2. **Run the two gates the agent cannot.** `npm run test:visual --workspace apps/web`, and if Docker gets
   installed, `docker compose -f infra/docker-compose.yml up -d`.
3. **Decide the corpus route.** Either supply a language model key so extraction can be measured against
   `tests/golden/`, or accept hand labelling and prioritise Task 14 so the console exists to do it with.
4. **Register the domains** if ADR-001 stands: `permissionbureau.com` and `permissionrisk.com`, both
   verified available by five methods on 2026-08-30.
5. **Get a trademark clearance opinion** before spending anything on the brand.
