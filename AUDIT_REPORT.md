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
| P0-1 | CRITICAL | `Dockerfile.api` referenced by compose but absent. Zero deployment artifacts repository wide, so `docker compose up` fails immediately and nothing can be deployed. | `infra/docker-compose.yml` | OPEN | 2026-08-30 |
| P0-2 | CRITICAL | The portfolio page sends no API key and there is no server side proxy route, so the wedge feature returns 401 outside development. | `apps/web/src/lib/api.ts:385,469`; `src/app/portfolio/page.tsx` | OPEN | 2026-08-30 |
| P0-3 | HIGH | Production compose sets `AUSPICE_ENV: production` without `AUSPICE_API_CORS_ORIGINS`, so CORS defaults to localhost and a deployed web origin is refused. | `infra/docker-compose.yml`, `config.py` | OPEN | 2026-08-30 |
| P0-4 | HIGH | `memo/generator.py` instructs `uv sync --extra memo` and no `memo` extra exists, so the priced PDF deliverable cannot be produced. | `memo/generator.py:141`, `pyproject.toml` | OPEN | 2026-08-30 |
| P1-1 | HIGH | `healthz` initialises `database = True` and never sets it false, so a database outage cannot be reported as degraded. The `Db` dependency also acquires the connection before the handler runs, so a hard outage surfaces as a 500 rather than the degraded body. | `apps/api/app/main.py` | OPEN | 2026-08-30 |
| P1-2 | HIGH | Every route is `async def` while all database, polars, XGBoost and NumPyro work is synchronous, so blocking work runs on the event loop. Combined with the single worker requirement of the in process rate limiter, effective concurrency is about one. | all routers | OPEN | 2026-08-30 |
| P1-3 | HIGH | `/healthz` is rate limit exempt and calls `ledger.verify()`, which is O(entries) and rehashes every payload. `/v1/public/accuracy` and `/v1/public/ledger` are unpaginated and uncached. The moat and the denial of service surface grow at the same rate. | `ratelimit.py`, `ledger/chain.py`, `routers/public.py` | OPEN | 2026-08-30 |
| P1-4 | MEDIUM | Read scoring performs savepoint writes and the count per request is uncapped. A 500 site portfolio opens 500 savepoints in one transaction, 13 per site when alternatives are enabled. The design is correct and the consequence is undocumented. | `score/engine.py` | OPEN | 2026-08-30 |
| P1-5 | HIGH | The Playwright visual suite is absent from CI, and the middleware comment records two CSP bugs that passed lint, types and build and were caught only by that suite. | `.github/workflows/ci.yml` | OPEN | 2026-08-30 |
| P1-6 | HIGH | No JavaScript test framework exists. `site-list.ts` and `published-doc.ts` are the two most logic dense TypeScript files and have no direct coverage. `parseDocument` throws by design on unknown markdown, so adding a blockquote to a published document breaks the production build with no earlier warning. | `apps/web` | OPEN | 2026-08-30 |
| P1-7 | LOW | `slowapi` is declared in the `api` extra and in the mypy overrides while `ratelimit.py` implements its own token bucket. | `pyproject.toml` | OPEN | 2026-08-30 |
| P2-1 | MEDIUM | Models are fitted at startup inside `lifespan`, including MCMC. The artefact loading seam is named in a docstring and not implemented. | `apps/api/app/deps.py` | OPEN | 2026-08-30 |
| P2-2 | MEDIUM | `monitor/watcher.py` writes rows to an `alert` table and nothing delivers them, so the monitoring line the specification calls the reason revenue recurs has no channel. | `monitor/watcher.py` | OPEN | 2026-08-30 |
| P2-3 | MEDIUM | No error tracking, no uptime metrics, no automated or tested backups. All three are specified and none exists. | absent | OPEN | 2026-08-30 |
| P2-4 | MEDIUM | Portfolio screening is a synchronous POST of up to 500 sites behind a 0.5 per second limit, with no progress and no partial results. | `routers/score.py` | OPEN | 2026-08-30 |

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
