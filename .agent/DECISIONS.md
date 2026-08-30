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
