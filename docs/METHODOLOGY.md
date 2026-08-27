# Methodology

Published because you should not have to trust us.

This document describes how a number is produced, what it is not, and where it breaks. It is written to
be read by someone who will be asked to defend a decision that used it. If anything here is unclear, that
is a defect in the document and worth telling us about.

Last revised 27 August 2026.

## The short version

We assemble a structured record of every body that can refuse permission, every decision it has made, and
the quoted reasoning behind it. A statistical model reads that record and produces a probability with an
interval, plus a distribution of time to a decision. When the record is too thin to support a number, we
say so instead of producing one.

No language model produces the number. That distinction is the reason we can publish an accuracy record at
all, and it is worth being precise about.

## What language models do here, and what they do not

Language models do two things in this system. They read documents and extract facts into a fixed schema,
and they turn a driver the statistical model already computed into one plain sentence.

They do not produce the probability, the interval, the timeline, or the ranking. A number produced by a
language model cannot be back tested, cannot be calibrated, and cannot be audited, because there is no
parameter to fit and no held out set that means anything. It can only be trusted or not trusted. That is
not a basis for a credit decision.

The extraction step is constrained in three ways that matter:

- The output must satisfy a JSON Schema in which the evidence array has a minimum length of one. A fact
  with no source is rejected by the schema rather than by review.
- Every quote is checked against the stored source document. The match is exact, and insensitive only to
  how whitespace was laid out, because a line break inside a PDF is a rendering artefact and never
  content. A changed word, a dropped clause or a different number fails. There is no edit distance and no
  similarity threshold anywhere in that check.
- A quote that does not match causes the whole extraction to be discarded and retried. It is not kept with
  a warning attached. A model that fabricated one citation has demonstrated that its reading of the
  document is not reliable.

High value documents go through a second pass with a different prompt at temperature zero. Where the two
passes disagree, the fact goes to a human rather than into the graph.

## The features

Seven groups: base rates and history, rules and discretion, politics and people, opposition, physical
characteristics, and applicant history. The full list, with the plain language sentence attached to each,
is served at `/v1/public/methodology` from the same constants the code enforces, so the published list
cannot drift from the implemented one.

A feature is only used if three things are true:

1. It can be computed for at least 80 percent of rows. This is measured, not assumed, and the measurement
   is printed by `auspice features build` along with the reason for every exclusion.
2. It derives from a document whose quote passed verification.
3. It can be explained to a customer in one plain sentence. A driver that cannot be explained cannot
   appear in a memo, and a memo is the thing that gets paid for.

Two features are computed and deliberately excluded from the model: the count of comparable decisions and
the months since the last one. They measure how much evidence we hold rather than what it says, and a model
that learned "more data means approval" would have learned something about our coverage rather than about
permission.

### Missing is missing

A feature that cannot be computed is recorded as unknown. It is never zero filled. A base rate of zero
means the county never approves, which is a strong claim, and making it out of ignorance is worse than
admitting the gap. Where a model needs a value, the uncertainty of not having one is carried into the
interval rather than hidden.

## Point in time construction

Every feature is computed as it would have been known on the filing date. If a score for a 2024 decision
used a 2025 ordinance, the model would be cheating, and the resulting accuracy figure would be a lie we
had published.

Three mechanisms make that enforceable rather than aspirational.

Every query takes an as-of date and every predicate filters on it. There is no code path that reads the
current state of anything.

The event table carries both the date something happened and the date it became publicly knowable. A
decision made on 3 March that only appeared in minutes published on the 20th was not knowable on the 10th,
and the history features read the second date.

A test builds features for a row, inserts four later decisions and a later moratorium, rebuilds, and
asserts that nothing moved. It fails if anyone writes a query without the date predicate, which is the
actual failure mode.

## The models

Five, because there are five questions.

**Base rate.** The historical approval rate for this use class in this jurisdiction, shrunk toward the
state and then toward the global rate by empirical Bayes with a Beta prior fitted by moment matching. This
is the benchmark everything else has to beat, and it is built to be as good as a base rate can be. A weak
baseline is the oldest way to fool yourself.

**Gradient boosted trees.** XGBoost, shallow, heavily regularised, with hyperparameters set by rule rather
than by search, because a hyperparameter search on a few hundred rows overfits the validation split. It
handles missing values natively rather than through imputation. Its intervals come from a bootstrap
ensemble and are labelled bootstrap intervals everywhere they appear, because they are not credible
intervals and calling them that would be a quiet overstatement.

