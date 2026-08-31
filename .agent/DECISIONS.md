# Decisions

Append only. Dissents are never deleted.

## ADR-001: Rename the brand to Permission Bureau

Date: 2026-08-30 | Trigger: trademark collision found during audit | Reversibility: easy at this stage

**Decision:** The public brand becomes Permission Bureau. Primary domain `permissionbureau.com`, with
`permissionrisk.com` registered alongside as the category asset.

**Rationale:** "Auspice" collides with Auspice Capital Advisors Ltd., a Calgary fund manager founded in
2006 that uses AUSPICE as a house mark across US distributed financial products (AUSPICE BROAD
COMMODITY, AUSPICE DIVERSIFIED TRUST, AUSPICE ONE FUND TRUST). A permission rating bureau selling
opinions to credit committees is Nice class 36, the same class. Separately `auspice.com` sits behind
MarkMonitor, which is corporate brand protection rather than a reseller, and `auspice.io` resolves to
Afternic nameservers, meaning it is listed on the aftermarket rather than available.

"Permission Bureau" uses vocabulary the project already owns. The specification's subtitle is The
Permission Risk Engine, the core asset is the Permission Graph, and the README already describes the
product as "a rating bureau for the right to build". Credit bureaus are private companies, so the
analogy carries no implication of government affiliation.

Availability was verified by five independent methods on 2026-08-30: Verisign authoritative RDAP,
rdap.org, DNS NS delegation, DNS A and SOA records, and a live HTTP probe. All five agree for both
names, and `.net`, `.org` and `.io` are open for both.

**Rejected:** `entitlementbureau.com`, because "entitlement" is US real estate vocabulary and the
specification plans UK, EU and India entry, where the terms are planning permission and approvals.
`assaybureau.com`, because the assay office is the best available metaphor for the business model, an
institution whose mark lenders came to require, but "assay" reads as laboratory work to a real estate
buyer. Roughly 490 candidates were screened across six generation strategies; no strong single word
`.com` exists in this space.

**Dissent:** Not resolved. A descriptive name is weaker than an ownable abstract mark for a business
that intends to become a standard, and rating agencies are named Moody's, Fitch and Kroll rather than
descriptively. The counter is that mandated diligence line items are named for what they cover, as with
title insurance and environmental Phase I, and that no good short mark was available.

**Reversal trigger:** If a trademark clearance opinion finds a class 36 conflict on Permission Bureau,
or if a short abstract `.com` becomes obtainable, revisit before any spend on brand assets.

**Checkpoint:** to be tagged with the Phase D rename.

## D-DEV-01: The baseline snapshot commit goes on the agent branch, not on main

Date: 2026-08-30 | Trigger: two instructions conflicted | Reversibility: easy

**Decision:** `checkpoint/000-baseline` tags `main` at `2d8efdf` without creating a commit there. The
snapshot of previously untracked work was committed as `checkpoint/001` on the agent branch instead.

**Rationale:** IRONCLAD section 1.3 commits the working tree as checkpoint 000 before branching, which
would place a commit on `main`. The run's hard prohibitions forbid any commit to `main`. Tagging the
existing commit and branching first satisfies both: the operator's work is preserved, `main` is
untouched at the exact hash they left it, and the restore path is unchanged.

**Rejected:** Following section 1.3 literally, because it violates a stated prohibition. Discarding the
untracked work, because IRONCLAD forbids discarding the operator's work.

**Reversal trigger:** None needed. This is strictly safer than the alternative.

## D-DEV-02: Edits to existing files must preserve that file's line endings

Date: 2026-08-30 | Trigger: self caught defect in checkpoint 001 | Reversibility: easy

**Decision:** Before editing an existing file, determine its line endings and preserve them. For
additive changes to LF files, rebuild from the git blob bytes and append rather than rewriting.

**Rationale:** The agent's file writer emits CRLF. `.gitignore` was LF, so a ten line addition produced
a diff of 69 insertions and 60 deletions, rewriting every line. The repository has no `.gitattributes`,
`core.autocrlf` is false and `core.eol` is lf. Measured: `README.md`, `src/auspice/config.py`,
`apps/web/package.json` and `.github/workflows/ci.yml` are pure LF; `pyproject.toml` is CRLF. A diff
that rewrites a whole file hides the actual change from review.

**Reversal trigger:** If a `.gitattributes` is added normalising the repository, this becomes moot.


## ADR-002: Prospective scoring builds features from a specification, not from a written row

Date: 2026-08-31 | Trigger: audit finding P1-4, uncapped savepoints in the read path | Reversibility: easy

**Decision:** Remove the savepoint from the scoring path. `ApplicationSpec` is a `TypedDict` describing
the exact record shape `features/builder._build` consumes, `build_for_spec` is the public entry point,
and `score/engine._synthetic_feature_row` constructs the specification in memory. `build_for_application`
is unchanged in signature and now reads a row into the same shape.

**Rationale:** The finding asked for a cap. A cap would have to be at least 500 to leave the documented
500 site portfolio working, so it would never fire, and it would leave the underlying inversion in place:
a read endpoint that requires write capability. `_build` already takes a mapping and never re-reads
`application` after it, so the seam existed and was simply not exposed. Measured consequences of the old
path, per site scored: one subtransaction, one dead tuple in the graph's primary table, one burned
sequence value. A 500 site portfolio produced 500 of each inside a single long lived snapshot, and 13 per
site when alternatives are enabled.

**Rejected:** Capping the count, because the cap could never fire without breaking the product.
Reusing one savepoint for a whole batch, because a single failure would then poison every site in the
request, where per site savepoints isolated failures. A dataclass instead of a `TypedDict`, because a
dataclass invites default values and a field defaulted for a prospective site is a feature that is
silently wrong rather than reported missing.

**Dissent:** BREAKER held that refactoring the leakage critical path risks a silent feature difference
that no test catches, and would only accept the change with a proof of equivalence. That objection is
answered rather than overruled: `tests/unit/test_features_spec_equivalence.py` builds one real
application by both routes and requires identical values, identical missing sets, identical as-of and
identical application id, and a companion test asserts the comparison is not vacuous by requiring at
least ten populated features and three comparable decisions.

**Also from the pre-mortem:** the most likely future incident was a column added to `application` that
`_build` begins reading, leaving the historical path working and the prospective path raising
`KeyError` in production. Two mechanisms close it. Strict mypy rejects an `ApplicationSpec` literal
missing a key, and a test parses `_build` with `ast` and asserts the set of keys it reads equals the set
the type declares, in both directions.

**Second pre-mortem finding, fixed:** the old INSERT chose the decision body with
`ORDER BY seats DESC NULLS LAST LIMIT 1`, which is not deterministic when two bodies have equal seats.
`_PROSPECTIVE_CONTEXT_SQL` adds `b.id` as a tiebreaker, so the same site cannot score two ways. The test
seeds two bodies with different seat counts so the choice is exercised rather than trivially satisfied.

**Not done in this task, deliberately:** `app.deps.get_connection` still opens a writable transaction.
Removing the write from scoring makes a read only connection possible, and serving scores from a hot
standby possible after that, but changing the connection dependency in the same checkpoint would make a
rollback unable to separate the two behaviours. Logged as A-015.

**Reversal trigger:** If a feature is ever needed that genuinely requires the application row to exist
in the database, for example a feature computed by a trigger or a generated column, `build_for_spec`
cannot serve it and the savepoint returns. `months_to_decision` is a generated column today and is not
read by `_build`, so this is not currently the case.

**Checkpoint:** checkpoint/019-no-savepoint-scoring
