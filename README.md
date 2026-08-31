<div align="center">
  <img src="apps/web/public/brand/templum-primary.svg" alt="Permission Bureau" width="72" height="72" />
  <h1>P E R M I S S I O N&nbsp;&nbsp;B U R E A U</h1>
  <p><strong>A rating bureau for the right to build.</strong></p>
</div>

---

Permission Bureau produces a calibrated probability and a time distribution for whether a specific
project will actually be permitted at a specific location, and it publishes its own
accuracy record so the number can be used by a credit committee.

The industry has plenty of data vendors. It does not have a rating agency.

## What this repository contains

Eleven pipeline stages, five models, one API, one web interface, and an append only
prediction ledger. The full reasoning behind every choice is in `AUSPICE_Master_Spec.md`.
The short version:

- **The Permission Graph** is the asset. A structured record of every body that can say no,
  every decision it has made, and the quoted reasoning behind it.
- **No language model produces the number.** Language models read documents and write
  sentences. The probability comes from a statistical model that can be back tested and
  calibrated. That distinction is the reason an accuracy record can be published at all.
- **Every fact carries provenance.** A quote that is not found verbatim in its source
  document is discarded, not flagged. Hallucinated citations are eliminated by mechanism
  rather than by trust.
- **The system is allowed to refuse.** `abstained` is a first class field. A system that
  always answers is trusted exactly once.

## Layout

```
auspice/
├─ src/auspice/              one installable Python distribution
│  ├─ pipeline/
│  │  ├─ registry/           stage 0   who actually decides for this parcel
│  │  ├─ adapters/           stage 1   five civic platform connectors
│  │  ├─ ingest/             stage 1   fetch, hash, store, dead letter
│  │  ├─ parse/              stage 2   PyMuPDF to pdfplumber to Tesseract cascade
│  │  ├─ transcribe/         stage 3   hearing audio to citable transcript
│  │  ├─ extract/            stage 4   strict schema, verbatim quote verification
│  │  ├─ resolve/            stage 5   entity resolution, reversible merges
│  │  ├─ graph/              stage 6   the Permission Graph
│  │  ├─ features/           stage 7   point in time, bi-temporal, leakage proof
│  │  └─ flows/              orchestration entry points
│  ├─ models/
│  │  ├─ baseline/           base rate benchmark and XGBoost
│  │  ├─ hierarchical/       NumPyro partial pooling model
│  │  ├─ survival/           time to decision with censoring and competing risks
│  │  ├─ rulechange/         will the rules change before a decision
│  │  └─ eval/               calibration, backtests, the kill test
│  ├─ score/                 the score object, abstention, explanations, alternatives
│  ├─ ledger/                hash committed public prediction ledger
│  ├─ memo/                  HTML to PDF committee memo
│  ├─ monitor/               diffing, materiality scoring, alerts
│  └─ cli/                   the `auspice` command
├─ apps/
│  ├─ api/                   FastAPI service, including PostGIS vector tiles
│  └─ web/                   Next.js 15 interface, public accuracy page, MapLibre coverage map
├─ packages/shared-types/    OpenAPI generated TypeScript, one source of truth
├─ data/
│  ├─ registry/              jurisdiction registry, hand built, version controlled
│  └─ labels/                labelled decisions with mandatory citations
├─ infra/
│  ├─ migrations/            Alembic
│  ├─ docker-compose.yml
│  └─ scripts/               portable PostgreSQL bootstrap for Windows
├─ tests/
│  ├─ golden/                hand checked extraction fixtures, the regression suite
│  ├─ unit/
│  └─ synthetic/             generated corpora for testing model mathematics only
└─ docs/
   ├─ METHODOLOGY.md         published
   ├─ NEUTRALITY.md          published
   ├─ DATA_SOURCES.md        published
   └─ OPERATIONS.md          internal
```

Two deviations from section 7.4 of the specification, both deliberate. First, the Python
code lives under `src/auspice/` as a single distribution rather than as four sibling top
level directories, because four directories on `sys.path` means four import path hacks and
no benefit. The subpackage names are unchanged, so the mapping to the specification is one
to one. Second, `tests/synthetic/` exists and is not in the specification. It holds
generated data used to prove that the calibration and survival mathematics are correct
against a known ground truth. Nothing in it is ever used for a published claim, and
`auspice eval kill-test` refuses to read it.

## Getting started

Requirements: Python 3.13, Node 24, and PostgreSQL 17 with PostGIS. On Windows without
Docker or administrator rights, `infra/scripts/bootstrap-postgres.ps1` fetches the
PostgreSQL and PostGIS binary archives and initialises a cluster under `var/`.

