# Session state, 2026-08-31

Written so that a cold start loses nothing. Read this first, then `.agent/VISUAL_GATE.md`,
`.agent/DEFERRED.md` and `AUDIT_REPORT.md`.

Everything below is either a recorded command output or a value read back from GitHub. Where something
was not verified it says so.

## Where things stand

| Thing | Value |
|---|---|
| Everything is on | `main`, at `d29a697baa7f444a3aa9502ef35980f2328d71cc` |
| That commit is | the merge of pull request #1, authored by devpilotX |
| `main` before the merge | `2d8efdf7fc2b7a7cf26dfb2e5c74c0d232980060` |
| Branch that carried the work | `agent/permission-bureau-20260830-172555`, merged at `ddcd7970`. Still present. Delete it from the pull request page if you want it gone; every commit on it is now reachable from `main` |
| CI on `main` | all four jobs green, run 33423519638 |

**`main` had never had a green pipeline before this.** Its only two earlier runs, 33057460017 and
33061610294, both concluded `failure`. Run 33423519638 is the first green one.

Evidence for that run, read job by job: python `99591417312` success, web `99591417543` success, writing
rules `99591417618` success, visual regression `99591417466` success with the `Build and visual
regression` step succeeding and the baseline commit step correctly skipped. The branch was independently
green first, on run 33389229249 at `ddcd7970`, where the visual log read `68 passed (43.5s)` with no
retries and pytest read `624 passed, 2 warnings in 44.38s` with nothing skipped.

One useful side effect: the Windows PostgreSQL cache is now saved at `main` scope. Branch scoped caches
cannot be read from other refs, which is why the first `main` run spent 63 seconds on `Start PostgreSQL`
instead of 9. Every later run on any branch can read it.

## Your local checkout is behind. Fix this first.

At the time of writing, local `HEAD` was `c25aa4ba9fd274af8398b6faece8ceb35e627091`, which is ten
commits behind what was pushed, and it is still sitting on the agent branch. The local
`.github/workflows/ci.yml` is the old 262 line version with no `AUSPICE_API_KEYS` and no
`update_snapshots`. Editing it before pulling would revert the CI repair.

```bash
git fetch origin
git checkout main
git pull
```

Nothing local was ever unpushed. All ten repair commits were made through the GitHub API, so the remote
was ahead of local rather than behind it.

Two tracked files were dirty locally and are not part of this work:
`.kiro/skills/autonomous-build/SKILL.md` and `.kiro/skills/deep-horizon-research/SKILL.md`, plus four
untracked directories under `.kiro/skills/`. If you ever commit those, run
`uv run python tools/check_no_secrets.py` first.

The 41 `checkpoint/000` to `checkpoint/041` tags do exist locally. They were never pushed.

## What was repaired, and why each commit exists

CI had never run green on this branch. Four independent causes, one commit each so the diff reads one
cause at a time.

| Commit | Cause it fixed |
|---|---|
| `cce6f407` | `postgis/postgis:17-3.5` carries no pgvector and the schema needs it. Added `infra/Dockerfile.db`, digest pinned, with checksum pinned pgvector 0.8.5, built in the job behind an extension readiness gate |
| `93844937` | kept every pre-existing gate while restructuring |
| `633bb8ed` | PostGIS 3.5 puts `tiger` and `topology` on the search path, so Alembic reflected them and reported drift that did not exist. `SET search_path TO public` before autogenerate compares |
| `e9895709` | `AUSPICE_ENV=test` with an empty key ring makes the app refuse to start, which failed two CORS tests. Added a CI only placeholder key. Also replaced a hanging `Invoke-WebRequest` probe with `http.client` |
| `17016e27` | ruled out the `uv.exe` intermediary by launching `python.exe -m uvicorn` directly |
| `b66522db` | the real one. A detached API survived a Windows step boundary but stopped answering loopback once its launch shell exited. API launch, health probe, build and the visual suite collapsed into one supervised PowerShell step |
| `4abae7e9` | added the data state diagnostic that prints both API payloads before the build |
| `98ae88e4` | added the `update_snapshots` workflow_dispatch input |
| `cf7a4073` | the re-recorded baselines, committed by `github-actions[bot]` |
| `ddcd7970` | `.agent/VISUAL_GATE.md` |
| `364a35e9` | this document |

Nothing was weakened to achieve this. `maxDiffPixelRatio` is still 0.002, no test was removed or
skipped, and `src/auspice/models/eval/thresholds.py` is byte identical to what was on `main`
(blob `3881f1d24286f9f17ff60005e788ad1482080ff3`).

