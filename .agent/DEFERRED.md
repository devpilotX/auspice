# Deferred queue

Parked, not forgotten. Every CRITICAL and HIGH item gets exactly one more attempt by a different route
before the run is allowed to finish. Nothing here was silently dropped.

## Plan tasks not reached in this run

Recorded here rather than left as TODO in the plan, so the scope that was not delivered is stated with an
impact rating rather than implied by a status column.

```
D-005 | Target: Task 16, corpus backfill across the twelve counties
      | Not blocked. Not done because it is hours of polite crawling followed by hand verification of
      |   every row, and a row entered without a verbatim quote from a real fetched source is forbidden
      |   by the run's constraints and would be worse than no row.
      | What exists to do it with: `auspice labels add` and `auspice labels quote`, both built in this
      |   run and both exercised against live county sources. The console is what makes the rate in
      |   data/labels/README.md, 30 to 60 rows a day, achievable rather than aspirational.
      | Impact: CRITICAL, and it is the binding constraint on the business rather than on the software.
      |   The kill test needs 400 terminal decisions and the corpus holds 1. Nothing else in the plan
      |   changes that number.
```

```
D-006 | Target: Task 22, portfolio screening as an asynchronous job
      | Not done because it spans a schema change, two endpoints, a worker, and the web client's polling
      |   and progress states. Started and deliberately not half-finished: an async path that exists in
      |   the API and not in the interface is a feature the product cannot use, and would have been
      |   worse than the current synchronous path, which works.
      | Impact: MEDIUM. A 500 site screen is one synchronous request behind a 0.5 per second limit, with
      |   no progress and no partial results, and it holds one database snapshot for its whole duration,
      |   which prevents autovacuum from reclaiming anywhere in the cluster while it runs. ADR-002
      |   removed the writes from that path, so the remaining cost is the held snapshot and the absent
      |   progress rather than graph damage.
      | Route: create a job row always, process inline below a configurable site count and return the
      |   same response shape so the existing client keeps working, return 202 with a job reference above
      |   it, and add polling to apps/web. One site per transaction in the worker.
```

```
D-007 | Target: Task 19, rule change watch as a product surface
      | Not done. The mechanism exists and is tested: monitor/watcher.py detects rule changes and scores
      |   them for materiality, and this run added the delivery that sends them. What is missing is the
      |   customer facing surface, an endpoint and a page showing what changed where and what is next.
      | Impact: MEDIUM. The audit called this the strongest new product finding, and it is a surface on
      |   top of working machinery rather than new machinery. It sells nothing until the corpus exists,
      |   because a rule change watch over twelve counties with one labelled decision has little to say.
```

```
D-008 | Target: Task 23, artefact serving seam and evidence drawer analytics
      | The serving seam half is closed rather than deferred: see P2-1 in AUDIT_REPORT.md, assessed with
      |   a measurement and deliberately not built, with a revisit trigger of 40 training rows.
      | The analytics half is not done. Instrumenting which evidence a customer opens is a product
      |   learning tool, and it collects behavioural data, which needs a decision about what is retained
      |   and for how long before any of it is written.
      | Impact: LOW. Nothing depends on it and it has a privacy dimension that belongs to the operator.
```

## Sweep, 2026-08-31

D-001 and D-002 were both swept by their third alternative route, and D-001's sweep found a real defect.

**D-001, route (c), static validation.** `tests/unit/test_container_files.py` checks twenty one properties
of the Dockerfile, compose file, .dockerignore and Caddyfile by parsing them. The check that every extra
named in the Dockerfile exists in `pyproject.toml` immediately caught a defect this run had introduced:
the `observability` extra was added to the project and not to the image, so a container with
`AUSPICE_SENTRY_DSN` set would have logged "configured but not installed" and reported nothing. Fixed.
The residual gap is unchanged and is stated in that module's docstring: nothing here proves the image
builds, that Chromium runs, or that uvicorn starts.

