# Audit report and project memory

Append only. Entries carry an ISO date. Nothing in this file is rewritten or deleted; a finding that
changes status gains a new dated line rather than losing its old one. Section anchors are stable so
commit messages and code comments can link to them without rotting.

Started 2026-08-30. Repository `C:\Dev\apps\auspice`. Baseline commit `2d8efdf`.

## Contents

- [Current state](#current-state)
- [Findings register](#findings-register)
- [Decisions log](#decisions-log)
- [Verification log](#verification-log)
- [Domain and trademark record](#domain-and-trademark-record)
- [Open gaps](#open-gaps)

---

## Current state

As measured on 2026-08-30, not as described by any document.

| Measure | Value | How it was measured |
|---|---|---|
| Python source | 22,858 lines | line count over `src`, `apps/api`, `tests`, `tools` |
| TypeScript source | 6,577 lines | line count over `apps/web/src`, `packages/shared-types/src` |
| Labelled terminal decisions | **1** | `data/labels/decisions.yaml`, one entry, outcome `approved` |
| Distinct outcome classes | **1** | same file |
| Kill test floor | 400 decisions, 60 held out, 6 jurisdictions with depth 5 | `src/auspice/models/eval/thresholds.py` |
| Jurisdictions in registry | 12 | `data/registry/jurisdictions.yaml` |
| Alembic migrations | 3 | `infra/migrations/versions` |
| Ledger entries published | 0 | README and the no record path in `ledger.public_record` |
| Language model key configured | no | `config.py` defaults `llm_provider` to `none` |
| Deployment artifacts | 0 | repository wide glob for Dockerfile, tf, fly.toml, Procfile, Caddyfile, nginx |
| Raw corpus | 80 files, 7.62 MB | `data/raw`, content addressed |

The ratio of mechanism to data is roughly 29,400 lines per label. Every model path, the kill test, and
every score therefore terminate in `INSUFFICIENT DATA` or `abstained`. The README states this plainly,
which is to its credit, and it is also the central problem.

The binding constraint on the business is labelled decisions, not engineering. Capital, compute and
engineering capacity are all non binding. Legal and brand constraints bind on the first sale, not on the
next label.

### What is strong and should not be changed without a recorded decision

- The ledger tail deletion detector in `ledger/chain.py::verify`, which compares the sequence
  generator's `last_value` against the highest row present. Tail truncation is the deletion someone
  would actually perform, and most implementations miss it entirely.
- The quote verifier in `pipeline/extract/verify.py`. Exact substring match after whitespace
  normalisation only, ellipsis bounded to 400 characters, fragments forbidden from crossing a page. The
  comment records the actual forgery probe that motivated the bound.
- `MIN_OUTCOME_CLASSES = 2` in `thresholds.py`, added after the scorer published a 100 percent approval
  probability from a single row because the prior it shrank toward was itself 1.0 and the pooling weight
  landed on exactly 0.8, which is not greater than 0.8.
- `/v1/public/methodology` serving from the same constants the code enforces, so the published claim and
  the enforced rule cannot diverge.
- Point in time feature construction, with a test that inserts later decisions and a later moratorium
  and asserts nothing moved.
- No SQL string interpolation anywhere. Every parameter is bound, including the PostGIS tile query.
- No cross site scripting surface. Markdown parses to typed nodes rendered through primitives, with no
  `dangerouslySetInnerHTML`.

---

## Findings register

Status values: OPEN, IN PROGRESS, CLOSED, PARKED, OPERATOR.

| ID | Severity | Finding | Location | Status | Dated |
|---|---|---|---|---|---|
| SEC-01 | CRITICAL | Live GitHub personal access token in plain text in a git working tree, untracked and not ignored. Would have entered history permanently on the first checkpoint commit. | `.kiro/settings/mcp.json` | PARTIAL. Git path closed 2026-08-30, verified by pickaxe across all refs. Revocation is OPERATOR. | 2026-08-30 |
| ENV-01 | HIGH | `node_modules/@auspice` workspace junctions pointed at `C:\auspice`, which does not exist. The tree was moved and `node_modules` was never reinstalled, so `tsc` could not resolve `@auspice/shared-types` and four typecheck errors were downstream of that one unresolved module. | `node_modules`, environment | CLOSED 2026-08-30 by `npm install`. Not a code defect. | 2026-08-30 |
| P0-1 | CRITICAL | `Dockerfile.api` referenced by compose but absent. Zero deployment artifacts repository wide, so `docker compose up` fails immediately and nothing can be deployed. | `infra/docker-compose.yml` | CLOSED 2026-08-30. `infra/Dockerfile.api` written, plus `.dockerignore` (context 4000 MB to 7.8 MB) and a Caddy TLS proxy. Build not executed: docker absent, D-001. | 2026-08-30 |
| P0-2 | CRITICAL | The portfolio page sends no API key and there is no server side proxy route, so the wedge feature returns 401 outside development. | `apps/web/src/lib/api.ts:385,469`; `src/app/portfolio/page.tsx` | CLOSED 2026-08-30. Route handler at `src/app/api/portfolio/route.ts` holds the key server side. Sentinel key verified absent from all client output. | 2026-08-30 |
| P0-3 | HIGH | Production compose sets `AUSPICE_ENV: production` without `AUSPICE_API_CORS_ORIGINS`, so CORS defaults to localhost and a deployed web origin is refused. | `infra/docker-compose.yml`, `config.py` | CLOSED 2026-08-30. Compose now fails fast on unset `AUSPICE_API_CORS_ORIGINS` instead of inheriting the localhost default. | 2026-08-30 |
| P0-4 | HIGH | `memo/generator.py` instructs `uv sync --extra memo` and no `memo` extra exists, so the priced PDF deliverable cannot be produced. | `memo/generator.py:141`, `pyproject.toml` | CLOSED 2026-08-30. `memo` extra defined, `uv.lock` regenerated, degradation path verified to still raise StageUnavailableError. | 2026-08-30 |
| P1-1 | HIGH | `healthz` initialises `database = True` and never sets it false, so a database outage cannot be reported as degraded. The `Db` dependency also acquires the connection before the handler runs, so a hard outage surfaces as a 500 rather than the degraded body. | `apps/api/app/main.py` | CLOSED 2026-08-31. Three defects, one of them introduced by fixing another and caught by the test. Tests proved to fail against the original handler. | 2026-08-31 |
| P1-2 | HIGH | Every route is `async def` while all database, polars, XGBoost and NumPyro work is synchronous, so blocking work runs on the event loop. Combined with the single worker requirement of the in process rate limiter, effective concurrency is about one. | all routers | CLOSED 2026-08-31. Twelve handlers converted, one await removed. Route table guard, proved by reverting a handler. | 2026-08-31 |
| P1-3 | HIGH | `/healthz` is rate limit exempt and calls `ledger.verify()`, which is O(entries) and rehashes every payload. `/v1/public/accuracy` and `/v1/public/ledger` are unpaginated and uncached. The moat and the denial of service surface grow at the same rate. | `ratelimit.py`, `ledger/chain.py`, `routers/public.py` | CLOSED 2026-08-31 in three parts: constant cost verify_head for healthz, digest keyed verification cache for the accuracy page, streamed export with ETags. | 2026-08-31 |
| P1-4 | MEDIUM | Read scoring performs savepoint writes and the count per request is uncapped. A 500 site portfolio opens 500 savepoints in one transaction, 13 per site when alternatives are enabled. The design is correct and the consequence is undocumented. | `score/engine.py` | CLOSED 2026-08-31, but not by capping. The savepoint is removed: `features.build_for_spec` takes an `ApplicationSpec` and the scoring path builds one in memory, so prospective scoring performs no write at all. A cap would have had to be at least 500 to leave the documented portfolio size working, so it could never have fired. See ADR-002 and `tests/unit/test_features_spec_equivalence.py`. | 2026-08-31 |
| P1-5 | HIGH | The Playwright suite is absent from CI entirely, so neither the unit tests nor the visual suite run automatically. The middleware comment records two CSP bugs that passed lint, types and build and were caught only by that suite. | `.github/workflows/ci.yml` | CLOSED 2026-08-30. Unit project wired into the web job; new `visual` job on windows-latest. | 2026-08-30 |
| P1-6 | **WITHDRAWN** | Claimed "no JavaScript test framework exists" and "these two files have no direct coverage". **This was false.** `apps/web/tests/unit/published-doc.spec.ts` and `site-list.spec.ts` already existed, 242 lines, running in the `unit` project of `playwright.config.ts`, covering both files including the docs parse guard and the refusal to fuzzy match a county. | `apps/web/tests/unit/` | WITHDRAWN 2026-08-30. See [Corrections](#corrections). Superseded by P1-5. | 2026-08-30 |
| P1-8 | MEDIUM | Visual baselines are recorded as `-win32.png` only. Playwright suffixes snapshot filenames with the platform, so the suite cannot pass on a Linux runner: it looks for `-linux.png`, finds nothing, and reports a missing snapshot, which reads as a regression and is not one. | `apps/web/tests/visual/design-system.spec.ts-snapshots/` | MITIGATED 2026-08-30 by running the visual job on windows-latest, where the baselines were made. Not fixed: the suite is still single platform. | 2026-08-30 |
| NEW-01 | **HIGH** | Endpoint tests read `AUSPICE_DATABASE_URL`, not the test database, because `app.deps.get_connection` uses the non test engine. Locally the two URLs name different databases; in CI they name the same one, so the fault is invisible there. Measured: `auspice` held 12 jurisdictions, 1 application and 2 ledger entries; `auspice_test` held none. `test_tiles.py` asserted a real tile for northern Virginia against boundaries no test created, and could not have passed in CI. | `tests/conftest.py`, `tests/unit/test_tiles.py`, `apps/api/app/deps.py` | CLOSED 2026-08-31. Tile tests seed their own geography; shared `api_client` fixture; autouse guard raises if the override is forgotten. Not in the original audit. | 2026-08-31 |
| P1-7 | LOW | `slowapi` is declared in the `api` extra and in the mypy overrides while `ratelimit.py` implements its own token bucket. | `pyproject.toml` | CLOSED 2026-08-31. Removed from the extra and the overrides. Dropped three transitive packages with it. | 2026-08-31 |
| NEW-02 | **HIGH** | A citation on the Newton County row carried the wrong quote entirely: the text stored against the county's official Resolution R-040726b was the headline of the WSB-TV news article cited beside it. The official record was also typed `secondary`. So the row's strongest evidence, a primary source, was both unverifiable and understated as secondary. | `data/labels/decisions.yaml`, `newton-data-center-moratorium-2026` | CLOSED 2026-08-31. Quote replaced with a verbatim span located by `auspice labels quote`, "SO RESOLVED this 7th day of April, 2026, ...", page 2, and the citation retyped `primary`. `auspice labels verify` now reports it verified on page 2 where it previously reported quote not found. This is the class of defect the labelling console exists to prevent. | 2026-08-31 |
| NEW-03 | **HIGH** | The Linn County row records `adopted_on: 2026-04-08` and `effective_on: 2026-04-08`, and its primary citation points at a county newsflash that describes a different event. That page is posted 1 July 2026, states the board "has approved an 18-month moratorium", says it "takes effect immediately", and refers to the February 2026 ordinance as a separate earlier action. It says nothing about 8 April. The date 8 April 2026 does appear verbatim in the Newton County resolution cited two rows above, as the expiry of Newton's earlier emergency moratorium, which is a plausible route for the value to have crossed rows during labelling. | `data/labels/decisions.yaml`, `linn-data-center-moratorium-2026` | **OPEN, and deliberately left open.** The quote was not repaired. Repairing it would verify the citation and admit the row to training with a date the source does not support, which is worse than an unverified row, because unverified rows are excluded by the training query and verified ones are not. Correcting a labelled fact is the operator's call under the no fabricated labels rule. See B-005. | 2026-08-31 |
| NEW-04 | **WITHDRAWN and replaced** | Claimed two cited sources cannot be verified because they render client side, on the strength of measuring how little text their fetches produced. **Both halves were wrong.** Rendering each in a real browser settled it. wsbtv.com is not client rendered: it answers HTTP 451 with "This website is unavailable in your location" and "It appears you are attempting to access this website from a country outside of the United States". cbs2iowa.com renders to 7658 characters of real article text and its plain fetch already produced 7636; it was verifying before this work and never needed rendering, and the 7636 figure quoted in the original finding came from a fetch that had succeeded. | `pipeline/extract/verify.py` | WITHDRAWN 2026-08-31. See [Corrections](#corrections). Superseded by NEW-05 and NEW-06. | 2026-08-31 |
| NEW-05 | MEDIUM | The WSB-TV citation on the Newton County row cannot be verified from outside the United States. The publisher answers HTTP 451 by geography, so no transcription of any quote from it can ever be located from this host, and no code change alters that. | `data/labels/decisions.yaml`, `newton-data-center-moratorium-2026` | OPEN, and not blocking. That row now carries a verified primary citation to the county's own resolution, so it counts toward training regardless. The remedies are a US egress for the fetcher or replacing the citation with an accessible source, and both are operator decisions. | 2026-08-31 |
| NEW-06 | LOW | `parse/cascade.py` and `adapters/platforms.py` both refer to "the Playwright path" for pages that need JavaScript, as though it existed. It did not. | `pipeline/parse/cascade.py`, `pipeline/adapters/platforms.py` | CLOSED 2026-08-31. `pipeline/ingest/render.py` is that path, with 19 tests. It is what produced the diagnosis that withdrew NEW-04, and it is needed for the corpus backfill, where civic platforms serve search results through JavaScript. Not wired into citation verification, because no citation currently needs it. | 2026-08-31 |
| P2-1 | MEDIUM | Models are fitted at startup inside `lifespan`, including MCMC. The artefact loading seam is named in a docstring and not implemented. | `apps/api/app/deps.py` | **ASSESSED, deliberately not built, 2026-08-31.** Measured against the live corpus: `load_serving_models` takes 3 to 9 milliseconds and fits no classifier at all, because the hierarchical model needs 40 training rows and the graph has 1. A cache would add a pickle deserialisation surface and a staleness risk to the one system whose value is provenance, to save three milliseconds. The lifespan now logs `fit_seconds` on every start, so the decision is revisited when the number says to rather than on principle. Revisit at 40 training rows, when MCMC actually runs. | 2026-08-31 |
| NEW-07 | MEDIUM | `auspice labels load` truncates and re-inserts applications, which assigns new ids and orphans every `feature_snapshot`. The dataset excludes any application without a snapshot at the current feature set version, so after a label load the corpus is invisible to every model until `auspice features build` runs again. Measured 2026-08-31: `auspice labels stats` reported 1 terminal decision and `load_serving_models` reported 0 decided rows and the note "1 row(s) excluded: no feature snapshot at version 1.0.0". Nothing failed, and the accuracy of every downstream statement was wrong. | `cli/labels_cmd.py`, `pipeline/graph/labels.py` | CLOSED 2026-08-31. `labels load` now counts applications with no snapshot at the current version and names the command that fixes it. Not fixed by having the load build features itself: that would make a corpus command do model work, and `features build` prints per feature coverage an operator needs to read. | 2026-08-31 |
| P2-2 | MEDIUM | `monitor/watcher.py` writes rows to an `alert` table and nothing delivers them, so the monitoring line the specification calls the reason revenue recurs has no channel. | `monitor/watcher.py` | OPEN | 2026-08-30 |
| P2-3 | MEDIUM | No error tracking, no uptime metrics, no automated or tested backups. All three are specified and none exists. | absent | OPEN | 2026-08-30 |
| P2-4 | MEDIUM | Portfolio screening is a synchronous POST of up to 500 sites behind a 0.5 per second limit, with no progress and no partial results. | `routers/score.py` | OPEN | 2026-08-30 |

---

## Corrections

Findings that turned out to be wrong. Kept rather than deleted, because an audit that quietly removes its
mistakes cannot be checked.

### 2026-08-31: NEW-04 was wrong on both counts

**Claimed:** two cited sources cannot be verified because they render client side. WSB-TV parses to 219
characters of app furniture and CBS2 Iowa to 7636 of the same, so no quote can be located in either, and
citation verification should route them through a browser.

**Actually:** rendering both in a real browser settled it, and neither half held.

WSB-TV is not client rendered. It answers HTTP 451, and the rendered page reads "This website is
unavailable in your location", "Error 451", and "It appears you are attempting to access this website from
a country outside of the United States". A renderer cannot fix a geographic block. Recorded as NEW-05.

CBS2 Iowa renders to 7658 characters of real article text, and its plain fetch already produced 7636. It
was verifying before this work and never needed rendering at all. The 7636 figure quoted in the finding
came from a fetch that had succeeded, which was visible in the same `auspice labels verify` output that
listed the failures: cbs2iowa appeared there twice, marked verified.

**How the error happened:** the claim was inferred from one measurement, the character count of the
extracted text, without asking why it was low. Two different causes produce a thin parse, a geographic
block and a client rendered page, and only one of them is a rendering problem. The available evidence
distinguishing them, the HTTP status and the verify output, was already on screen and was not read.

**What was kept:** `pipeline/ingest/render.py`, because it produced the diagnosis and because
`parse/cascade.py` and `adapters/platforms.py` both already referred to a Playwright path that did not
exist. That gap is real and is now closed, recorded as NEW-06. It is deliberately not wired into citation
verification, since no citation needs it.

### 2026-08-30: P1-6 was false

**Claimed:** apps/web has no JavaScript test framework and no unit coverage of `site-list.ts` or
`published-doc.ts`.

**Actually:** `apps/web/tests/unit/` already held `published-doc.spec.ts` and `site-list.spec.ts`, 242
lines between them, running in the `unit` project declared in `playwright.config.ts`. They covered both
files, including the refusal to fuzzy match a county name and a guard that every published document
parses. One of their assertions is stronger than anything in the replacement that was briefly written:
`no sentence is dropped` harvests every word from all five documents and asserts the parser kept them all.

**How the error happened:** the claim was asserted from a grep for `vitest` and `jest` across the
repository plus a read of the CI workflow. `apps/web/tests` appeared in an early directory listing and
was never opened. A negative claim about test coverage requires a directory listing, not a dependency
grep. The lesson is general: absence of a tool is not absence of the thing the tool provides.

**What it cost:** one commit, `e39f8cf`, added Vitest and 60 duplicate tests, overruling an explicit
decision recorded in `playwright.config.ts`: "Kept in this runner rather than a second test framework,
because the code under test is TypeScript the web app imports and one runner is enough." Reverted in
`e5b0559`. The 14 cases that were genuinely new were ported into the existing specs instead, taking the
unit project from 21 tests to 35.

**What survived:** the real defect was narrower than claimed and is now closed. The tests existed and
never ran, because CI never invoked Playwright. That was P1-5.

---


### 2026-08-31: the ledger was reported as empty and is not

**Claimed:** Ledger entries published: 0.

**Actually:** `uv run auspice ledger status` reports 2 predictions published, 2 still pending, chain
intact. The accuracy record is empty because nothing has resolved, which is a different statement.

**How the error happened:** taken from the README's "what this does not do yet" section and from the
no-record branch in `public_record`, rather than from a query. A claim about the state of the data has to
come from the data.

**What it changes:** Task 17 is not starting from zero. The moat has begun accruing, which moves the
argument for scheduled publishing from "start the clock" to "keep it running".

---

## Decisions log

Full text with rationale, rejected alternatives and dissents is in `.agent/DECISIONS.md`. Summarised
here so this file stands alone.

| ID | Date | Decision | Reversibility |
|---|---|---|---|
| ADR-001 | 2026-08-30 | Brand becomes Permission Bureau. Primary `permissionbureau.com`, category asset `permissionrisk.com`. Rejected `entitlementbureau.com` for being US only vocabulary and `assaybureau.com` for reading as laboratory work. Dissent recorded and unresolved: a descriptive name is weaker than an ownable abstract mark for a business intending to become a standard. | easy at this stage |
| D-DEV-01 | 2026-08-30 | The baseline snapshot commit goes on the agent branch, not on `main`, because IRONCLAD section 1.3 and the run's prohibition on committing to `main` conflict. `checkpoint/000-baseline` tags `main` at `2d8efdf` with no commit there. | strictly safer, nothing to reverse |
| D-DEV-02 | 2026-08-30 | Edits to existing files must preserve that file's line endings. The agent's writer emits CRLF; the repository is predominantly LF with `pyproject.toml` as the CRLF exception. | easy |

---

## Verification log

| Date | Layer | Command | Result |
|---|---|---|---|
| 2026-08-30 18:31 | L1a | `uv run ruff check .` | PASS |
| 2026-08-30 18:31 | L1b | `uv run ruff format --check .` | PASS, 117 files already formatted |
| 2026-08-30 18:33 | L2 | `uv run python -m mypy` | PASS, no issues in 102 source files |
| 2026-08-30 18:35 | L3 | `uv run python -m pytest -q` | PASS, 309 passed, 0 skipped, 128.40s |
| 2026-08-30 19:31 | L4 | `alembic check` | PASS, "No new upgrade operations detected", corroborated by `test_no_pending_migration` |
| 2026-08-30 19:26 | L6a | `eslint .` | PASS |
| 2026-08-30 19:26 | L6b | `tsc --noEmit` | **RED**, 4 errors, all downstream of ENV-01 |
| 2026-08-30 19:28 | L6b | `tsc --noEmit` after `npm install` | PASS, both workspaces |
| 2026-08-30 19:26 | L6c | `check-tokens.mjs` | PASS, 77 tokens defined, 33 files checked |
| 2026-08-30 19:29 | L7a | `next build` | PASS, 12 routes, 103 kB shared first load |
| 2026-08-30 19:29 | L7b | `check-budget.mjs` | PASS, within budget on all 12 routes |
| 2026-08-30 19:27 | L10 | `check-types-current.mjs` | PASS, document and generated types current |
| 2026-08-30 18:31 | L11 | `check_writing.py` | PASS, 158 files checked |
| 2026-08-30 19:29 | audit | `check-audit.mjs` | PASS, 2 advisories, both assessed, review by 2026-11-01 |
| 2026-08-30 19:40 | SEC-01 | `git log --all -S <token>` and `git log --all -- .kiro/settings/mcp.json` | PASS, no commit on any ref contains the token or the file |

Two tooling facts worth not rediscovering. `uv run mypy` fails with a trampoline error after `uv run
ruff` reinstalls the local package; `uv run python -m mypy` works, and the same applies to `alembic` and
the `auspice` CLI. `alembic check` reports no drift and still exits non zero in PowerShell.

---

## Domain and trademark record

Verified 2026-08-30. Method matters here: `rdap.org` returned 404, meaning available, for
`auspice.io`, `auspice.co`, `auspice.us` and `auspice.eu`, all four of which are registered and DNS
delegated. It also returned 404 for a deliberately fake TLD. **A single RDAP proxy is not a safe
availability check.** Only results confirmed by the authoritative registry plus DNS are recorded below.

### Registered, not available

| Domain | Evidence |
|---|---|
| `auspice.com` | Verisign RDAP 200. Nameservers `ns1/ns2.markmonitor.com`, which is corporate brand protection rather than a reseller. Acquisition unlikely. |
| `auspice.io` | Identity Digital RDAP 200. Nameservers `ns5/ns6.afternic.com`, meaning it is listed for sale on the aftermarket. |
| `auspice.ai` | Registered, no A or NS records. Held and undelegated. |
| `.net .org .dev .app .xyz .tech .co .us .eu .co.uk` | all registered |

### Verified available, two methods agreeing

| Domain | Verisign or Identity Digital RDAP | DNS delegation |
|---|---|---|
| `permissionbureau.com` | AVAILABLE | none |
| `permissionrisk.com` | AVAILABLE | none |
| `permissionbureau.net` `.org` `.io` | AVAILABLE | none |
| `permissionrisk.net` `.org` `.io` | AVAILABLE | none |
| `entitlementbureau.com` | AVAILABLE | none |
| `assaybureau.com` | AVAILABLE | none |
| `permissionrating.com` `permissiongrade.com` `permissionoffice.com` | AVAILABLE | none |
| `permitgrade.com` `quorumgrade.com` `abstentia.com` | AVAILABLE | none |
| `auspice.build` `.land` `.credit` `.report` `.institute` `.capital` and 13 more gTLDs | AVAILABLE | none |
| `rightto.build` `permission.build` `entitlement.build` | AVAILABLE | none |

`permissionbureau.com` and `permissionrisk.com` were each confirmed by five methods: Verisign
authoritative RDAP, rdap.org, DNS NS, DNS A and SOA, and a live HTTP probe. All five agree.

`auspice.ratings` is **not** available and not a domain: `.ratings` is not a delegated TLD. It appeared
available only because the RDAP proxy false positives on non existent TLDs.

Roughly 490 candidate names were screened across six generation strategies: Roman augury vocabulary,
Roman land surveying vocabulary, the bird genera augurs watched, assent and permission Latin,
attestation and evidence semantics, and constructed marks. There is no strong single word `.com`
available in this space. `groma`, `milvus`, `quorate`, `decisis`, `limes`, `sententia`, `probitas`,
`regula` and `templum` are all registered.

### Trademark

Auspice Capital Advisors Ltd., Calgary, founded 2006, describes itself as Canada's largest active
commodity and CTA fund manager with retail and institutional products in Canada and the US, and a
distribution partnership with CI Global Asset Management. It uses AUSPICE as a house mark across at
least three named products. A permission rating bureau selling opinions to credit committees is Nice
class 36, the same class.

One search for "Permission Bureau" as a company or mark returned nothing in this space. That is a
signal, not a clearance opinion.

---

## Open gaps

| ID | Gap | Impact | Why unresolved | How it constrains conclusions |
|---|---|---|---|---|
| G-001 | Extraction accuracy has never been measured | HIGH | No language model key. Stage 4 refuses rather than inventing facts. | The largest unmeasured quantity in the product. One key away from being knowable. |
| G-002 | Whether the model has signal | FATAL if absent | 1 label of 400. Unknowable from this repository. | Every claim about calibration in `docs/METHODOLOGY.md` is a claim about method, not a measured result. |
| G-003 | Container stack and PDF memo never observed working | MEDIUM | docker absent on this machine | The artifacts can be written and reviewed but not demonstrated. |
| G-004 | Visual suite never executed locally | MEDIUM | operator instructed no servers | Wiring it into CI resolves it durably. |
| G-005 | Exposed token not revoked | CRITICAL | only the owner can revoke | The git path is closed; the credential is still live. |
| G-006 | Domains not registered | LOW | operator action | The rename is independent of who owns the name. |
| G-007 | No errors and omissions cover, no reviewed terms of service | HIGH before first sale | outside software | Specification section 15.1 calls it non negotiable. |
| G-008 | No trademark clearance opinion | HIGH before brand spend | needs a lawyer | One negative search is not clearance. |
