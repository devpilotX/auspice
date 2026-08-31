# Terms of use

Last revised 27 August 2026. These terms have not been reviewed by counsel. They describe what Permission Bureau
actually does and what it will not stand behind, written by the people who built it. Before this product is
sold, a lawyer in the relevant jurisdiction should read them. That statement is here rather than in a
footnote because a terms page that implies legal review it has not had is worse than no terms page.

## What Permission Bureau sells

An opinion, expressed as a probability, about whether a specific project will be permitted at a specific
location, together with the evidence behind it and a published record of how accurate previous opinions
turned out to be.

That is the whole product. It is not a permit, not a guarantee, not an appraisal, not an insurance policy,
and not legal advice. Nobody at Permission Bureau can make a county approve your application, and nothing here
changes the outcome of a vote.

## What the number is and is not

A probability of 0.62 means that of a large number of applications we would score at 0.62, we expect
roughly 62 percent to be approved. It does not mean your application is 62 percent approved, and it does
not mean the deciding body has formed any view. A single application either happens or does not, and no
probability short of 0 or 1 is falsifiable on one case.

We publish our calibration record at `/accuracy` so that this claim can be checked rather than trusted. If
the record is not there, or is stale, treat every number on the site as unmeasured.

## When we refuse to answer

The system abstains when the evidence behind a number is too thin to support it. An abstention is a real
answer and is delivered as one. It is not an error, it is not a degraded result, and it must not be read as
a low probability. A site we will not score and a site we score at 0.05 are different claims, and we keep
them visually and structurally separate for that reason.

Do not convert an abstention into a number by any means, including averaging it with other sites,
substituting a default, or treating a missing value as zero.

## What you may and may not do with a score

You may use a score, a memo and the evidence behind it inside your own organisation, share it with your
own advisers, lenders and investors, and quote it in an internal decision document.

You may not:

- present a score as a determination by any government body
- present a score as our prediction about how a named individual will vote, because we do not make those
  and the model has no such term
- remove the abstention, the interval, or the data as of date from a number when passing it on, since each
  of those is part of what the number means
- resell, sublicense or redistribute the corpus, the labels or the ledger, which are the asset rather than
  the output

## The ledger is permanent

A published prediction is committed to an append only ledger whose entries are hash chained. We cannot
revise or delete one, including at your request, because the ability to do so would destroy the only thing
that makes the accuracy record worth reading. Publishing is a deliberate act behind a flag for exactly this
reason.

If a published prediction contains a factual error, we can publish a correction that references it. We
cannot make the original disappear.

## Data we hold about your projects

A site list you paste or upload into the portfolio screen is parsed in your browser and is sent to our API
only when you ask for a score. See `/privacy` for what happens to it after that.

## Accuracy, uptime and change

We do not promise a level of accuracy, and the published record is a statement about the past rather than a
commitment about the future. Uptime is not promised either. The model changes, and when it does, the model
version travels with every score so a number you hold can be traced to what produced it.

Where our data about a jurisdiction is more than fourteen days old, the score is flagged. Beyond ninety
days we refuse to score at all rather than answer from rules that may no longer exist.

## Liability

To the extent the law allows, Permission Bureau is not liable for any decision made in reliance on a score, a memo,
an abstention, or anything else on this site. Permitting decisions involve discretion exercised by elected
and appointed people, and a probabilistic opinion about what they will do is not a substitute for your own
diligence, your own counsel, or your own reading of the record.

You are buying a better prior, not certainty. If you need certainty, the only source of it is the permit
itself.

## Contact

Questions about these terms, or a factual dispute about a published prediction, should go to the operator
of your Permission Bureau deployment. This repository does not publish a contact address, because the deployment that
serves you may not be ours.
