# Assumptions

Each one is a choice made without asking. Each carries the cost of reversing it.

```
A-001: No language model key is available, so extraction accuracy stays unmeasured.
       Evidence: config.py defaults llm_provider to "none"; AUSPICE_LLM_API_KEY is empty.
       Reverse by: set AUSPICE_LLM_API_KEY and AUSPICE_LLM_PROVIDER, then run stage 4 against
       tests/golden/documents. About 30 minutes, no code change. Parked as D-003.
```

```
A-002: The code namespace rename is deferred behind the brand rename.
       Reason: changing env_prefix from AUSPICE_ to PERMBUREAU_ makes a missed variable fall back
       to a Settings default silently rather than failing, which is the hardest class of failure to
       notice in this codebase. The brand rename delivers the user visible value at near zero risk.
       Reverse by: running plan Task 13. About 3 to 4 days, touches every file.
```

```
A-003: permissionbureau.com is not yet registered by the operator.
       The rename proceeds regardless, because the code and copy change is independent of who owns
       the domain, and holding the work hostage to a registration would stall the run.
       Reverse by: nothing to reverse. If the operator picks a different name, the rename is a
       find and replace over the same set of files, about 2 hours.
```

```
A-004: .co and .ai availability is unverified and is not claimed anywhere.
       Reason: rdap.org was proven to return 404 for registered ccTLD domains during this run. It
       reported auspice.io, auspice.co, auspice.us and auspice.eu as available; the authoritative
       registry and DNS delegation both show all four registered. Only gTLD results are trusted.
       Reverse by: query the ccTLD registry directly, or check at a registrar. 10 minutes.
```

```
A-005: PostgreSQL running on 55432 is the operator's cluster and the agent must not stop, start or
       reconfigure it. The initial probe reported the port closed, then the test suite connected
       successfully, so it came up between the two observations.
       Consequence: database tests run for real. The agent takes no logical dump, because pg_dump
       against a cluster it does not control is a read the operator did not ask for.
       Reverse by: the operator runs pg_dump if they want a logical backup beside the bundle.
```

```
A-006: The dangling node_modules junctions were repaired with npm install.
       This modified only node_modules, which is gitignored, so it changed nothing tracked. It was
       necessary because tsc could not resolve @auspice/shared-types and four typecheck errors were
       downstream of that single unresolved module.
       Reverse by: nothing. Deleting node_modules and running npm ci reaches the same state.
```

```
A-007: AUDIT_REPORT.md lives at the repository root and is therefore outside the INCLUDE_GLOBS of
       tools/check_writing.py, so the writing rules do not scan it.
       The file still follows those rules, because a report that breaks the project's own prose
       standard is a report nobody trusts. This is a choice, not an exemption being exploited.
       Reverse by: add "AUDIT_REPORT.md" to INCLUDE_GLOBS in tools/check_writing.py. One line.
```

A-015: Left app.deps.get_connection opening a writable transaction after ADR-002 removed the write
       from the scoring path. A read only connection, and later a hot standby for scoring, are now
       possible and were deliberately not done in the same checkpoint, so a rollback can separate the
       two behaviours.
       Reverse by: nothing to reverse. To go further, change 	ransaction() to a read only variant in
       get_connection and add a test that a write through it fails. About 20 lines, 30 min.

A-016: Deferred plan Task 12, the brand rename, to the end of the run rather than doing it in plan
       order. It is pure copy, it depends on a trademark clearance opinion the operator does not yet
       have (B-004), and ADR-001's own reversal trigger contemplates the name changing. Doing it after
       every feature exists is one pass over final copy instead of two, and if the clearance opinion
       rejects Permission Bureau only one pass is redone.
       Reverse by: do it now instead. The surface is small and measured: 4 strings in
       apps/web/src/app/layout.tsx, 4 in published-page.tsx, 1 message in the report page, prose
       in 5 docs files, the README, and 6 brand SVG files. Environment variable and package names are
       Task 13, not Task 12.