**Hierarchical partial pooling.** The one that matters. Most jurisdictions have three to eight relevant
decisions, and a flat model on that either overfits noise or ignores locality. This one lets a
jurisdiction's intercept shrink toward its cluster and the cluster mean shrink toward the global mean, so a
county with forty decisions is scored almost entirely on its own record, and a county with two is scored
mostly on how similar counties behave with an interval that is correctly wide.

Clusters are built from legal framework, discretion and population density. They are not built from
outcomes, which would be circular and would guarantee tight, meaningless intervals.

Missing features are marginalised analytically rather than imputed. A missing standardised feature has a
marginal distribution close to standard normal, so its contribution to the linear predictor is normal with
the coefficient as its scale, and a row's missing cells contribute a single normal term. This is not a
refinement. Measured against a corpus with a known truth, the 80 percent interval covered 69 percent of the
time when missing values were imputed at the mean, and 78 percent once they were marginalised.

Sampling is NUTS in NumPyro, non centred. A run with an R-hat above 1.01 or any divergent transition does
not serve. An interval from a posterior that did not converge is worse than no interval.

**Survival.** Time to a decision, as a distribution, not a point. This has to be survival analysis rather
than regression for one reason that matters commercially: a pending application is right censored, not
missing. A project filed fourteen months ago with no decision is the information that at least fourteen
months have elapsed, and discarding those rows biases every timeline optimistically, which is exactly the
direction that destroys trust.

Approval, denial and withdrawal are three separate exits and are modelled as competing risks. The published
quantiles are for time to any decision, because that is the quantity the score object claims and it is far
better identified than time to approval specifically. Cumulative incidence is computed as the integral of
each cause specific hazard against overall survival, which is monotone by construction. Summing cause
specific survival curves is not, and it was visibly decreasing with time before that was corrected.

**Rule change hazard.** A separate model rather than a feature, because it is the risk humans most
consistently fail to price. A discrete time hazard on jurisdiction months, with a ridge penalty on the
covariates and none on the intercept. The penalty is not optional: restriction events are rare, and a
covariate that separates the data perfectly sends an unpenalised coefficient to infinity, which would make
the published number exactly zero or one.

The monthly hazard is held constant over the forecast horizon. With this many events, fitting a shape to
the hazard would be fitting a curve to four points. That assumption is stated rather than buried.

## Calibration

Calibration is not a metric here, it is the product claim. If we say 70 percent, it should happen about
70 percent of the time.

A calibrator is fitted after the model, on data the model has not seen. The training set is split by date,
the model is refitted on the earlier part, and the calibrator is fitted on its predictions for the later
part. Fitting a calibrator on the training predictions understates the error, and fitting it on the test
set is leakage that makes the reported number meaningless. Isotonic regression above a hundred rows, Platt
scaling below, because isotonic on a small sample has enough freedom to fit the noise.

The reliability curve uses equal width bins, deliberately. Equal count bins produce a smoother curve and
hide the region where the model is overconfident, which is the region the chart exists to show. Bins are
plotted at their mean predicted probability rather than at the bin midpoint, because plotting at the
midpoint flatters the model. Each bin carries a Wilson interval, so a bin resting on four observations does
not look as authoritative as one resting on four hundred.

## Validation

Temporal splits only. Random k-fold is invalid here and produces a beautiful, worthless result, because it
leaks future ordinances and future board compositions into the training set.

Leave one jurisdiction out as a second test, because generalising to a county the model has never seen is
what happens on every new customer's first site.

## What counts as a yes

Approval with conditions counts as approval. This is a real choice with a real cost, because conditions can
be onerous enough to destroy the economics, and it is stated here rather than left implicit. The conditions
are kept in the record so a later model can separate them.

Withdrawal is not denial and it is not discarded. A high withdrawal rate is a feature in its own right,
because it measures hidden denials: staff killing projects quietly before a vote. In a county where a third
of applications are withdrawn, the true denial rate is far higher than the recorded one.

Approval later voided by a court is recorded as approval, because that is what the body decided and the
approval model predicts what the body will do. The reversal is carried as litigation events and is priced
separately. This is a genuine limitation: for a developer, a rezoning voided on appeal is as dead as one
denied. It is named here so nobody discovers it in a deal.

## When we refuse to answer

We abstain when all three of these hold:

- fewer than three comparable decisions in this jurisdiction, and
- more than 80 percent of any estimate would be borrowed from other jurisdictions, and
- the 80 percent interval would be wider than 0.35.