## Things that will bite you if you forget them

- The visual job must stay on `windows-latest`. Playwright suffixes a snapshot with the platform that
  recorded it and every baseline is `-win32.png`.
- API launch, health probe, build and the Playwright run must stay in one PowerShell step. Splitting
  them reintroduces `b66522db`.
- Never set `AUSPICE_ENV=test` with an empty key ring.
- A push by `github-actions[bot]` produces a run with conclusion `action_required`. Dispatch a run
  manually to verify instead of waiting on it.
- The jurisdiction profile screenshot embeds the derived election dates 2027-11-02 and 2031-11-04. It
  will fail on its own after 2027-11-02. That is not a regression. Re-record with the
  `update_snapshots` dispatch input.

## Why your name is missing from the Contributors graph

Diagnosed, not guessed. Two independent causes.

**The graph counts the default branch only.** Before the merge all 58 commits were on a branch, so none
of them could appear. The merge fixes this half.

**Forty seven of the commits are authored `Auspice <build@auspice.local>`, which is linked to no GitHub
account.** Querying `main` for the commit `author` object returned no author and no committer object at
all, which is GitHub saying it cannot match that email to a user. The same query on the branch returned
`author.login: devpilotX` for the eleven commits made through the API.

So now that it is merged, eleven commits credit you and forty seven do not. `build@auspice.local` can
never be verified because `.local` cannot receive mail, so adding it to your account is not available.
The only way to attribute those forty seven is rewriting history, which changes every SHA and needs a
force push. That was not done and needs a deliberate decision.

Merge commits are excluded from the Contributors graph, so the merge commit itself adds nothing.

## Findings from the deep recheck, none of them fixed

These were found by audit on 2026-08-31 and deliberately left alone, because fixing them was not asked
for. Ranked by how much they matter. Every one carries the evidence that established it.

**1. `auspice eval kill-test` exits 0 when it reports FAIL.** `src/auspice/cli/model_cmd.py`, read
directly: on a FAIL verdict it prints FAIL, lists the failing gates, then falls off the end of the
function with no `typer.Exit(1)`. On INSUFFICIENT it raises `typer.Exit(0)` explicitly. CI does not run
it, only `auspice eval sufficiency`, which is honestly documented as informational. So this is not a
hole in CI today, but for the command the README calls the test that decides everything, a FAIL that
exits zero is a trap for whoever wires it into a pipeline.

**2. `tools/check_no_secrets.py` never runs.** `ci.yml` is the only workflow file in the repository and
it does not reference the script. There is no hooks directory and no pre-commit config. The pull
request description instructs reviewers to run it. Given a personal access token is already known to
have been exposed, this is the wrong gate to leave unwired.

**3. `tests/conftest.py` around lines 44 to 47 catches bare `Exception` and returns `False`.** A
malformed DSN or an unreadable `.env` silently skips all 155 database tests. Nothing guards the skip
count: `addopts` is `-ra --strict-markers --strict-config` with no minimum collected and no fail on
skip. A typo in the CI environment variable would skip a quarter of the suite and stay green. Today
they do all run, confirmed by `624 passed` with nothing skipped.

**4. Two published documents understate the product.** `README.md` lines 156 to 158 and
`docs/METHODOLOGY.md` line 249 still say parcel geometry is not loaded so setback compliance margin and
distance to residential are unavailable. `src/auspice/pipeline/features/builder.py` now computes both
from a PostGIS `ST_Distance` on a bi-temporal nearest residential parcel query, with twelve tests in
`tests/unit/test_parcel_features.py`. The absent rather than zero behaviour is still correct; the stated
reason is false. The same README bullet's claim about board composition needing per member vote records
is also stale, since `builder.py` computes `board_composition_score` and `graph/labels.py` parses and
cross checks `member_votes`. For a project whose rule is that the published claim and the enforced one
must not come apart, this is a defect rather than a typo.

**5. Coverage is 49 percent, not the 51 the pull request claimed.** Measured in CI:
`TOTAL 7899 3762 1852 128 49%`. Worse, three modules are at zero percent under pytest while being what
loads all twelve jurisdictions, 109 elections and twelve boundaries:
`src/auspice/pipeline/registry/loader.py`, `boundaries.py` and `probe.py`. `score/engine.py` is at 27
percent and `models/eval/killtest.py` at 24 percent. There is no `fail_under` gate.

