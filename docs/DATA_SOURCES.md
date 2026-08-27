# Data sources

Every source we read, how often we read it, and what we do not have. Published because a forecast is only as
good as its inputs and you should be able to check ours.

Last revised 27 August 2026.

## How we behave as a consumer of these systems

Access is the business. Burning it is unrecoverable, so the operating rules are stricter than the law
requires.

- `robots.txt` is fetched per host and honoured. A disallowed path raises an error and is not worked around.
  There is no override flag, because a flag that exists gets used.
- Rate limits are per host, not global, so one county's slow portal does not throttle the other eleven. A
  `Crawl-delay` directive slower than our own default is adopted.
- The crawler identifies itself honestly, with a contact address in the `From` header. The service refuses
  to start without one.
- Content is addressed by the hash of its bytes, so an unchanged page is never fetched twice and never
  reprocessed.
- On 429 or 503 we back off with exponential jitter and stop. Repeated failures go to a dead letter queue
  that is drained rather than ignored.
- Nothing behind a paywall or a licence is read without the licence. No exceptions.

Where scraping is unwelcome we use the published API if there is one, and a formal public records request if
there is not.

## What is loaded now

### Jurisdiction boundaries

**United States Census Bureau, TIGERweb.** County boundaries and land areas, keyed on FIPS code, fetched as
GeoJSON in WGS84 and cached to disk with the request URL and retrieval timestamp beside them.

Boundaries are fetched rather than typed. A hand entered polygon has no provenance and cannot be checked,
and a single transposed digit produces a spatial join that returns nothing, which looks exactly like a county
with no decisions.

All twelve counties in the registry have boundaries loaded. Land areas were checked against independent
figures: Maricopa County at 23,833 square kilometres and Loudoun at 1,336 are both correct.

### The jurisdiction registry

Hand built, version controlled at `data/registry/jurisdictions.yaml`, and every assertion in it carries a
source URL and the date it was read. The loader refuses a jurisdiction whose legal framework has no source.

What is asserted by hand: the name, kind and FIPS code, the legal framework, the decision bodies with their
seat counts and quorums, and the rule by which each body's election calendar is derived.

What is not asserted by hand: boundaries, which are fetched; election dates, which are derived from term
length, cycle and staggering rather than pasted as a list, because a pasted list rots and a wrong date
silently corrupts a feature; the discretion index, which is computed from the county's own decision record;
and the data depth counter, which is a count.

Legal framework classification is cited to state code where the citation is stable, and to the National
League of Cities comparative reference for the states where it is not. Per state statutory refinement is an
open item and is listed as one.

### Civic platform detection

Detected from each jurisdiction's live site rather than assumed, by matching host names, well known paths and
markup that each vendor emits. The result is written to `data/registry/platforms.detected.yaml`, which is a
separate file from the hand authored registry, because a machine detection and a human assertion are
different kinds of claim and should not share a file.

Detection is deliberately conservative. Seven of twelve counties were identified. Five returned `unknown`,
either because the site refused our request or because no fingerprint matched, and `unknown` means a human
looks at it rather than an adapter being pointed somewhere it cannot read.

The seven that resolved are concentrated on two vendors, which is direct support for the strategic claim that
a handful of good adapters beats ten thousand site specific scrapers.

### Labelled decisions

`data/labels/decisions.yaml`. Hand built ground truth, and the most valuable thing in the repository.

Every row carries either one official record or two independent contemporary reports, each with a verbatim
quote. `auspice labels verify` fetches every cited URL, stores the bytes in the content addressed corpus,
extracts the text, and checks the quote appears character for character. A row whose quotes do not verify is
excluded from training rather than flagged.

That check earned its place immediately. Run against the real cited sources it rejected six of twenty
citations, correctly: they were descriptions of documents rather than quotations from them. Nineteen of
twenty one now verify. The two that do not are a JavaScript rendered page with no text in its HTML, and a PDF
behind a rate limit. Both stay excluded.

## Refresh commitments