**D-002, route (c), assert the invariants without a browser.** `apps/web/tests/unit/csp.spec.ts` asserts
twenty nine properties of the content security policy, including both bugs the visual suite originally
caught, as negative assertions: no `strict-dynamic` and no nonce. Web unit tests went from 43 to 72. The
residual gap is unchanged: no test here renders a page, so a layout regression still needs the visual
suite, and re-recording the baselines after the brand rename is an operator action.

**D-003 was not swept, because it has no second route.** Extraction accuracy needs a language model key.
The alternative is hand labelling, which is not a route to measuring extraction accuracy.

**D-004 was not swept.** Revoking a credential is not a local action.

```
D-001 | Target: Execution verify the container stack and the PDF memo (DONE criteria 12, 13)
      | Blocked by: docker is not installed on this machine. `docker --version` reports
      |             CommandNotFoundException. Confirmed at 17:25 during the capability probe.
      | Tried: (1) `docker --version` (2) checked for Docker Desktop on PATH
      |        (3) confirmed no compose alternative such as podman is present
      | Alt routes: (a) the operator runs `docker compose up` and reports the result
      |             (b) run uvicorn and Chromium directly on the host, without a container
      |             (c) validate the Dockerfile by static parse and hadolint only
      | Impact: MEDIUM. The artifacts can still be written correctly and reviewed. What cannot be
      |         claimed is that they were observed to work. Route (a) resolves it in one command.
      | Affects: P0-1, P0-4, DONE 12, DONE 13
```

```
D-002 | Target: Execution verify the Playwright visual suite (DONE criterion 9)
      | Blocked by: the operator instructed the agent not to start servers at 18:30. Playwright
      |             needs a running web application at PLAYWRIGHT_BASE_URL.
      | Tried: (1) read playwright.config.ts to confirm it needs a base URL
      |        (2) confirmed no webServer autostart is configured that would avoid the constraint
      |        (3) considered a static build preview, which is still a server
      | Alt routes: (a) the operator runs `npm run test:visual --workspace apps/web`
      |             (b) CI runs it once the workflow change lands, which needs no local server
      |             (c) assert the same invariants in a JS unit test where they do not need a browser
      | Impact: MEDIUM. Route (b) is the durable fix and is inside the agent's scope, so the suite
      |         will run automatically even though the agent never runs it locally.
      | Affects: P1-5, DONE 9, DONE 14, DONE 18
```

```
D-003 | Target: Measure extraction accuracy against the golden set (plan Task 15)
      | Blocked by: no language model key is configured. `llm_provider` defaults to "none" and
      |             AUSPICE_LLM_API_KEY is empty in .env.example. Stage 4 refuses to run rather
      |             than inventing facts, which is the correct behaviour.
      | Tried: (1) read config.py llm_configured property (2) read .env.example
      |        (3) confirmed the golden fixtures exist and are the intended measuring instrument
      | Alt routes: (a) the operator supplies a key and the agent runs stage 4 against
      |                 tests/golden/documents
      |             (b) hand labelling carries the corpus alone, which is slower and is the
      |                 documented fallback in data/labels/README.md
      |             (c) nothing else. There is no third route that does not fabricate data.
      | Impact: HIGH. Extraction accuracy is the largest unmeasured quantity in the product and it
      |         is one key away from being measurable. It does not block any other work.
      | Affects: plan Task 15, AUDIT_REPORT Open Gaps
```

```
D-004 | Target: Revoke the exposed GitHub personal access token
      | Blocked by: only the token's owner can revoke it. The agent must not contact the remote,
      |             and revoking a credential is not a local action.
      | Tried: (1) prevented it entering git by ignoring .kiro/settings/
      |        (2) snapshotted it outside the repo so nothing is lost
      |        (3) confirmed by `git log -S` that no commit contains it
      | Alt routes: (a) the operator revokes it at https://github.com/settings/tokens
      |             (b) no other route exists
      | Impact: CRITICAL. The token grants write access, sat in plain text inside a git working
      |         tree, and was printed into the session transcript by the agent's own scan command.
      |         It must be treated as compromised.
      | Affects: SEC-01, DONE 22
```