**6. About twenty assertions test source text rather than behaviour.** The two that matter:
`tests/unit/test_models_recover_truth.py` lines 212 to 214 asserts a substring of
`inspect.getsource(killtest._fit_calibrator)` under the message that the calibrator must be fitted from
the training set only, which is the leakage guard behind the published calibration claim; a renamed
leaking variable keeps it green. `tests/unit/test_observability.py` lines 292 to 296 asserts
`"compare_digest" in source` as a constant time comparison security check, which proves the string
appears somewhere in the file and not that it guards the metrics token.

**7. `tests/unit/test_models_recover_truth.py` line 221 cannot fail.**
`assert binned_interval_coverage(...) >= 0.0`, and that function returns a value in zero to one or nan.
It works only as a nan check, and its name claims it checks the bootstrap interval label.

**8. Documentation and comment drift, small but real.** `README.md` says eight pages and there are
eleven `page.tsx` files, with `/privacy` and `/terms` in neither the count nor the table.
`apps/web/playwright.config.ts` lines 4 and 7 say visual regression covers the accuracy page and the
report and that the report is the product; the report screen has no baseline at all, and the coverage
table which does have one is unmentioned. `ci.yml` in the writing job says full history and then sets
`fetch-depth: 1`, which is the shallow checkout; this one is pre-existing, present in the version before
the repair, and the gate still works because `git cat-file blob HEAD:path` resolves at depth 1.

**9. The visual job holds `permissions: contents: write` on every path**, including pull request runs,
although only the dispatch gated commit step uses it. Narrowing it would be the tighter configuration.

**10. `tools/check_writing.py` does not scan `.agent/`, `.github/`, `.kiro/` or `packages/`,** and its
`docs/*.md` glob is not recursive so documentation subdirectories are missed.
`tools/check_line_endings.py` has no such gap because it reads every tracked file through
`git ls-files`. Both were run locally: 187 files pass the writing rules, 261 tracked text blobs are all
stored LF. The `AUDIT_REPORT.md` exclusion is recorded as assumption A-007; the `.agent/` exclusion is
documented nowhere.

Checked and found sound, so do not re-litigate these: all three web gates can genuinely fail and the
audit allowlist in `scripts/check-audit.mjs` is empty; the `tests/synthetic` isolation is really
enforced; there are no vacuous self comparisons, no `assert True`, no empty test bodies and no
mock-configured-then-asserted tests anywhere in the suite; Playwright has zero `.skip`, `.only` or
`.fixme` and `forbidOnly` is on in CI.

## What is actually left on the project

**The corpus, and nothing else comes close.** One labelled terminal decision against the 400 the kill
test needs. In a fresh CI database the sufficiency report prints `0 decided applications held, 400
needed` because no features have been built, and the dataset loads zero rows. Until that changes the
kill test has no verdict, every site abstains, and every calibration statement is a claim about method
rather than a measured result. `D-005` in `.agent/DEFERRED.md` is blunt that this is the binding
constraint on the business rather than on the software.

**Blocked on you, cannot be done from a session:**

1. Revoke the exposed personal access token at github.com/settings/tokens. It never entered a commit,
   verified across 560 blobs on every ref, but it sat in a working tree and was printed into a
   transcript. Treat it as compromised. This is `D-004`, rated CRITICAL.
2. Supply a language model key, or accept hand labelling as the only route to the corpus. `D-003`,
   HIGH. Extraction accuracy is the largest unmeasured quantity in the product and is one key away
   from being measurable.
3. Build the container stack. `D-001`, MEDIUM. Twenty one static checks pass by parsing, but nothing
   proves the image builds, that Chromium runs, or that uvicorn starts. Docker is not installed here.
4. Settle the Linn County adoption date, `B-005`. The row cites a source describing a different event
   and it was deliberately not guessed.
5. Trademark clearance on Permission Bureau. `ADR-001` carries an unresolved dissent.

**Deferred engineering, parked with impact ratings in `.agent/DEFERRED.md`:** `D-006` portfolio
screening as an asynchronous job, MEDIUM, currently one synchronous request holding a single database
snapshot for its whole duration; `D-007` the rule change watch surface, MEDIUM, machinery works and the
endpoint and page are missing; `D-008` evidence drawer analytics, LOW, needs a data retention decision
first.

## Rules this work followed, worth keeping

Do not weaken a test to make CI green. Do not regenerate a visual baseline without first proving from
the data what the page should render. Do not modify `thresholds.py`. Do not claim complete coverage.
Record a withdrawn finding rather than deleting it, because an audit that removes its own mistakes
cannot be checked.