Published rather than internal, because stale data is the real outage in this business.

| Source | Refresh | Why |
|---|---|---|
| Meeting agendas | Daily | The leading indicator. An agenda tells you what is coming before any news does. |
| Minutes and vote records | Daily | Outcomes have to land fast or the ledger grades late. |
| Ordinances and moratoria | Daily | This is the retroactive kill. A rule adopted while an application is pending is the most common cause of a wrong forecast. |
| Hearing transcripts | Weekly, top counties only | Expensive and not time critical. |
| Parcel and assessor data | Monthly, or on publication | Slow moving. |
| Litigation dockets | Weekly | Slow moving. |
| Election results and filings | Per cycle, plus filing deadlines | Calendar driven and knowable in advance. |

Every score carries the date its data is current to. Beyond fourteen days a jurisdiction is flagged in the
interface and in the API response. Beyond ninety days the system abstains rather than flagging, because a
flagged number still gets pasted into a memo without the flag.

The current freshness of every source is public at `/v1/public/freshness`. It is uncomfortable to publish and
it stays.

## The source catalogue

What each class of document yields, and what it is worth. Ordered by value rather than by ease.

| Source | What it yields | Status |
|---|---|---|
| Hearing video and audio | The real reasons, spoken aloud. The minutes say "motion denied, 1 to 4"; the recording says "I can't support this until we understand what it does to the aquifer, and I've been asking for six months". The second is a transferable feature and the first is a data point. | Pipeline built, corpus not ingested |
| Meeting agendas | Upcoming applications, days before any other signal | Adapters built, ingestion not run at scale |
| Minutes | Decisions, vote tallies, conditions | Adapters built |
| Staff reports | The professional recommendation, and whether the body overruled it | Adapters built |
| Ordinances and moratoria | Rule change, which is the most common cause of a wrong forecast | Loaded by hand for the labelled set |
| Zoning codes | Use tables, setbacks, overlays, procedural steps | Not loaded |
| Vote records by member | Individual behaviour, aggregated into board composition | Not loaded. This is why the board composition features report as unknown. |
| Parcel and assessor data | Geometry, ownership, valuation | Not loaded. This is why setback compliance and distance to residential report as unknown. |
| Litigation dockets | Appeal risk and post approval delay | Not loaded |
| Interconnection queues | Grid feasibility | Not loaded |
| Election results and candidate filings | Board turnover | Derived from term rules, not from results |
| Local news | Salience, organised opposition | Not loaded at scale |

Being specific about what is not loaded matters more than listing what is. Every gap above surfaces as a
named entry in a score's missing features list, and several of them are the reason an interval is as wide as
it is.

## Legal basis

| Source type | Basis | Rules followed |
|---|---|---|
| Agendas, minutes, staff reports | Published public record | robots.txt, documented APIs preferred, polite rate limits |
| Meeting audio and video | Public broadcast under open meeting law | Audio only extraction, source URLs retained |
| Ordinances and codes | Public law | Vendor APIs where available |
| Parcel and assessor data | Public record, sometimes fee bearing | Fees paid, licence terms honoured |
| Court dockets | Public record | Jurisdiction specific terms respected |
| Anything licensed or paywalled | Only with a licence | No exceptions |

On personal data: decision makers appear in these records in their official capacity, and we record their
names, the seats they hold and how they voted, because that is the public record and it is the point. We do
not record or infer anything about them beyond it. Residents who speak at hearings are counted and their
stated grounds are categorised; they are not named in any output.

## Known gaps, stated plainly

The corpus holds one terminal decision with verified provenance. The kill test requires 400 and refuses to
report a verdict, which is what it should do.

Closing that gap has two routes and no third. Hand labelling from agendas and minutes, at roughly 30 to 60
rows a day. Or the extraction pipeline with a language model key configured, producing candidate rows that a
human confirms. The second is faster and is not a substitute, because the golden set that measures extraction
accuracy has to be made by hand.

Generating plausible looking rows would produce a kill test that passes and a company that does not work.