All three, joined by and. A rule that fired on any one of them would abstain on most of the corpus, which
is not intelligence, it is refusing to work.

We also abstain when our data for a jurisdiction is more than ninety days old, and when we cannot establish
which body decides for the parcel. The first is an addition to the original design: a score is flagged at
fourteen days, and a flag is right at that horizon, but at three months the ordinance a score assumed may
no longer exist, and a flagged number still gets pasted into a memo without the flag.

An abstention carries no number at all. Not a greyed one, not one behind a warning. A number with a caveat
beside it gets separated from the caveat.

## The sample size floors

`auspice eval kill-test` refuses to report a verdict below 400 terminal decisions and 60 held out, and
prints `INSUFFICIENT DATA` with the specific blockers instead.

That threshold is not in the original specification and is worth justifying. The standard error of a Brier
skill estimate on n held out decisions falls roughly as one over the square root of n. Below a few hundred
training rows with sixty held out, the 95 percent interval on the skill score spans both zero and 0.3,
which is to say it contains both "clear signal" and "no signal". A verdict computed there is a coin flip
wearing a number, and someone would quote it.

## The pass conditions

- Brier skill score against the base rate of at least 0.15, target 0.25.
- Expected calibration error below 0.08.
- Coverage of the 80 percent interval between 0.76 and 0.84. Both ends matter. Coverage of 0.95 fails,
  because an interval that always contains the answer carries no information.
- Area under the ROC curve above 0.70.
- Abstention materially better than answering on the same rows, so that refusing is intelligent rather
  than lazy.

These live in one file whose only job is to hold them, so relaxing one is a visible single line change
rather than a tweak buried in evaluation code.

## Current state, stated plainly

As of this revision the corpus holds one terminal decision with verified provenance against the 400 the
kill test requires. The kill test prints `INSUFFICIENT DATA` and no accuracy claim of any kind is published.

The model mathematics has been verified against a synthetic corpus with a known truth: the hierarchical
model reaches a Brier skill of 0.111 against the base rate, an area under the curve of 0.73 and an expected
calibration error of 0.059, recovers seven of eight generating coefficients inside a 90 percent credible
interval, and produces intervals covering the truth 78 percent of the time against a claim of 80.

That is evidence the code is correct. It is not evidence about permission risk, and it is not published as
an accuracy record. Nothing generated synthetically is ever used for a published claim, and the kill test
has no code path that reaches it.

## Known limitations

- Twelve counties. Everywhere else abstains. A shallow answer for three thousand counties would be a demo
  that dies in the first customer meeting.
- Individual voting records are not yet loaded, so board composition and swing seat count are unavailable
  and are recorded as unknown rather than neutral.
- Parcel geometry is not loaded, so setback compliance margin and distance to residential are unavailable.
  Both are named in the score object's missing features list when they are.
- Hearing transcripts are the highest value untapped input and are not yet ingested at scale. The pipeline
  exists; the corpus does not.
- Post approval litigation reversal is tracked but not yet modelled as a distinct risk.
- Relocation cost in the alternatives ranking is a placeholder of two points per hundred kilometres,
  labelled as a placeholder in the memo, because only the customer knows what moving actually costs.
- **Point in time features use occurrence dates, not knowledge dates.** History features filter on the date
  a decision was made and on the date an ordinance was adopted. They do not filter on the date the fact
  reached our corpus. The `event` table is bi-temporal and the monitor uses it that way, but `application`
  and `instrument` carry only `created_at`, which records our data entry rather than the county's
  publication, and the labelled rows were entered by hand long after the decisions they describe.

  What this costs: a backtest is optimistic to the extent that a decision reached us later than the county
  published it, because the model is credited with knowledge it would not have had. County minutes are
  usually published within days of a meeting, so the gap is small, and it is not zero. Closing it means
  giving each row a published-on date read from the source document. Until that exists, treat every
  backtest figure as a mild upper bound rather than an unbiased estimate.

## Things we will never do

We will never predict how a named individual will vote. Aggregate body behaviour and published voting
records only. Modelling individuals is legally reckless and ethically indefensible.

We will never infer or imply motive, corruption or bad faith.

We will never let a customer's identity influence a score, and no customer can pay to change one, see
another's queries, or suppress a result.

We will never quietly revise a published prediction. The ledger is append only by structure: editing a
payload, recomputing its hash, or deleting an entry all break verification at a reported sequence number.

We will never present a score without its interval and the date its data is current to.
