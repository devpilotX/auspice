# Deferred queue

Parked, not forgotten. Every CRITICAL and HIGH item gets exactly one more attempt by a different route
before the run is allowed to finish. Nothing here was silently dropped.

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
