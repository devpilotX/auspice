# Privacy

Last revised 27 August 2026. Not reviewed by counsel, and it says so for the same reason the terms page
does. Everything below was written by reading the code rather than by describing an intention, and the
claims about what the site does not do are checkable in this repository.

## What the website collects

Nothing, by itself. There is no analytics package, no tag manager, no advertising pixel, no session
recorder and no third party script of any kind. The Content Security Policy blocks scripts from any origin
other than this one, so a tracker could not load even if one were added by accident.

The only thing stored in your browser is your light or dark theme choice, kept by `next-themes` so the page
does not flash the wrong theme on load. It is a preference, it never leaves your device, and clearing site
data removes it.

There is no cookie banner because there are no cookies to consent to.

## What the API receives

The interface talks to an API, and that API receives what you send it:

**Site details you ask us to score.** Jurisdiction, use class, relief sought, acreage, capacity, a coordinate
if you give one, and whatever label you typed. This is commercially sensitive, and it is the reason the
portfolio screen parses a pasted list or an uploaded file in your browser rather than uploading the file:
nothing reaches a server until you ask for a score on it.

**Your API key.** Stored as a hash rather than in the clear, and compared with a constant time comparison.
We can tell that a key is valid and which tier it belongs to. We cannot recover the key from what we store.

**The ordinary metadata of an HTTP request**, including your IP address, which the web server sees in order
to answer at all.

## What is kept

A score is computed and returned. It is not written to the database unless it is published, and publishing
is a separate deliberate action rather than a default, because a published prediction cannot be withdrawn.

**A published score is public and permanent.** It carries the site details it was computed from, including
the label you gave it, in an append only ledger that anyone can download. Do not publish a score for a site
whose existence is confidential. The flag exists so that this is a decision rather than an accident.

An unpublished score leaves no record beyond ordinary server logs.

## What we do not do

- We do not sell, rent or share your data with anyone.
- We do not build a profile of you, your firm, or the sites you have asked about.
- We do not tell a county, a community group, or a competitor that you asked about a parcel. Section 3 of
  the neutrality charter is the longer version of this and it is the commitment the product depends on.
- We do not predict how a named individual will vote, so we hold no model of any person's intentions.

## Data about public officials

The corpus contains the names of elected and appointed officials, their terms of office, and how they voted
on published records. This is public record, gathered from published minutes and county websites, and it is
used in aggregate to model how a body behaves.

We do not infer motives, we do not model private characteristics, and no feature in the model is a
prediction about a named person. `docs/NEUTRALITY.md` states that as a rule the code enforces rather than as
an intention.

## Your requests

Because unpublished scores are not retained, there is usually nothing to export or delete. Where there is,
including an API key, the operator of your deployment can remove it.

The one thing that cannot be deleted is a published ledger entry. That is a design decision rather than a
limitation, and it is stated in the terms as well, because it is the sort of thing someone should learn
before they publish rather than after.

## Changes

This page is a file in the repository and is rendered from it, so its history is the change log. If it says
something the code does not do, the code is the truth and the page is a bug.
