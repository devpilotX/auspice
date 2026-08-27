<div align="center">
  <img src="apps/web/public/brand/templum-primary.svg" alt="Auspice" width="72" height="72" />
  <h1>A U S P I C E</h1>
  <p><strong>A rating bureau for the right to build.</strong></p>
</div>

---

Auspice produces a calibrated probability and a time distribution for whether a specific
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
│  ├─ api/                   FastAPI service
│  └─ web/                   Next.js 15 interface and public accuracy page
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

# Interfaces
uv run uvicorn app.main:app --app-dir apps/api --reload
npm --prefix apps/web run dev
```

## The test that decides everything

`auspice eval kill-test` trains on decisions before a cutoff date and predicts held out
decisions after it. It reports the Brier score against the base rate benchmark, expected
calibration error, interval coverage, and abstention precision.

The pass condition is a Brier skill score of at least 0.15 against the base rate, expected
calibration error under 0.08, and 80 percent interval coverage between 0.76 and 0.84.

The command refuses to report a verdict on fewer than 400 labelled decisions or fewer than
60 held out decisions. It prints `INSUFFICIENT DATA` instead. A verdict computed on a
sample too small to support it is worse than no verdict, because someone will quote it.

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