```bash
# Python toolchain and dependencies
uv sync --all-extras

# Database
pwsh infra/scripts/bootstrap-postgres.ps1     # Windows, no admin needed
docker compose -f infra/docker-compose.yml up -d db   # anywhere else
uv run alembic -c infra/alembic.ini upgrade head

# Load the hand built registry and the labelled decisions
uv run auspice registry load
uv run auspice labels load

# The honest test. Trains on everything before the cutoff, predicts what follows.
uv run auspice eval kill-test

# Score a site. Returns an abstention when the evidence is too thin, which is an answer.
uv run auspice features build
uv run auspice train all
uv run auspice score site --jurisdiction us-va-loudoun --acres 412 --capacity-mw 300

# Publish it to the append only ledger, then render the committee memo.
uv run auspice score site --jurisdiction us-va-loudoun --publish
uv run auspice memo render <public-id>
uv run auspice ledger verify

# Interfaces
uv run uvicorn app.main:app --app-dir apps/api --reload
npm --prefix apps/web run dev
```

Publishing is behind a flag rather than the default. A ledger entry cannot be revised or deleted,
so committing one should be something an operator did on purpose.

## The test that decides everything

`auspice eval kill-test` trains on decisions before a cutoff date and predicts held out
decisions after it. It reports the Brier score against the base rate benchmark, expected
calibration error, interval coverage, and abstention precision.

The pass condition is a Brier skill score of at least 0.15 against the base rate, expected
calibration error under 0.08, and 80 percent interval coverage between 0.76 and 0.84.

The command refuses to report a verdict on fewer than 400 labelled decisions or fewer than
60 held out decisions. It prints `INSUFFICIENT DATA` instead. A verdict computed on a
sample too small to support it is worse than no verdict, because someone will quote it.

## What this does not do yet

The corpus is the product and the corpus is small. Stated plainly, because the number of ways
to imply otherwise is large:

- **The kill test has no verdict.** It needs 400 labelled decisions and holds 1. It prints
  `INSUFFICIENT DATA` and names the four things blocking it. Every claim about calibration in
  `docs/METHODOLOGY.md` is a claim about the method, not a measured result.
- **Every site abstains.** With one outcome class in the training data, no probability from it is
  defensible, so the scorer refuses. That is the system working, and it is also not yet a product.
- **Extraction is unproven end to end.** The schema, the quote verifier and the golden fixtures all
  run, and no language model has read a document, because that needs a key. `tests/golden/` is what
  will measure accuracy the day one is configured.
- **Several features report unknown rather than a value.** Board composition needs per member vote
  records. Setback and distance need parcel geometry. Neither is loaded, so those columns are absent
  rather than zero.
- **Transcription is not run at scale.** The pipeline works on a file. No hearing audio has been
  ingested in volume.

The mechanisms are built and tested. What is missing is data, and the order matters: the
specification says data and labels first, then the model, then the interface, and the reason to
follow it is that a screen built on an unmeasured model is a screen that lies confidently.

## The interface

Eight pages, all of which answer with real data or say plainly that they cannot.

| Page | What it is for |
|---|---|
| `/` | What the product claims, and the one number it will not give you yet |
| `/portfolio` | Section 5.4 product 2. Paste or upload a site list, get it ranked, with the sites we would not score kept separate rather than sorted last |
| `/accuracy` | The published record. Reliability curve, Brier score, the ledger, and a link to download all of it |
| `/jurisdictions` | Coverage. The map, site search, and the twelve counties with their depth and freshness |
| `/jurisdictions/[slug]` | One county's profile. Indexed, no login |
| `/report/[publicId]` | A published score, with its drivers, precedents and evidence drawer |
| `/method`, `/neutrality`, `/data-sources` | Rendered from `docs/`, so the published claim and the enforced one cannot come apart |

The map serves vector tiles from PostGIS with `ST_AsMVT`. There is no basemap and no tile vendor.
Shading is decision depth, never probability, and the coverage table below it is the same information
and works without it.

## Writing and design

Interface copy, documentation, commit messages and memo text follow one rule above the
rest: they read as though a person wrote them, because a person did. No em dashes. None
of the vocabulary that gives machine writing away, and `tools/check_writing.py` enforces
the mechanical part of that in CI. When the model does not know, the copy says we do not
know.

The design system is a document that happens to be interactive. Two pixel radius, no
shadows anywhere, hairlines for all separation, one chromatic colour. Probability is never
coloured, because a green 82 percent reads as advice and this product does not give advice.
All tokens live in `apps/web/src/styles/tokens.css` and nothing hardcodes a colour anywhere
else.

## Licence

Not licensed for redistribution. The method is published in `docs/METHODOLOGY.md`; the
corpus, the labels and the ledger are the asset.
