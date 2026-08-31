# The neutrality charter

Binding. Not a statement of values.

Permission Bureau sells a number that people rely on. The moment we have a side, the number is worth nothing, and no
amount of accuracy repairs that. So the commitments below are constraints on the business rather than
aspirations for it, and each one is written to be checkable.

Last revised 27 August 2026.

## The six rules

**1. We take no land positions, ever.** No parcels, no options, no joint ventures, no carried interest in
any project we score. Not through a subsidiary and not through a person connected to us.

**2. We do no brokerage, development, lobbying or expediting.** These are lucrative and they are the exact
services that would destroy the asset. If you want someone to help get your project approved, we are not
that and we will not refer you to one for a fee.

**3. We never advocate for or against an application.** We will not appear at a hearing on either side. We
will not write a letter of support or of objection. If our data is cited at a hearing by either party, that
is public information being used as it should be, and we do not join in.

**4. The same data is available to everyone.** Developers, lenders, insurers, counties and community
groups. The last two at no cost.

This is unprofitable and it is not negotiable. It is the defence against the fair criticism that this is a
tool for capital to defeat communities, and it produces the best data quality feedback in the system,
because the people who know a county's record best are the people who live there.

**5. We model published voting records and stated positions, never inferred motives.** Aggregate body
behaviour only. We will not publish a prediction about how a named individual will vote, we will not
characterise anyone's reasons beyond what they said on the record, and we will not imply corruption.

**6. No customer can pay to change a score, see another customer's queries, or suppress a result.**

## On rule six

Rule six is the one that gets tested, and it will be tested by a large customer with a large cheque, framed
as something reasonable. A request to review a score before it publishes. A request to delay one. A request
to remove a county from the public profiles because a deal is sensitive.

The answer is no, in writing, the first time.

Not because the request is dishonourable. Usually it is not. It is because the value of every other number
we produce rests on the fact that this one cannot be bought, and a single exception is not a small
concession, it is the end of the asset. There is no version of this where we make an exception quietly and
the exception stays quiet.

If that costs us a customer, it costs us a customer.

## What we publish about ourselves

**Our accuracy record, including the calls we got wrong.** Every prediction is hashed and chained before
any outcome exists, so nothing can be revised or removed after the fact. The full ledger is downloadable
and every line can be verified without using our tooling.

**Our misses, with a written explanation.** Not a count. The specific call, what we said, what happened, and
what the model missed. Nobody who is hiding results volunteers their failures, which is exactly why this is
worth something.

**How stale our own data is, per jurisdiction.** Published on the same page as the accuracy record. A bureau
that hides how out of date its inputs are has already decided what kind of company it is.

**Our methodology.** In full, in `docs/METHODOLOGY.md`, including the limitations and the assumptions we
could not test. Publishing the method invites imitation. The corpus and the record are the asset, and
neither can be copied.

**When we do not know.** The system abstains rather than producing a number it cannot stand behind, and an
abstention is a first class outcome rather than an error. A system that always answers is trusted exactly
once.

## What we are not

Not legal advice. A probabilistic opinion with a disclosed method, in the same category as a credit rating
or an appraisal. That distinction is legal necessity, not marketing, and we will not blur it in a sales
conversation.

Not an appraisal, and not a guarantee.

Not a permit tracking tool, a workflow product, or a chatbot over documents.

Not a government product. Public bodies get their own jurisdiction's data at no cost, and we do not sell to
them, because procurement cycles measured in years would change what this company optimises for.

## The ethical question, taken seriously

The fair version of the criticism is this: does a tool that prices local opposition help capital route
around communities?

The honest answer has four parts.

The same information helps both sides, and both get it. A county learns how its own process actually
performs against its peers. A community group learns what the record shows rather than what either side
claims it shows. Neither pays.

Better prediction reduces conflict rather than increasing it. A developer who learns in week one that a site
is hostile does not spend eighteen months fighting a community that never wanted the project. The fights
that get avoided are avoided for both sides, and the eighteen months belong to the residents as much as to
the developer.

We model institutions, not people. Aggregate behaviour and published records. Never a prediction about a
named person and never an inference about anyone's motives.

We are transparent about the method precisely so that the criticism can be made specifically. A vague
objection to an opaque system cannot be answered. A specific objection to a published method can be, and
sometimes the objection will be right.

## Permanent hard lines

- No modelling of individual officials' motives.
- No inference of corruption or bad faith.
- No guaranteed approval product, at any price.
- No introductions to officials.
- No paid influence on any score.
- No selling of community organiser data to developers, in any form, aggregated or not.

## Skin in the game, in this order and no other

Financial exposure to our own accuracy is the strongest trust signal available. It is also the fastest way
to go bankrupt if offered before calibration is proven, so the order is fixed.

1. Publish accuracy. Prospective, hashed, graded in public.
2. A fee back guarantee on materially wrong calls, after six months of calibration data.
3. A warranty product with a defined payout, after twelve months and expected calibration error under 0.08.
4. Parametric delay cover with a carrier, after twenty four months and an actuarial review.

We are at step one, and step one is not finished.

## Holding us to this

Every commitment here is either checkable in the code or checkable in public.

- The ledger is append only by structure and `auspice ledger verify` recomputes the whole chain.
- The abstention rule is in one file and tested against every way of relaxing it.
- The published methodology is served from the same constants the code enforces, so it cannot drift.
- The free county and community tier is a tier in the code, not a discount applied by hand.

If you find us in breach of any of it, the failure is ours and we would rather hear it from you than not.
