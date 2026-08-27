# Operations

Internal. Not published, unlike the other three documents in this directory.

What to run, what breaks, and what to do about it. Written for whoever is on call, which for now is one
person.

Last revised 27 August 2026.

## The dashboard that matters

Section 16.4 says one page, checked daily, five lines:

1. Predictions published, cumulative.
2. Predictions resolved, and the running Brier score.
3. Sources within their freshness window, as a percentage.
4. Quote verification pass rate, last 24 hours.
5. Paying customers, and revenue.

If lines 1 and 2 are healthy, the company is compounding something that cannot be bought. Nothing on any
other dashboard matters more.

```bash
uv run auspice ledger status        # lines 1 and 2
uv run auspice registry status      # line 3, per jurisdiction
uv run auspice labels stats         # line 4
```

## Bringing it up

```bash
uv sync --all-extras

# Windows, no Docker, no admin. Fetches PostgreSQL 17, PostGIS and pgvector into .tools/ and
# initialises a loopback only cluster under var/.
pwsh infra/scripts/bootstrap-postgres.ps1

# Anywhere else.
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml up -d db

uv run alembic -c infra/alembic.ini upgrade head
uv run auspice registry load          # fetches boundaries from the Census, cached after the first run
uv run auspice labels load
uv run auspice labels verify          # fetches every cited source and checks every quote
uv run auspice features build
```

The bootstrap script is idempotent. `-Reset` destroys the data directory and starts from a fresh initdb,
which is the only destructive flag in the repository and it says so in its help text.

## The daily run

```bash
uv run auspice ingest run          # fetch, hash, store, dead letter
uv run auspice parse run           # the PyMuPDF to Tesseract cascade
uv run auspice extract run         # needs a language model key, otherwise reports unavailable
uv run auspice resolve run
uv run auspice features build
uv run auspice monitor run
```

Each stage is independently re-runnable and idempotent. Re-running ingest on unchanged content is free,
because the raw store is keyed by the hash of the bytes and a matching hash means no downstream work.

## What actually breaks, in order of how often

**A portal changes its markup.** The most frequent failure and the most dangerous, because it is silent. A
CivicPlus theme change makes `_parse_agenda_center` return zero meetings, and zero meetings looks exactly
like a quiet county.

How you find out: the freshness table. A jurisdiction that stops producing documents shows as stale within
its refresh window and then broken, and both are on the public page. That is the reason freshness is
published rather than internal.

What to do: run the adapter against the live page, compare with the recording in `tests/golden`, and fix the
parser. Then add the new shape to the golden set, because a fix with no regression test is a fix that gets
undone.

**A government site rate limits us.** Expected, and handled: 429 and 503 back off with exponential jitter
and the source goes to the dead letter queue after repeated failures.

What not to do: raise the rate limit or rotate an address to get around it. Access is the business, and
section 15.2 is not decoration. If a host is refusing us, the answer is a slower crawl or a formal public
records request.

**Quote verification pass rate drops.** Section 16.2 puts the floor at 99 percent, below which extraction is
unsafe. A drop usually means one of two things: a model change altered how quotes are reproduced, or a
source started serving JavaScript rendered pages whose HTML holds no text.

Check which by looking at whether the failures cluster on one host. If they do, it is the source. If they are
spread across hosts, it is the model, and the prompt version needs pinning until it is understood.

**The dead letter queue grows.** Drained weekly to zero, per section 16.2. A queue nobody drains is a queue
hiding a broken adapter.

```bash
uv run auspice ingest dead-letters
```

**The hierarchical model stops converging.** It refuses to serve rather than serving a bad posterior, so the
symptom is the boosted model being reported instead. Usually caused by a jurisdiction with a single outcome
class entering the training set, which makes its intercept unidentified.

**The ledger fails verification.** This is the serious one. The API refuses to start, which is deliberate:
serving an accuracy page from a broken chain would make a public claim on a record that cannot be trusted.

```bash
uv run auspice ledger verify     # reports the exact sequence number where it breaks
```

A break means an entry was edited or deleted. Find out how before restoring anything, because a restore that
does not explain the break leaves the same hole open. The chain is verifiable from the published export, so
an independent copy is the reference.

## Backups

Nightly `pg_dump` plus WAL archiving to object storage, and a restore tested weekly. An untested backup is
not a backup.

What has to survive: the raw corpus, the labels, and the ledger. Everything else is derived and can be
rebuilt. The corpus is content addressed and immutable, so it is append only in the backup too.

What matters most in a restore is the ledger, because it is the only thing that cannot be reconstructed.
Losing the corpus costs months of re-crawling. Losing the ledger costs the company its record, and there is
no way to earn that back other than by waiting.

## Secrets

Never in git. `.env` is gitignored and `.env.example` documents every variable.

Injected from a secret manager in production. The settings object refuses to construct in production without
a crawler contact address, object storage credentials and API keys, so a half configured deploy fails at
startup rather than serving something wrong.

The database password generated by the bootstrap script lives at `var/pg.superuser.pw`, which is inside the
gitignored `var/` directory. It is a local development cluster on loopback only.

## Cost control

Section 7.5 puts language model inference at the top of the variable cost line, and the levers in order of
impact:

1. **Cache by content hash and prompt version.** Reprocessing unchanged documents costs nothing. Usually a
   five to ten times saving on its own.
2. **Triage with the cheap model.** Around nine documents in ten are irrelevant to a given use class, and
   discovering that with a frontier model costs thirty times what it needs to.
3. **Batch where latency does not matter.** Roughly half price.
4. **Extract once, derive features many times.** Facts live in PostgreSQL; a feature change never re-invokes
   a model.
5. **Escalate, never default.** Cheap deterministic parsing first, a model only when parsing fails.

Transcription is scoped to the top counties and, within a meeting, to the agenda items that mention the
target use class. A three hour hearing is roughly twenty to forty minutes of relevant audio.

## Before shipping a model change

```bash
uv run pytest -q
uv run auspice eval kill-test --json-out artifacts/kill-test.json
```

The kill test refuses to report a verdict below the sample size floors and prints `INSUFFICIENT DATA`
instead. Do not adjust the test until it passes. If it fails, write down what the residuals looked like and
change the wedge rather than the threshold.

A model that has not converged must not be promoted. Promotion is a separate command from training for
exactly that reason.

## Before shipping an interface change

```bash
npm run lint --workspace apps/web
npm run typecheck --workspace apps/web
npm run build --workspace apps/web
npm run budget --workspace apps/web
npm run test:visual --workspace apps/web
node scripts/check-audit.mjs
uv run python tools/check_writing.py
```

The report screen and the accuracy page must never silently break, which is what the visual regression
covers. The budget catches weight added without noticing.

## The one thing that cannot slip

Publishing predictions. Section 8.2: a competitor starting today is permanently behind on the record and
cannot buy their way forward, but only if the record is actually accruing. Every day without a published
prediction is a day of the only unassailable advantage in this business, gone and unrecoverable.

Nothing on this page is more urgent than that, including fixing a broken adapter.
