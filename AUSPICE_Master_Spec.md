# AUSPICE — The Permission Risk Engine

**A complete, unabridged specification: problem, concept, product, architecture, stack, trust model, competition, economics, and build plan.**

| Field | Detail |
|---|---|
| Document version | 1.0 |
| Date | 26 August 2026 |
| Prepared for | Dipanshu Kumar |
| Status | Pre-build. **Nothing in this document has been built yet.** Every figure is sourced or explicitly labelled an assumption. |
| Build constraint | 1 person · 1 laptop · 1 month · unlimited frontier-model inference · full internet access |
| Beachhead | United States — data centre and utility-scale energy siting, top 40 counties by pipeline |
| Name | **Auspice** — from Latin *auspicium*: both official approval ("under the auspices of") and a formal reading of whether an undertaking will succeed. Selected 26 August 2026. Company-name conflict scan clean; **formal trademark search still outstanding — see §17, Q11.** |

---

## Table of contents

- [0. How to read this document](#0-how-to-read-this-document)
- [1. The thesis in one page](#1-the-thesis-in-one-page)
- [2. The problem](#2-the-problem)
- [3. How big the problem really is](#3-how-big-the-problem-really-is)
- [4. Why nobody has solved this until now](#4-why-nobody-has-solved-this-until-now)
- [5. The product](#5-the-product)
- [6. How it works — the complete pipeline](#6-how-it-works--the-complete-pipeline)
- [7. The stack](#7-the-stack)
- [8. The trust architecture](#8-the-trust-architecture)
- [9. Competition](#9-competition)
- [10. Go-to-market](#10-go-to-market)
- [11. Business model and money](#11-business-model-and-money)
- [12. The 30-day build plan, day by day](#12-the-30-day-build-plan-day-by-day)
- [13. Month 2 to month 12](#13-month-2-to-month-12)
- [14. Risks and kill criteria](#14-risks-and-kill-criteria)
- [15. Legal, ethical and regulatory](#15-legal-ethical-and-regulatory)
- [16. Metrics and instrumentation](#16-metrics-and-instrumentation)
- [17. Open questions and known unknowns](#17-open-questions-and-known-unknowns)
- [18. Sources](#18-sources)
- [19. Appendices](#19-appendices)

---

## 0. How to read this document

Three conventions are used throughout, and they matter:

1. **Sourced fact** — plain text with an institution named. Traceable to §18.
2. **[ASSUMPTION]** — my estimate. Not evidence. Must be tested before money is spent on it.
3. **[DECISION]** — a choice made in this document, with the rejected alternative stated. If you disagree, this is the line to argue with.

Where I am uncertain, I say so. Where a competitor is genuinely good, I say so. There is no claim anywhere in this document that this idea is unprecedented, because it is not — see §9.

**The three sections that actually decide whether this works:** §6.9 (the model), §8 (trust), §9.4 (durable advantage). Everything else is execution detail.

---

## 1. The thesis in one page

### 1.1 One sentence

> Auspice is a rating agency for the right to build: it produces a calibrated probability and a time distribution for whether a specific project will actually be permitted at a specific location, and it publishes its own accuracy record so the number can be trusted by a credit committee.

### 1.2 The logic chain, compressed

1. The world is in the largest physical build-out in modern history — data centres, power generation, transmission, housing, factories.
2. Every one of those projects requires **permission** from a local, discretionary, political body.
3. That permission is the **single largest cause of project failure and delay**, ahead of technology, construction and demand risk.
4. Capital markets price construction risk, technology risk, demand risk, currency risk and rate risk. **They do not price permission risk** — not because it is unimportant, but because no instrument exists to price it.
5. It is currently handled by local lawyers, relationships and gut feel: unportable, uncomparable, and impossible to underwrite.
6. The raw material to price it has always existed — ordinances, agendas, minutes, votes, dockets, hearing video — but was economically unreadable.
7. Frontier language models made reading it cheap roughly eighteen months ago. **That is the why-now.**
8. Whoever first publishes a credible, calibrated accuracy record for permission outcomes becomes the standard.
9. Standards collect a fee on every transaction that must pass through them. Title insurance, appraisal and environmental Phase I reports are all businesses created exactly this way.

### 1.3 What is being sold

Not software. Not information. **An accountable number.**

The industry already has data vendors. It does not have a rating agency. Auspice is an attempt to be the rating agency.

### 1.4 The three tests at day 30

| Test | Pass condition | If it fails |
|---|---|---|
| Does the model work? | Beats the naive base rate on held-out 2026 decisions, with a published calibration curve | **Stop on day 16.** Wedge is wrong. |
| Is the moat started? | 25 timestamped, hashed public predictions live on pending applications | Not fatal, but the clock has not started and every day of delay is unrecoverable |
| Will anyone pay? | ≥1 customer has actually transferred money | Change the buyer (lenders, not developers) before changing the product |

---

## 2. The problem

### 2.1 In plain language, no jargon

A company decides to spend $500 million on a data centre.

It hires engineers to confirm the site works. It negotiates a power agreement. It options or buys the land. It signs contractors. Then it walks into a room with five elected county commissioners — people who were not consulted, who face re-election, whose constituents are worried about water, noise, and their own electricity bills — and asks permission to rezone.

Sometimes the answer is yes in four months.
Sometimes it is no after two years.
Sometimes the county passes a moratorium halfway through and the answer becomes no **retroactively**.

**The company had no way to know the odds before it spent the money.**

That sentence is the entire business.

### 2.2 The permission stack: everyone who can say no

Most people think "permitting" is one step. It is a stack, and any single layer can kill the project. This is why the problem is hard and why nobody has assembled it.

| Layer | Who decides | Typical instrument | Failure mode |
|---|---|---|---|
| **Land control** | Private owner, or in India the state of the title itself | Option, purchase, lease | Owner walks, title is contested, encumbrance discovered |
| **Zoning / use** | Municipal or county planning body | Rezoning, special use permit, conditional use, variance, overlay | Denied, or granted with conditions that destroy the economics |
| **Legislative body** | County board, city council | Ordinance vote, comprehensive plan amendment | Political reversal after a public hearing |
| **Moratorium risk** | Same legislative body, acting pre-emptively | Temporary or permanent ban | **Retroactive kill.** The rules change under you. |
| **Utility / power** | Utility, grid operator, regulator | Load study, interconnection agreement, large-load tariff | Multi-year queue, or capacity refused outright |
| **Water** | Utility, water district, state regulator | Allocation, discharge permit | Increasingly the binding constraint, not power |
| **Environmental** | State or national agency, courts | Impact assessment, clearance, habitat rules | Years of review; litigation risk after approval |
| **Building / fire / safety** | Local departments | Building permit, occupancy | Usually procedural, occasionally weaponised |
| **Litigation** | Any objector with standing | Appeal, judicial review, injunction | Wins on procedure even when the project is sound |
| **Fiscal** | Council, state, development authority | Tax abatement, incentive agreement | Approved but uneconomic |

**[DECISION]** Auspice models the whole stack but **scores the discretionary human layers first** — zoning, legislative, moratorium, and objection risk. The grid layer is already being attacked by well-funded companies (§9.2); water and environmental come in phase two. Rationale: the human layer is the largest source of variance and the least served.

### 2.3 Anatomy of a failure — the timeline nobody models

A composite of the pattern visible in public records. **[ASSUMPTION]** on specific dollar figures; the sequence is the point.

| Month | Event | Cumulative spend at risk |
|---|---|---|
| 0 | Site identified. Broker says "county is business friendly." | $0 |
| 1 | Land optioned. Option fee + legal. | ~$0.5M |
| 3 | Engineering, environmental, geotech, power study. | ~$3M |
| 5 | Pre-application meeting. Staff is encouraging. Staff does not vote. | ~$4M |
| 7 | Rezoning filed. First public hearing. 200 residents attend. Water is the issue. | ~$5M |
| 9 | Hearing continued. Two commissioners publicly waver. | ~$6M |
| 11 | County announces a study period, then a **six-month moratorium**. | ~$7M |
| 17 | Moratorium becomes a permanent data-centre overlay ordinance with a 2,000 ft residential setback. The site no longer complies. | ~$8M |
| 18 | Project dead. Land un-sellable at the price paid because the ordinance destroyed its value. | **$8M+ written off, 18 months lost** |

**The signal was available at month 0.** The neighbouring county had passed a similar ordinance nine months earlier. Two of the five commissioners had voted against a warehouse project on water grounds in the prior term. A residents' group had already organised against a different facility. **All of that is public record. None of it was assembled.**

That gap between *publicly available* and *actually assembled* is the product.

### 2.4 The four structural breakages

#### Breakage 1 — It is invisible
The predictive information exists but is scattered across:
- tens of thousands of separate government websites,
- millions of pages of PDFs with inconsistent structure,
- tens of thousands of hours of hearing video that is never transcribed,
- court dockets on separate systems,
- local newspapers, many behind paywalls or offline,
- and the single richest source of all: **what people actually said out loud in a hearing**, which is almost never written down in the minutes.

#### Breakage 2 — It is not comparable
A developer screening 300 candidate sites cannot compare Loudoun County to Boone County to Johor, because there is no common unit of measurement. Every assessment is a bespoke human opinion produced by a different human. **You cannot rank what you cannot measure in the same units.**

#### Breakage 3 — It is not underwritable
A credit committee cannot accept "our local counsel feels good about it" as a risk input. So permission risk is not priced conservatively — **it is omitted from the model entirely**, and then absorbed as a total loss when it lands. Unpriced risk is not absent risk. It is concentrated risk.

#### Breakage 4 — It is not transferable
In several markets you legally cannot walk away from it. India's Central Electricity Regulatory Commission ruled in 2026 that land, defence and approval delays are **not** valid grounds for a developer to exit an awarded 200 MW wind project.

> **If you cannot escape a risk, you are forced to price it. And today there is nothing to price it with. That is the strongest single argument for this company's existence.**

### 2.5 Why the existing coping mechanisms fail

| Current mechanism | Why it is used | Why it fails |
|---|---|---|
| Local land-use counsel | Genuinely excellent in one familiar jurisdiction | Not portable, not comparable, cannot screen a portfolio, bills for time, and has no incentive to make itself unnecessary |
| Site-selection consultants (KPMG, CBRE, BDO) | Deep relationships, real judgement | $150K–$500K, 8–16 weeks, unrepeatable, uncalibrated, unaccountable, and cannot cover 300 sites |
| Broker assurance | Free, fast | Structurally conflicted — the broker is paid on the transaction closing |
| "We know this county" | Sometimes correct | Institutional memory of 3–5 people, invalidated by one election |
| Internal spreadsheets | Cheap | Stale within a quarter; nobody maintains them; the analyst who built it left |
| Simply accepting the loss | Requires no work | Currently costing the industry hundreds of billions — see §3 |

### 2.6 The reframe that unlocks everything

Everyone in this industry treats permission as a **process to be managed**.

It should be treated as a **risk to be priced**.

| | Process management | Risk pricing |
|---|---|---|
| Business model | Consulting, billable hours | Data monopoly, then insurance |
| Margin | Linear in headcount | Compounding, near-zero marginal cost |
| Defensibility | Relationships | A track record that cannot be back-dated |
| Ceiling | A good firm | A market standard |

Every competitor in §9 is on the left column. **[DECISION]** Auspice lives exclusively in the right column, and refuses all revenue that would drag it left — no expediting services, no lobbying, no brokerage, no "we'll help you get it approved." Those are lucrative and they destroy the asset.

---

## 3. How big the problem really is

Every figure in this section is attributed to a named institution. Nothing here is my own estimate.

### 3.1 Capital already blocked, stalled or written off

| Evidence | Figure | Source |
|---|---|---|
| US investment held back by permitting delay | **$1.5 trillion** of investment, **$1.7–2.4 trillion** of GDP; **650+ major projects** stalled in the federal permitting queue | Business Roundtable |
| US data centre projects blocked or delayed by local opposition | **$64 billion** (2024–25 count); restated in 2026 reporting as **$64–98 billion** | Data Center Watch |
| US wind and solar threatened by stalled permits | **$121 billion**; ~7 GW on federal land cancelled or stalled in 2025 | Wood Mackenzie |
| Local restrictions on US renewable siting | **395 restrictions across 41 states**; roughly **15% of US counties** effectively block wind or solar | Columbia Sabin Center; WRI; UC Law SF |
| Capacity waiting in US interconnection queues | **2,061 GW** — more than the entire existing US generation fleet | Lawrence Berkeley National Laboratory |
| Global capacity stalled in grid-connection backlogs | **~1,650 GW** | Industry / energy-transition reporting |
| India — investment impacted by land conflict | **₹12 trillion (~$140B)**; over **25% of 80 high-value projects** stalled | Rights & Resources Initiative with ISB |
| India — government's own infrastructure overrun | **₹4.92 lakh crore (~$56B)** across 1,847 monitored projects; **~36.6 months** average time overrun | MoSPI |
| India — homebuyer capital frozen | **₹10.79 lakh crore (~$120B)** across ~1,626 stalled projects, ~432,000 homes | PropEquity and industry reporting |

### 3.2 The capital arriving into that same bottleneck

The problem is not static. It is being loaded at unprecedented speed.

| Forecast | Figure | Source |
|---|---|---|
| Data centre capex to 2030 | **$3 trillion** | Dell'Oro |
| Data centre + AI infrastructure spend | **$5 trillion** | JPMorgan |
| Potential data centre investment | **$6.7 trillion** | McKinsey |
| Data centre electricity demand | **945 TWh** | International Energy Agency |
| APAC data centre asset value by 2030 | **~$1 trillion, requiring $280 billion of capex** | Cushman & Wakefield |
| APAC data centre capacity | **32 GW → 57 GW by 2030** (12% CAGR) | JLL |

Every dollar of it must pass through a local approval that nobody prices.

### 3.3 Why the published numbers understate the real loss

This matters, because it is the difference between a large market and an enormous one.

The published figures only count projects that were **announced and then visibly blocked**. They structurally cannot count:

1. **Projects never attempted** because the risk was unknowable — the largest category, and entirely invisible.
2. **Sites quietly abandoned** at the pre-application stage, which never generate a public record.
3. **Carry cost**: option payments, interest, and staff time burned during multi-year waits on projects that eventually succeed.
4. **Value destruction on land** whose permitted use was removed by ordinance after purchase.
5. **Opportunity cost of the wrong site chosen** — a project that took 26 months in County A when County B would have taken 7.
6. **Risk premium paid across the whole portfolio** because the risk cannot be discriminated site by site.

> **[ASSUMPTION]** The invisible loss is several multiples of the visible loss. I cannot prove this and neither can anyone else — which is itself evidence that the measurement layer does not exist.

### 3.4 Why it is getting worse, not better

| Force | Direction | Consequence |
|---|---|---|
| Demand for land, power and water | Rising faster than any prior infrastructure cycle | More applications chasing the same approvals |
| Local resistance | Rising — water scarcity, electricity prices, noise, and AI as a political symbol | Higher denial rates |
| Rule stability | Falling — moratoria and new overlay ordinances passed mid-process | Retroactive kills; forecasts must model rule change, not just current rules |
| Approval capacity | Flat | There are not more planners, hearings or court days than last year |
| Political salience | Rising — data centres became a local election issue in multiple countries in 2026 | Decisions increasingly driven by electoral calendars, which are knowable in advance |

That last row is important and under-appreciated: **the more political this becomes, the more predictable it becomes**, because electoral incentives are public and documented. Politicisation is bad for developers and good for a forecasting business.

### 3.5 Where the problem exists: the four-region comparison

This is a **worldwide** problem. It appears wherever three conditions overlap: abundant capital, contested land, and discretionary local approval. But the *shape* differs, and shape dictates sequencing.

#### United States — permission is slow and political
- ~**33,000** general-purpose local governments, each with real veto power and its own code.
- Only about **20%** of American zoning has ever been standardised into comparable data (National Zoning Atlas), out of an estimated 740,000 pages.
- The answer is knowable. Nobody has assembled it.

#### Europe and the UK — slow, litigated, but reformable
- Onshore wind consent historically **5–10 years**.
- The EU legally capped renewable permitting at **2 years** (3 for offshore) and is now **referring member states to the Court of Justice with financial sanctions** for failing to implement it.
- Germany proved the constraint is legal, not physical: after introducing an "overriding public interest" presumption it permitted **15 GW of onshore wind in 2024 — seven times its rate five years earlier** (WindEurope).
- UK: reserved-matters approvals run **12–18 months**; completions outside the fifty largest housebuilders fell **16% year on year** to Q1 2026.

#### Asia excluding India — the rules are being written this year
This is the strongest "why now" evidence in the entire document, because these events are months old.

| Market | What happened |
|---|---|
| **Malaysia / Johor** | Absorbed ~**$35 billion** after Singapore's 2019–22 moratorium; planned an **8× capacity increase to 7,000 MW**; saw its **first data-centre protests in February 2026**; in March the state premier said there would be **no approvals for high-water-demand facilities**. A 50 MW facility uses the water of ~2,200 households and the power of ~22,000 (Bank Negara). |
| **South Korea** | **All 25 Seoul district heads petitioned unanimously** for tighter data-centre rules in August 2026. Geumcheon-gu now requires **majority consent of residents within 200 metres**. Yeongdeungpo, Incheon and Gwacheon are imposing separation distances. **There is no national guideline**, so the regime is a patchwork and in-flight projects can restart from zero. Data-centre opposition became a local-election issue in June 2026. |
| **Japan** | Rising urban opposition; data centres are still classified as **"offices" rather than industrial** under outdated zoning; in March 2026 residents **sued the private company that issued a building permit**. |
| **Singapore** | The original precedent. Its 2019–22 moratorium proved permission scarcity does not destroy capital — **it relocates it across a border**. Which means permission is a map, and maps are products. |

#### India — the largest version of the problem, and a different one

> In the United States you do not know whether you will be **allowed** to build.
> In India you often do not know who **owns** the land.

| Indicator | Reality | Source |
|---|---|---|
| Share of civil litigation | Land and property disputes are roughly **66% of all civil cases** | Supreme Court of India; Centre for Policy Research; DAKSH |
| Time to resolve | **~20 years** average for a land or real-estate dispute | NITI Aayog |
| Court backlog context | 4,87,54,355 cases pending in district courts, of which 1,10,68,892 civil (April 2026) | National Judicial Data Grid |
| Investment exposed | **₹12 trillion** impacted; >25% of 80 high-value projects stalled | RRI / ISB |
| Government's own projects | **₹4.92 lakh crore** overrun; stated causes are literally *land acquisition, forest and environment clearances, technical approval, encroachment* | MoSPI |
| Housing | **₹10.79 lakh crore** frozen; PropEquity counts ~2,000 stalled projects and 5.08 lakh units across 42 cities; NCR alone 240,610 units worth ₹1.81 lakh crore | Industry / PropEquity |
| Renewables | Stranded renewable projects **doubled past 50 GW**; 147 GW of connectivity granted but 3–5 years to operate; Great Indian Bustard zones push Rajasthan timelines to **48 months** | Industry reporting |
| Data centres | Over **$100 billion announced**; ASSOCHAM–PwC (May 2026) names **bureaucratic land and power approval delays** as a key bottleneck; power sanction alone ~18 months; build cost ₹44–54 crore per MW | ASSOCHAM–PwC; Axis Capital |
| Governance | "The future of data centres in India is decided locally" — state governments described as **the new kingmakers** | DatacenterDynamics |
| **Land records — the hidden gap** | Government claims **95%** of rural records digitised. But mutation is computerised at only **47%**, digitally signed titles at **28%**, cadastral maps at **46%** | PIB; PRS Legislative Research |

> **The single most important observation about India:** the country scanned the paper without resolving the ownership. A digitised record of a contested title is still a contested title. **The gap between "digitised" and "conclusive" is the product opportunity — and the buyer is not the developer, it is the lender.**

### 3.6 Direct comparison and the resulting order of attack

| Dimension | United States | Europe / UK | Asia ex-India | India |
|---|---|---|---|---|
| Nature of the problem | Slow, politically unpredictable | Slow, litigated, legally capped | Rules not yet written | Title itself is contested |
| Data availability | Public, English, semi-structured | Good, but 27 legal regimes | Fragmented, non-English, low volume | Scanned, multilingual, contested, partly offline |
| Jurisdictions to cover | ~33,000 — hardest | Thousands | **Dozens — easiest** | Hardest of all |
| Willingness to pay per answer | **Highest** — USD, institutional | High | High — same hyperscaler buyers | Low per unit, enormous volume |
| Time to a working product | ~30 days for one vertical | 3–6 months | ~45 days | 6–12 months |
| Existing competition | Real but adjacent (§9) | Fragmented | Effectively none | None on prediction |
| Legal risk of publishing opinions | Manageable | Manageable | Manageable | Higher — defamation and land-mafia exposure |
| **Auspice** | **Start here** — funds everything, proves calibration | Third | **Second** — fastest route to owning an entire country | **Biggest prize, enter third, via lenders** |

**Sequencing logic, stated plainly:**

1. **US first.** The data is public and in English, and the buyers pay in dollars. This funds everything and produces the calibration record that makes every later market possible.
2. **Korea, Malaysia, Japan second.** A country with only dozens of relevant jurisdictions can be **completely covered by one person in a month**, the rules are being written right now so there is no incumbent, and the buyers are the same hyperscalers already met in step one.
3. **India third**, funded by the first two, entered through **banks and title risk rather than zoning** — because in India the party with money, urgency and a legal obligation to quantify risk is the lender, not the developer.

---

## 4. Why nobody has solved this until now

This section exists because the first question any serious investor or customer asks is: *if this is so obvious and so valuable, why does it not exist?* There are five real answers.

### 4.1 The data was economically unreadable

The signal lives in millions of pages of ordinances, staff reports and minutes, plus tens of thousands of hours of hearing video, across thousands of separate websites, using **different vocabulary for identical concepts**. One county says "special use permit," the next says "conditional use," the third says "discretionary review."

Normalising that by hand cost more than the answer was worth. Frontier language models changed that cost by two to three orders of magnitude, and only recently. **This is the whole why-now, and it has a shelf life.**

### 4.2 The value was far lower before the capital wave

A calibrated permission forecast in 2015 was an interesting academic paper. In 2026, when a single blocked site can cost $40 million in sunk cost and 18 months, it is a budget line item. The problem got valuable and the solution got cheap **in the same 24-month window**. That intersection is the opportunity.

### 4.3 The incumbents are structurally misaligned

| Incumbent | Why they will not build this |
|---|---|
| Land-use lawyers | A tool that answers in nine seconds destroys the billable hour |
| Site-selection consultants | Their product *is* the bespoke opinion; commoditising it destroys their pricing |
| Brokers | Paid on transaction close — a tool that says "do not buy this" is against their interest |
| Data vendors | Sell completeness, not accountability. **Publishing an accuracy score is pure downside for them** — it creates a liability and invites comparison |
| Government | Has the data, no mandate to forecast, and a strong institutional reason never to predict its own decisions |

That fourth row is the most important line in this section. **The reason the trust mechanism in §8 is available is that it is irrational for an incumbent to adopt it.**

### 4.4 It looks unglamorous

Reading county planning minutes and transcribing three-hour zoning hearings is the least fashionable work in technology. That is precisely why the corpus is unclaimed. **Defensibility usually hides inside tedium.** Ambitious teams chase the model layer, where there is no moat, and ignore the data layer, where all of it is.

### 4.5 The correct statistical method is awkward

Most jurisdictions have only a handful of relevant historical decisions — often three to eight. Naive machine learning fails badly on that, produces embarrassing results, and most teams conclude the problem is unsolvable and stop.

The correct answer is a **hierarchical model with partial pooling**: borrow strength from similar jurisdictions, shrink toward the group mean where local data is thin, and report honest uncertainty. This is standard statistics and rare in this industry. Full treatment in §6.9. **This is the single most defensible technical decision in the document.**

### 4.6 The consequence

The window is open because the enabling technology is new, the value is newly enormous, the natural owners are conflicted, the work is unglamorous, and the correct method is unfashionable.

**None of those five conditions is permanent.** That is the argument for building it in thirty days rather than thirty weeks.

---

## 5. The product

### 5.1 The direct answer: what is this thing?

> **It is not an app. It is a data asset with a prediction layer on top and three thin delivery surfaces.**

This distinction is not philosophical. It determines whether the company survives.

- If you build this as **an app**, you have built something a funded competitor can clone in a weekend.
- If you build it as a **dataset with a public accuracy record**, you have built something that cannot be caught up to, because the record is time-locked.

The website is a window. The window is not the building.

### 5.2 The four layers, in order of importance

| # | Layer | What it is | Why it matters | Copyable? |
|---|---|---|---|---|
| **1** | **The Permission Graph** | A structured database of every body that can say no, every decision it has made, and the reasoning behind it | **This is the company.** It compounds daily and cannot be back-dated. | No |
| **2** | **The prediction layer** | Calibrated probability of approval + a distribution of time-to-decision | Converts an archive into a decision instrument | Method yes, calibration record no |
| **3** | **The delivery surfaces** | Web app, API, generated PDF memo, alert stream | Thin, replaceable, cheap. **Deliberately not the moat.** | Yes, in a weekend |
| **4** | **The risk product** | Warranty, then parametric insurance on permission delay | Year 2–3. Only possible once calibration is proven. Converts software revenue into a balance sheet. | No — requires the record |

**[DECISION]** Engineering effort is allocated roughly 60% layer 1, 25% layer 2, 15% layer 3. Most teams invert this and die. The temptation to polish the interface must be actively resisted for the first ninety days.

### 5.3 How people actually access it

Four access surfaces, in the order a customer typically encounters them.

#### (a) Website — a browser-based web application
The primary human surface. **No download, no install, no mobile app.** Log in at `app.<domain>`, search a parcel or address, get a score.

Why web and not native: the users are analysts sitting at desks with two monitors, working in spreadsheets and GIS tools. They are not on phones. A mobile app would be a vanity project. **[DECISION]** The site is fully responsive so a phone works for reading alerts, but no native app is ever built.

#### (b) API — for other companies' software
A REST + JSON API so lenders, brokerages, site-selection platforms and grid-analytics companies can pull scores into their own systems. This is the highest-margin revenue line and it makes Auspice **infrastructure** rather than a tool.

#### (c) The PDF memo — for the investment committee
The most underrated surface. The buyer's real job is not "understand risk" — it is **defend a decision to a committee**. A clean, sourced, dated document that goes into a deal file is what actually gets paid for.

> Sell the artefact, not the dashboard.

#### (d) The alert stream — email, Slack, and webhook
When a county adopts a moratorium, a board member is replaced, or a comparable application is denied nearby, every affected site in every customer's portfolio is re-scored and an alert fires. **This is what converts a one-off report into a subscription.** Without monitoring there is no recurring revenue.

#### Access summary

| Surface | Who uses it | Technology | Pricing tie |
|---|---|---|---|
| Web application | Analysts, developers, brokers | Browser, responsive | Subscription |
| REST API | Partner engineering teams | HTTPS + JSON, API key | Licence |
| PDF memo | Investment committees, credit committees | Generated document | Per-site fee |
| Alerts | Everyone | Email, Slack, webhook | Included in subscription |
| Public accuracy page | Anyone, no login | Public website | Free — it is the marketing |

That last row is deliberate. **The single most important page on the website is public and free**: the live accuracy record. It is simultaneously the product proof, the marketing engine, and the moat.

### 5.4 The five things a customer can buy

#### Product 1 — Site Score
Input: address, parcel ID, or uploaded polygon, plus a use type and size.
Output: the full score object (§5.6).
Job it does: *should I spend money on this site at all?*

#### Product 2 — Portfolio Screen
Input: a CSV or shapefile of up to 500 candidate sites.
Output: every site scored and ranked, with a downloadable comparison table and a map.
Job it does: *which 12 of these 300 sites deserve a human being's attention?*
**This is the wedge feature.** No lawyer or consultant can do this at any price, which is why the sales conversation should always start here rather than with a single site.

#### Product 3 — Monitor
Input: sites you care about.
Output: continuous re-scoring plus alerts on ordinance changes, moratoria, board turnover, comparable denials nearby, and litigation filings.
Job it does: *tell me before my deal breaks, not after.*

#### Product 4 — Permission Memo
Output: a 6–12 page generated PDF: score, method, drivers, precedent decisions with citations, timeline distribution, named risks, mitigations, alternatives, and an explicit uncertainty statement.
Job it does: *let me defend this decision to my committee, in writing, with sources.*

#### Product 5 — API and bulk data licence
Output: programmatic scores, jurisdiction profiles, ordinance change feeds.
Job it does: *embed permission risk into our own underwriting or platform.*

### 5.5 Who buys, and what they are actually buying

| Persona | Their real job | What they buy | What they will pay | Urgency |
|---|---|---|---|---|
| **Data centre site-selection lead** | Find 5 buildable sites out of 300 candidates | Portfolio Screen | $2K–8K/mo | **Very high** |
| **Renewables development manager** | Kill bad sites before spending on interconnection | Site Score + Monitor | $2K–5K/mo | High |
| **Project finance / credit officer at a lender** | Not lend against a site that will never be permitted | Permission Memo per deal | Per-deal fee, mandated | **Highest strategic value** |
| **Real estate PE / infrastructure fund** | Diligence an acquisition or a JV | Memo + API | $50K–200K/yr | Medium |
| **Land brokerage** | Prove a listing is buildable, close faster | API embedded in listings | Licence | Medium |
| **Grid-analytics company (e.g. a GridCare or Verse type)** | Add the political layer to their grid layer | API | $200K+/yr | Medium–high |
| **Insurer / MGA** | Underwrite a delay product | Model access + record | Premium share | Year 2–3 |
| **County or community group** | Understand what is coming | Free or near-free tier | $0 | Low revenue, **high neutrality value** |

**[DECISION]** That last row is unprofitable and non-negotiable. Selling the same data to counties and community groups at zero cost is the defence against the single largest reputational risk in this business (§15.3). It also produces the best data-quality feedback in the system, for free.

### 5.6 The output object — exactly what a score contains

This is the core deliverable. Every field is specified because vagueness here is what makes a product untrustworthy.

```json
{
  "site": {
    "parcel_ids": ["0123-45-678"],
    "jurisdiction_chain": [
      {"level": "county", "name": "...", "role": "primary_decider"},
      {"level": "state_agency", "name": "...", "role": "clearance"},
      {"level": "utility", "name": "...", "role": "load_approval"}
    ],
    "use_class": "data_center_hyperscale",
    "requested_relief": "rezoning + special_use_permit",
    "by_right": false
  },
  "determination": {
    "approval_probability": 0.34,
    "credible_interval_80": [0.25, 0.44],
    "confidence": "medium",
    "abstained": false,
    "time_to_decision_months": {"p10": 8, "p50": 14, "p90": 27},
    "probability_of_rule_change_before_decision": 0.22
  },
  "drivers": [
    {"factor": "recent_overlay_ordinance", "direction": "negative", "weight": 0.31,
     "evidence_id": "ord_2026_0412", "plain_language": "County adopted a data centre overlay 4 months ago with a 2,000 ft residential setback."},
    {"factor": "comparable_denials", "direction": "negative", "weight": 0.24,
     "evidence_id": "app_2025_0881", "plain_language": "3 of the last 4 comparable applications were denied."},
    {"factor": "election_proximity", "direction": "negative", "weight": 0.15,
     "plain_language": "2 of 5 board seats face election in 8 months."},
    {"factor": "groundwater_salience", "direction": "negative", "weight": 0.12,
     "plain_language": "Groundwater raised by residents in 3 of the last 5 hearings."}
  ],
  "precedents": [
    {"application_id": "app_2025_0881", "similarity": 0.88, "outcome": "denied",
     "vote": "1-4", "months_to_decision": 11,
     "citation": {"doc": "minutes_2025_09_14.pdf", "page": 7, "quote": "..."}}
  ],
  "mitigations": [
    {"action": "Relocate to comply with the 2,000 ft setback", "expected_delta": "+0.19"},
    {"action": "Pre-file a groundwater impact study", "expected_delta": "+0.06"}
  ],
  "alternatives": [
    {"jurisdiction": "...", "distance_km": 31, "by_right": true, "score": 0.81},
    {"jurisdiction": "...", "distance_km": 44, "by_right": false, "score": 0.76}
  ],
  "provenance": {
    "model_version": "v0.4.1",
    "data_as_of": "2026-08-24",
    "documents_used": 47,
    "jurisdiction_data_depth": "8 comparable decisions since 2019",
    "pooled": true,
    "pooling_note": "Local data thin; strength borrowed from 6 similar jurisdictions."
  }
}
```

**Five design rules embedded in that object, each one deliberate:**

1. **A credible interval is always shown.** A bare point estimate is a lie.
2. **`abstained` is a first-class field.** The system is allowed to refuse. See §8.4.
3. **Every driver carries an `evidence_id`.** No unsourced claim reaches the customer.
4. **`pooling_note` is disclosed.** If the answer partly comes from other jurisdictions, the customer is told. This is uncomfortable and it is what makes the number credible.
5. **`alternatives` exists.** This is where the customer saves $40 million, and it is the field they will renew for.

### 5.7 The screens, in build order

| Order | Screen | Purpose | Build day |
|---|---|---|---|
| 1 | **Public accuracy page** | The moat, and the marketing. Live reliability curve, Brier score, prediction ledger, misses log. No login. | 25 |
| 2 | **Site search → score** | Single-site flow: enter address, pick use class, get the score object rendered | 21 |
| 3 | **Portfolio upload** | CSV or shapefile in, ranked table out, map view, CSV export | 22 |
| 4 | **Evidence drawer** | Click any driver → see the source document, page, and highlighted quote | 22 |
| 5 | **Memo generator** | One button → PDF | 23 |
| 6 | **Jurisdiction profile** | Base rates, discretion index, board composition, ordinance history timeline | 24 |
| 7 | **Monitor / alerts** | Watchlist, alert history, notification settings | Month 2 |
| 8 | **Admin and billing** | Deferred — invoice manually for the first ~20 customers | Month 3 |

**[DECISION]** The public accuracy page is built **first among the screens** despite generating zero revenue, because it is the only screen a competitor cannot replicate.

### 5.8 What the product explicitly is not

| Not this | Why not |
|---|---|
| Legal advice | It is a probabilistic opinion with disclosed methodology. This distinction is a legal necessity, not marketing. See §15.1. |
| A lobbying or expediting service | Auspice never advocates for a project. Neutrality is the asset; selling advocacy destroys it permanently. |
| A brokerage or developer | No land positions, ever. The moment we have a side, the number is worthless. |
| A chatbot over documents | A system that always answers confidently is the exact opposite of what this market needs. |
| A permit-tracking workflow tool | That is a crowded, low-margin category. We forecast; we do not manage tasks. |
| A mobile app | The users are analysts at desks. |
| A government product | Selling to government means procurement cycles measured in years. Give it to them free, sell to capital. |

---

## 6. How it works — the complete pipeline

Eleven stages. Each is independently testable, which is the only reason one person can build this in a month.

```
[0] Jurisdiction registry
     ↓
[1] Ingestion  ────────────────────→ [raw object store, immutable, forever]
     ↓
[2] Document processing / OCR
     ↓
[3] Audio + video transcription
     ↓
[4] LLM extraction → strict schema  (every fact carries a source span)
     ↓
[5] Entity resolution
     ↓
[6] The Permission Graph  (PostgreSQL + PostGIS)
     ↓
[7] Feature engineering
     ↓
[8] Modelling: hierarchical classifier + survival model
     ↓
[9] Calibration + evaluation  ──→ [public accuracy page]
     ↓
[10] Output generation: score, evidence, memo, alternatives
     ↓
[11] Monitoring + re-scoring ──→ [alerts]
```

### 6.0 Stage 0 — Jurisdiction registry

**Purpose:** answer the deceptively hard question *"who actually decides for this parcel?"*

Almost nobody has this cleanly, and everything downstream is worthless without it.

What it contains per jurisdiction:
- Name, type (county / municipality / township / special district / state agency / utility / grid operator), FIPS or equivalent code.
- **Boundary geometry** (PostGIS polygon) so a parcel can be resolved to a jurisdiction chain by spatial join.
- Governing legal framework — in the US, critically, whether the state is **Dillon's Rule or home rule**, which determines how much power a locality actually has.
- The decision bodies within it, their composition, quorum rules, meeting cadence, and **election calendar**.
- The document sources for that jurisdiction (§6.1) and the civic platform vendor it uses.
- Data-depth counter: how many usable historical decisions we hold. Drives the abstention rule in §8.4.

**[DECISION]** Build the registry by hand for 40 counties before writing a single scraper. Three days of manual work that prevents three weeks of building pipelines into the wrong places.

### 6.1 Stage 1 — Ingestion

#### The source catalogue

| Source | What it yields | Access pattern | Priority |
|---|---|---|---|
| Zoning ordinance / municipal code | Use tables, setbacks, overlays, definitions, procedural steps | Code-hosting vendors (Municode, American Legal, Code Publishing) or PDF | **P0** |
| Comprehensive / general plan | Stated intent, future land use map | PDF | P1 |
| Meeting agendas | Upcoming applications — **the leading indicator** | Civic platform | **P0** |
| Minutes | Decisions, vote tallies, conditions | Civic platform, PDF | **P0** |
| Staff reports | The professional recommendation, and whether the body overruled it | Civic platform, PDF | **P0** |
| Vote records | Individual member behaviour | Minutes, sometimes structured | **P0** |
| **Hearing video / audio** | The real reasons, spoken aloud | Granicus, YouTube, Vimeo, Legistar media | **P0 — the differentiator** |
| Ordinance amendments / moratoria | Rule change — the most common cause of a wrong forecast | Council agendas, legal notices | **P0** |
| Permit records | Downstream confirmation, build timelines | County portals, Accela, or a vendor | P1 |
| Litigation dockets | Appeal risk, post-approval delay | Court systems, PACER-type sources | P1 |
| Interconnection queues / hosting capacity | Grid feasibility | Grid operator and utility publications | P1 |
| Election results and candidate filings | Board composition change | State/county election offices | P1 |
| Local news | Salience, organised opposition, sentiment | RSS, search, archives | P2 |
| Parcel and assessor data | Geometry, ownership, valuation | County GIS / open data / vendor | **P0** |

#### The civic-platform insight

This is the highest-leverage engineering observation in the document.

US local government does not have 33,000 different websites. It has **a small number of software vendors** — predominantly **Legistar/Granicus, CivicPlus, Accela, OpenGov, and Municode-class code hosts** — reselling the same platform to thousands of jurisdictions.

> **[DECISION]** Build **five to seven excellent platform adapters** rather than ten thousand bad site-specific scrapers. One adapter unlocks hundreds or thousands of jurisdictions at once. This single decision is what makes a one-month build physically possible.

Each adapter is structured identically:

```python
class CivicAdapter(Protocol):
    platform: str
    def discover(self, jurisdiction: Jurisdiction) -> list[SourceRef]: ...
    def fetch(self, ref: SourceRef) -> RawDocument: ...   # bytes + response headers
    def enumerate_meetings(self, since: date) -> Iterator[MeetingRef]: ...
    def media_url(self, meeting: MeetingRef) -> str | None: ...
```

#### Ingestion engineering rules

1. **Content-addressed, immutable raw store.** Every fetched byte stream saved to object storage under its SHA-256 hash, with a sidecar JSON of URL, fetch time, HTTP headers and jurisdiction. **Never overwrite. Never delete.**
2. **Politeness and legality.** Respect `robots.txt`, rate-limit per host, identify the crawler honestly with a contact address, and cache aggressively. These are public records, but behaving like a hostile scraper is how access gets cut.
3. **Idempotent re-fetch.** Same URL, unchanged content hash → no new work downstream.
4. **Change detection is a product feature, not plumbing.** The diff between yesterday's ordinance and today's *is* the alert in §6.11.
5. **Failure is normal.** Government sites go down constantly. Retry with exponential backoff, keep a dead-letter queue, and surface source freshness on a dashboard — stale data is the real outage in this business.

### 6.2 Stage 2 — Document processing

A deliberate cost-ordered cascade. Never send a document to an expensive model if a cheap deterministic tool can read it.

| Step | Tool | Handles |
|---|---|---|
| 1 | `pymupdf` (fitz) | Digital-native PDFs — the majority. Fast, free, exact. |
| 2 | `pdfplumber` | Table extraction where layout matters (use tables, setback schedules) |
| 3 | `tesseract` via `pytesseract` | Scanned documents |
| 4 | Layout-aware model / vision model | Only when 1–3 produce garbage: complex tables, stamped maps, handwriting |

**Quality gate:** every extracted page gets a heuristic legibility score (character density, dictionary-word ratio, expected-token presence). Below threshold → escalate to the next step. Log the escalation rate per jurisdiction; a sudden rise means a source changed format.

**Chunking:** documents are split on structural boundaries (section headings, agenda items, motion blocks) rather than fixed token counts. Every chunk retains `document_id`, `page`, `char_start`, `char_end` — **this is what makes citation possible later**, and it is not retrofittable.

### 6.3 Stage 3 — Audio and video transcription

> **This is the single most underexploited input in this market. Nobody is systematically mining hearing video, and the decisive reasoning is spoken there and never written down.**

Pipeline:
1. Discover the media URL from the meeting record.
2. Download audio only (`ffmpeg -vn -ac 1 -ar 16000`) — video is 50–100× larger and adds nothing.
3. Transcribe with a Whisper-class model, **with word-level timestamps and speaker diarisation**.
4. Align transcript segments to agenda items using timestamps plus the agenda structure.
5. Store the transcript as a first-class document with the same provenance fields, so a quote can be cited as *"Commissioner X, 1:47:22, 14 September 2025 hearing."*

**Why it matters concretely:** the minutes say *"Motion denied, 1–4."* The video says *"I can't support this until we understand what it does to the aquifer, and I've been asking for six months."* The second sentence is a **transferable, generalisable feature** — it predicts the next four decisions in that county and possibly the neighbouring one. The first is a data point.

**Cost control:** transcribe only the top ~10 counties initially, and only agenda items matching the target use class. **[ASSUMPTION]** a three-hour meeting is roughly 20–40 minutes of relevant audio.

### 6.4 Stage 4 — LLM extraction into a strict schema

**[DECISION]** Extraction uses **schema-enforced structured output**, never free text that is parsed afterwards. Free-text parsing is where data pipelines go to die.

Example target schema for a decision event:

```json
{
  "type": "object",
  "required": ["event_type", "jurisdiction_ref", "decided_on", "outcome", "evidence"],
  "properties": {
    "event_type": {"enum": ["application_filed","hearing_held","decision_rendered",
                             "ordinance_adopted","moratorium_enacted","appeal_filed"]},
    "jurisdiction_ref": {"type": "string"},
    "body": {"enum": ["planning_commission","board_of_supervisors","city_council",
                       "zoning_board","other"]},
    "applicant": {"type": ["string","null"]},
    "use_class": {"type": ["string","null"]},
    "relief_sought": {"type": "array", "items": {"type": "string"}},
    "decided_on": {"type": ["string","null"], "format": "date"},
    "outcome": {"enum": ["approved","approved_with_conditions","denied",
                          "withdrawn","continued","tabled","pending","unknown"]},
    "vote": {"type": ["string","null"], "pattern": "^[0-9]+-[0-9]+(-[0-9]+)?$"},
    "conditions": {"type": "array", "items": {"type": "string"}},
    "objection_grounds": {"type": "array",
      "items": {"enum": ["water","noise","traffic","electricity_cost","property_value",
                          "visual","environmental","process","tax","other"]}},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "evidence": {
      "type": "array", "minItems": 1,
      "items": {"type": "object",
        "required": ["document_id","page","quote"],
        "properties": {
          "document_id": {"type": "string"},
          "page": {"type": "integer"},
          "char_start": {"type": "integer"},
          "quote": {"type": "string", "maxLength": 500}
        }}}
  }
}
```

**The five extraction rules:**

1. **`evidence` has `minItems: 1`.** A fact with no source is rejected by the schema, not by a code review. Make correctness structural.
2. **The model must quote, not paraphrase.** Every quote is then verified programmatically against the stored source text. If the quote is not found verbatim in the document, the extraction is discarded and retried. **This eliminates hallucinated citations mechanically rather than by trust.**
3. **Two-pass extraction on high-value documents.** Pass 1 extracts. Pass 2, with a different prompt and temperature 0, verifies. Disagreement → human review queue.
4. **`unknown` and `null` are always valid.** The model is explicitly instructed that guessing is a failure. Missing data is cheap; wrong data poisons the model.
5. **Everything is cached by content hash + prompt version.** Re-processing 400,000 pages because a prompt changed must cost nothing when the prompt did not change.

**Model tiering for cost:**

| Task | Model class | Why |
|---|---|---|
| Triage: is this document relevant at all? | Small, cheap | 90% of volume, trivial task |
| Classification: use class, objection grounds | Small, cheap | High volume, closed label set |
| Structured extraction of decisions | **Frontier** | Accuracy here determines everything downstream |
| Reasoning over conflicting evidence | **Frontier** | Rare, high value |
| Plain-language explanation for the customer | Mid | Prose quality matters, facts already fixed |

### 6.5 Stage 5 — Entity resolution

The unglamorous stage that decides whether the graph is real or garbage.

Problems to solve:
- "Loudoun County Board of Supervisors" vs "Loudoun Co. BOS" vs "the Board" → one entity.
- The same applicant behind six different single-purpose LLCs → **beneficial-owner clustering.** Very high value: applicant identity is genuinely predictive, and developers deliberately obscure it.
- Parcels that split, merge, or get renumbered between assessment years.
- A commissioner who appears as "J. Smith", "Jane Smith" and "Supervisor Smith", across two non-consecutive terms.

Method: blocking on jurisdiction + type, then `pg_trgm` similarity, then embedding similarity via `pgvector`, then an LLM adjudication only on the ambiguous middle band. Every merge is recorded in an audit table and is reversible. **Never destroy the original strings.**

### 6.6 Stage 6 — The Permission Graph

Everything defensible is here. The graph is not a technical preference; it is the only structure in which **precedent becomes computable**.

#### Core schema (abridged DDL)

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- WHO CAN SAY NO
CREATE TABLE jurisdiction (
  id              bigserial PRIMARY KEY,
  name            text NOT NULL,
  kind            text NOT NULL,          -- county|municipality|special_district|agency|utility
  country          text NOT NULL,
  admin_codes     jsonb NOT NULL DEFAULT '{}',
  home_rule       boolean,                -- Dillon's Rule vs home rule: real predictive power
  boundary        geometry(MultiPolygon, 4326) NOT NULL,
  civic_platform  text,
  discretion_index numeric,               -- 0 = fully by-right, 1 = fully discretionary
  data_depth      integer NOT NULL DEFAULT 0,
  UNIQUE (country, kind, name)
);
CREATE INDEX ON jurisdiction USING GIST (boundary);

CREATE TABLE decision_body (
  id              bigserial PRIMARY KEY,
  jurisdiction_id bigint NOT NULL REFERENCES jurisdiction(id),
  name            text NOT NULL,
  kind            text NOT NULL,
  seats           integer,
  quorum          integer,
  meeting_cadence text
);

CREATE TABLE decision_maker (
  id              bigserial PRIMARY KEY,
  body_id         bigint NOT NULL REFERENCES decision_body(id),
  display_name    text NOT NULL,
  name_variants   text[] NOT NULL DEFAULT '{}',
  term_start      date,
  term_end        date,                   -- election proximity is a live feature
  seat_label      text
);

-- THE RULES, AND HOW THEY CHANGE
CREATE TABLE instrument (                 -- ordinance, overlay, plan, moratorium
  id              bigserial PRIMARY KEY,
  jurisdiction_id bigint NOT NULL REFERENCES jurisdiction(id),
  kind            text NOT NULL,
  citation        text,
  adopted_on      date,
  effective_on    date,
  expires_on      date,                   -- moratoria expire; that date is a feature
  supersedes_id   bigint REFERENCES instrument(id),
  restrictions    jsonb NOT NULL DEFAULT '{}',  -- setbacks, height, noise, water caps
  full_text_ref   text
);

-- THE LAND
CREATE TABLE parcel (
  id              bigserial PRIMARY KEY,
  jurisdiction_id bigint REFERENCES jurisdiction(id),
  external_id     text,
  geom            geometry(MultiPolygon, 4326) NOT NULL,
  acres           numeric,
  current_zoning  text,
  overlays        text[] NOT NULL DEFAULT '{}',
  owner_raw       text,
  owner_cluster_id bigint,
  valid_from      date, valid_to date     -- parcels split and merge; keep history
);
CREATE INDEX ON parcel USING GIST (geom);

-- THE ASK, AND WHAT HAPPENED
CREATE TABLE application (
  id              bigserial PRIMARY KEY,
  jurisdiction_id bigint NOT NULL REFERENCES jurisdiction(id),
  body_id         bigint REFERENCES decision_body(id),
  applicant_cluster_id bigint,
  use_class       text NOT NULL,
  relief_sought   text[] NOT NULL,
  capacity_mw     numeric,
  acres           numeric,
  filed_on        date,
  decided_on      date,
  outcome         text,                   -- approved|approved_with_conditions|denied|withdrawn|pending
  vote_for        integer, vote_against integer, vote_abstain integer,
  conditions      jsonb,
  months_to_decision numeric GENERATED ALWAYS AS
      (CASE WHEN decided_on IS NOT NULL AND filed_on IS NOT NULL
            THEN (decided_on - filed_on)/30.44 END) STORED,
  censored        boolean NOT NULL DEFAULT false  -- still pending = right-censored
);

CREATE TABLE vote (
  application_id  bigint NOT NULL REFERENCES application(id),
  maker_id        bigint NOT NULL REFERENCES decision_maker(id),
  position        text NOT NULL,          -- for|against|abstain|absent
  PRIMARY KEY (application_id, maker_id)
);

CREATE TABLE objection (
  id              bigserial PRIMARY KEY,
  application_id  bigint REFERENCES application(id),
  jurisdiction_id bigint REFERENCES jurisdiction(id),
  organised       boolean,
  group_name      text,
  grounds         text[] NOT NULL,
  speakers        integer,
  media_mentions  integer
);

-- PROVENANCE: NON-NEGOTIABLE
CREATE TABLE document (
  id              text PRIMARY KEY,       -- sha256 of raw bytes
  jurisdiction_id bigint REFERENCES jurisdiction(id),
  kind            text NOT NULL,          -- agenda|minutes|staff_report|ordinance|transcript|docket
  source_url      text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  published_on    date,
  storage_key     text NOT NULL,
  page_count      integer,
  embedding       vector(1536)
);

CREATE TABLE fact_evidence (
  id              bigserial PRIMARY KEY,
  subject_table   text NOT NULL,
  subject_id      bigint NOT NULL,
  field           text,
  document_id     text NOT NULL REFERENCES document(id),
  page            integer,
  char_start      integer, char_end integer,
  quote           text NOT NULL,
  extractor_version text NOT NULL,
  verified        boolean NOT NULL DEFAULT false  -- quote found verbatim in source
);

-- PRECEDENT: THE ENGINE
CREATE TABLE precedent_link (
  a_id            bigint NOT NULL REFERENCES application(id),
  b_id            bigint NOT NULL REFERENCES application(id),
  similarity      numeric NOT NULL,
  basis           jsonb NOT NULL,         -- which dimensions matched
  PRIMARY KEY (a_id, b_id)
);
```

#### The relationships that generate the value

| Relationship | Why it is worth money |
|---|---|
| jurisdiction **has authority over** parcel | Resolves "who actually decides" — harder than it sounds, and wrong answers here invalidate everything |
| decision_maker **voted on** application | Turns an anonymous institution into named, modelled behaviour |
| instrument **supersedes** instrument | Lets the system know the rules changed last month — **the most common cause of a wrong forecast** |
| application **is comparable to** application | The precedent engine. Converts an assertion into a justification. |
| objection **appeared in** jurisdiction | Detects contagion — opposition spreads between neighbouring counties faster than policy does |
| applicant_cluster **applied in** jurisdiction | Some applicants get approved and some do not, consistently |

#### Three non-negotiable data rules

1. **Never discard a raw document.** Extraction methods improve; the corpus is only re-processable if you kept it. **This is the compounding asset and the entire reason a late competitor cannot catch up.**
2. **Every fact carries provenance.** A claim without a verified citation is deleted, not shipped.
3. **Model the change, not just the state.** Knowing the current ordinance is a commodity that three companies already sell. Knowing that it changed 90 days ago, who moved it, and which neighbouring county is next — that is the product.

### 6.7 Stage 7 — Feature engineering

The complete feature dictionary for v1. Grouped by what they measure.

#### Group A — Base rates and history
| Feature | Definition | Why predictive |
|---|---|---|
| `approval_rate_juris_use` | Approval rate for this use class in this jurisdiction, all time | The strongest single predictor. Boring and dominant. |
| `approval_rate_juris_use_24m` | Same, last 24 months only | Captures regime change. Diverging from the all-time rate is itself a signal. |
| `approval_rate_trend` | Slope of the last 8 decisions | Detects a hardening or softening board before it is obvious |
| `denial_streak` | Consecutive denials for this use class | Boards behave with momentum |
| `withdrawal_rate` | Share withdrawn before decision | **Hidden denials.** A high withdrawal rate means staff kills projects quietly — the true denial rate is much higher than the recorded one. |
| `n_comparable_decisions` | Count of usable precedents | Drives pooling weight and the abstention rule |

#### Group B — Rules and discretion
| Feature | Definition | Why predictive |
|---|---|---|
| `by_right` | Is the use permitted as of right? | Binary, and enormous. By-right sites barely need us; that is fine — we tell them so. |
| `discretion_index` | Share of the decision that is discretionary vs ministerial, 0–1 | The mechanism by which politics enters |
| `relief_count` | Number of separate approvals needed | Each one is an independent failure point |
| `overlay_present` | Use-specific overlay in force | Usually adopted *in response to* projects like yours |
| `days_since_rule_change` | Days since the governing instrument changed | **A change in the last 180 days is the single most dangerous condition, and the one humans miss most often** |
| `setback_compliance_margin` | Metres of slack against the binding setback | Converts a legal text into a continuous number |
| `moratorium_active` / `moratorium_expiry` | Currently banned; when it lifts | Turns a hard no into a dated no |

#### Group C — Politics and people
| Feature | Definition | Why predictive |
|---|---|---|
| `board_composition_score` | Weighted history of the sitting members on this use class | Institutions do not vote; people do |
| `swing_seat_count` | Members with mixed voting histories | Determines variance, i.e. the width of the interval |
| `months_to_next_election` | For the deciding body | Approvals of unpopular uses fall sharply near elections |
| `turnover_since_last_comparable` | Share of seats changed since the last precedent | Precedent decays when the people change. Most models ignore this. |
| `staff_recommendation_alignment` | Historical rate at which the body follows its own staff | If a board overrules staff 40% of the time, a positive staff report means much less |

#### Group D — Opposition
| Feature | Definition | Why predictive |
|---|---|---|
| `objection_density_24m` | Objection events per decision in this jurisdiction | Baseline civic temperature |
| `organised_group_present` | Named group with repeat appearances | Organised opposition wins far more than individual opposition |
| `salience_water` / `_power_cost` / `_noise` / `_traffic` | Topic frequency in recent hearings and local news | **Identifies the specific argument that will be used against you** |
| `neighbour_contagion` | Objection or restriction activity in adjacent jurisdictions | Opposition tactics diffuse geographically faster than policy |
| `media_volume` | Local coverage count, 90 days | Political cost of a yes |

#### Group E — Physical and infrastructural
| Feature | Definition |
|---|---|
| `distance_to_residential` | Metres to nearest residential zone — the most common trigger |
| `distance_to_transmission`, `substation_headroom_mw` | Grid feasibility |
| `water_stress_index` | Increasingly the binding constraint, not power |
| `parcel_acres`, `capacity_mw`, `intensity_mw_per_acre` | Scale drives opposition non-linearly |
| `prior_industrial_use` | Brownfield sites are dramatically easier |

#### Group F — Applicant
| Feature | Definition | Note |
|---|---|---|
| `applicant_track_record` | Approval rate of this applicant cluster | Genuinely predictive |
| `applicant_local_experience` | Prior applications in this jurisdiction | Cuts both ways — measure, do not assume |
| `entity_opacity` | Single-purpose LLC with no disclosed principal | Opacity correlates with opposition |

**[DECISION]** No feature is used unless (a) it can be computed for ≥80% of the target jurisdictions, (b) it is derived from a document with verified provenance, and (c) it can be explained to a customer in one plain sentence. **Explainability is a hard product requirement, not a nice-to-have** — an unexplainable driver cannot appear in a memo, and a memo is what gets paid for.

### 6.8 Stage 8 — Modelling

Two models, because there are two questions. Conflating them is the most common analytical error in this domain.

#### Model 1 — Will it be approved? (hierarchical classifier)

The problem: most jurisdictions have 3–8 usable historical decisions. A flat model either overfits to noise or ignores locality entirely.

The solution: **partial pooling**. Let jurisdiction *j* sit inside cluster *c* (similar jurisdictions grouped by population density, home-rule status, discretion index, region, and prior behaviour).

```
for application i in jurisdiction j, cluster c:

    y_i  ~ Bernoulli(p_i)
    logit(p_i) = a_j + X_i · b + Z_i · g_c

    a_j  ~ Normal(mu_c, sigma_c)        # jurisdiction intercept shrinks toward its cluster
    mu_c ~ Normal(mu_0, tau)            # cluster mean shrinks toward the global mean
    b    ~ Normal(0, 1)                 # global feature effects
    g_c  ~ Normal(0, s)                 # cluster-specific effects
```

What this buys, in plain terms:
- A county with **40 decisions** is scored almost entirely on its own record.
- A county with **2 decisions** is scored mostly on how similar counties behave, and **the interval is correctly wide**.
- The model degrades gracefully instead of lying confidently. **That is the whole point.**

**Implementation path:** XGBoost baseline on day 13 to establish signal and a floor. Hierarchical Bayesian model in **NumPyro** (or PyMC) by day 15–16. Keep both permanently — the gradient-boosted model is the honest benchmark the Bayesian model must beat, and if it never does, ship the simpler one.

#### Model 2 — How long will it take? (survival analysis)

Approval is not a yes/no. It is a **duration**, and a two-year yes is often worse than a fast no because of carry cost.

This must be survival analysis, not regression, for one technical reason that matters commercially: **pending applications are right-censored**. A project filed 14 months ago with no decision yet is not a missing value — it is the information that *at least* 14 months have elapsed. Throwing those rows away biases every timeline estimate optimistically, which is exactly the direction that destroys customer trust.

- Method: Cox proportional hazards for interpretable driver effects; Accelerated Failure Time or a discrete-time hazard model for calibrated P10/P50/P90 output.
- Competing risks: approval, denial and withdrawal are **three distinct exits**, not one event. Modelled as competing risks.
- Library: `lifelines` for v1; `scikit-survival` if performance demands it.

#### Model 3 — Will the rules change first? (hazard model)

A small, separate model for `probability_of_rule_change_before_decision`. Trained on ordinance and moratorium adoption events, with features for neighbour contagion, objection density, media volume and election proximity.

**[DECISION]** This is a distinct model rather than a feature, because it is the risk humans most consistently fail to price, and because it is the one that produces the most valuable alert (§6.11).

#### The architectural rule that matters most

> **No language model produces the number.**
>
> Models extract facts and write explanations. **The probability is produced by a statistical model that can be back-tested and calibrated.**

This is not stylistic. A number generated by a language model cannot be calibrated, cannot be back-tested, cannot be audited, and therefore **cannot be sold to a credit committee or accepted by an insurer**. Every competitor that skips this is permanently ceiling-capped at "useful research tool." It is the most important line in this document.

### 6.9 Stage 9 — Calibration and evaluation

Calibration is not a metric here. **It is the product.** It therefore gets first-class tooling.

| Metric | Definition | Target v1 | Why this metric |
|---|---|---|---|
| **Brier score** | Mean squared error of probabilistic forecasts | Beat the base-rate model by ≥15% | The headline number. Single, honest, hard to game. |
| **Reliability curve** | Predicted vs observed frequency, decile bins | Within ±10 points per bin | This is what a customer actually checks |
| **Expected Calibration Error** | Weighted mean bin deviation | <0.08 | Summarises the curve |
| **AUC / ROC** | Ranking ability | >0.70 | Portfolio screening only needs correct *ordering* |
| **Concordance index** | Ranking for the survival model | >0.65 | Timeline equivalent of AUC |
| **Coverage** | Share of outcomes inside the 80% interval | 76–84% | Tests honesty of uncertainty, which is what an insurer will ask about |
| **Abstention precision** | Accuracy on answered vs abstained cases | Answered materially better | Proves abstention is intelligent, not lazy |

#### Validation discipline — the part that is easy to get wrong

1. **Temporal splits only.** Train on decisions before a cutoff date, test after. **Random k-fold is invalid here** and will produce a beautiful, worthless result, because it leaks future ordinances and future board compositions into the training set.
2. **Leave-one-jurisdiction-out** as a second test, to prove the model generalises to a county it has never seen. This is the test that matters for expansion.
3. **Point-in-time feature reconstruction.** Every feature must be computed as it would have been known *on the filing date*. If the score for a 2024 decision uses a 2025 ordinance, the model is cheating. **[DECISION]** All feature tables are bi-temporal (`valid_from`, `valid_to`) specifically to make this enforceable rather than aspirational.
4. **Calibration applied after fitting** — isotonic regression, or Platt scaling on small samples — and re-fitted monthly.
5. **A base-rate model is a permanent tracked baseline.** If the sophisticated model cannot beat "the historical approval rate for this use class in this county," it must not ship.

### 6.10 Stage 10 — Output generation

Three sub-components:

1. **Explanation.** Driver weights come from the model (SHAP for the boosted model, posterior contributions for the Bayesian one). A mid-tier language model turns each into one plain sentence, **constrained to the facts already extracted** — it is given the driver, the evidence quote and the numbers, and is forbidden from adding anything.
2. **The alternative-site ranker.** Given a target region and requirements, search the graph for parcels that (a) satisfy physical constraints, (b) sit in jurisdictions with materially higher scores, (c) are ideally **by right**. Ranked by expected value: `score × feasibility − relocation_cost`. This is the highest-value single feature in the product and the reason customers renew.
3. **The memo.** Templated HTML → PDF via headless Chromium. Deterministic, versioned, and every claim hyperlinked to its source document.

### 6.11 Stage 11 — Monitoring and re-scoring

**Monitoring is what turns a report into a subscription.** Without it there is no recurring revenue and this is a consulting business.

Daily job: re-ingest all watched jurisdictions → diff against yesterday → detect material events → re-score every affected site → fire alerts.

| Trigger | Alert | Value to customer |
|---|---|---|
| Ordinance or overlay amended | "Rules changed in a jurisdiction where you hold 3 sites" | **Highest.** This is the retroactive-kill scenario, caught early. |
| Moratorium proposed **or on an agenda** | "A moratorium is on next Tuesday's agenda" | Enormous — there is still time to act |
| Comparable application denied nearby | "A similar project was denied 40 km away; your score moved from 0.61 to 0.48" | Directly actionable |
| Board member resigned, replaced, or lost | "Board composition changed; two of your sites re-scored" | Invisible to humans until too late |
| Litigation filed against a comparable | "Appeal risk in this jurisdiction has risen" | Timeline impact |
| Agenda mentions your use class | "This county is discussing data centres on Thursday" | The leading indicator, days ahead of any news |

**[DECISION]** Alerts are scored for materiality before sending. An alert system that cries wolf gets muted in a week, and a muted alert system is a cancelled subscription.

### 6.12 Data freshness commitments

Stale data is the real outage in this business. These are the internal SLAs, and they are published on the accuracy page.

| Source | Refresh | Why |
|---|---|---|
| Agendas | Daily | The leading indicator — the whole point |
| Minutes and votes | Daily | Outcomes must land fast |
| Ordinances and moratoria | Daily | Retroactive-kill risk |
| Hearing transcripts | Weekly, top counties | Expensive; not time-critical |
| Parcel and assessor data | Monthly or per publication | Slow-moving |
| Litigation dockets | Weekly | Slow-moving |
| Election data | Per cycle plus filing deadlines | Calendar-driven |

Every score displays `data_as_of`. **If a jurisdiction's data is more than 14 days stale, the score is flagged in the UI and in the API response.** Silent staleness is the fastest way to lose the one asset that matters.

---

## 7. The stack

### 7.1 What "best" means here — read this before the tables

You asked for the best of the best. I want to be precise about what that means, because the naive reading of it is the fastest way to fail.

**"Best" does not mean the technology used by the largest company.** Netflix's stack is best-in-class *for Netflix* and would be actively fatal for one person with thirty days. Kubernetes, Kafka, Snowflake and a microservice mesh are all genuinely excellent and all wrong here.

**"Best" here means: highest quality tool that a single operator can run correctly, that will not need to be replaced at 100× the current scale.** Every choice below is best-in-class *in its category* and chosen so that nothing has to be thrown away later.

Three selection principles:

1. **Boring where it is load-bearing, modern where it is leverage.** The database is boring on purpose. The model layer and the language-model tooling are aggressively modern, because that is where the differentiation is.
2. **Minimise the number of systems, not the amount of code.** Every additional running system is a failure mode, a backup, an upgrade path and an on-call burden. Code is cheap; systems are expensive.
3. **Nothing that requires a second person to operate.** If a technology needs a platform engineer, it is disqualified regardless of merit.

> **The scarce resource in this project is the month, not the compute.**

### 7.2 The complete stack

| Layer | Choice | Version | Why this is the best choice here | Rejected alternative, and why |
|---|---|---|---|---|
| **Data/ML language** | **Python** | 3.13 | Owns the document, ML and scientific ecosystem outright. Not close. | Rust — faster, but no Bayesian or survival ecosystem. Wrong tool. |
| **Web language** | **TypeScript** | 5.x, strict mode | Type safety across the API boundary; strict mode non-negotiable | Plain JS — no. Type errors in a risk product are unacceptable. |
| **Python packaging** | **uv** | latest | 10–100× faster than pip; single tool for envs, locking and installs. Genuinely best-in-class now. | Poetry, pip-tools — slower, more moving parts |
| **Python lint/format** | **Ruff** | latest | Replaces flake8, isort, black, and a dozen plugins with one fast binary | The old multi-tool chain |
| **Type checking** | **mypy** strict, or **pyright** | latest | Strict typing on the data layer catches the errors that silently corrupt a dataset | Untyped Python — fine for scripts, not for a corpus |
| **Database** | **PostgreSQL** | 17+ | **The single most important choice.** Relational + geospatial + vector + fuzzy text + JSON + graph traversal in one system. At this scale it genuinely does all six well. | A polyglot stack of Postgres + Neo4j + Pinecone + Snowflake: four systems, four backups, four sync bugs, zero added capability at this scale |
| **Geospatial** | **PostGIS** | 3.5+ | The best geospatial engine that exists, in any language, at any price | Shapely-only in application code — loses spatial indexing and does not scale |
| **Vector search** | **pgvector** | 0.8+ | Embeddings live beside the rows they describe. HNSW indexing is fast enough for hundreds of millions of vectors. | A dedicated vector DB — a second datastore means a second sync problem for zero benefit here |
| **Fuzzy text** | **pg_trgm** + full-text search | built in | Entity resolution and search without a second engine | Elasticsearch — excellent, and an entire additional system to operate |
| **Graph traversal** | **Recursive CTEs in Postgres** | — | Traversal depth here is 2–4 hops. Postgres handles this trivially. | Neo4j — genuinely the best graph DB, and a month of operational work for a problem we do not have. **Revisit only if a real query proves it.** |
| **Analytical queries** | **DuckDB** | latest | Embedded OLAP over Parquet for feature-building and back-tests. Zero infrastructure, extraordinary speed. | Snowflake/BigQuery — a warehouse bill and a data-sync pipeline for a dataset that fits on a laptop |
| **Dataframes** | **Polars** | latest | Multi-threaded, lazy, far faster than pandas on the feature-engineering path | pandas — kept only where a library demands it |
| **Migrations** | **Alembic** | latest | Versioned, reviewable schema history. The graph schema will change weekly. | Hand-run SQL — guarantees drift and an unreproducible database |
| **ORM / query layer** | **SQLAlchemy 2.0 Core** | 2.0+ | Typed query building without hiding SQL. PostGIS and CTEs need real SQL. | A heavy ORM that abstracts SQL away — fights you on exactly the queries that matter |
| **HTTP client** | **httpx** + **tenacity** | latest | Async, HTTP/2, with principled retry and backoff | requests — no async |
| **Browser automation** | **Playwright** | latest | The best in class. Handles the JS-heavy civic portals that block simple clients. | Selenium — slower, flakier, worse API |
| **Orchestration** | **Prefect 3**, or a `jobs` table + cron | 3.x | Retries, observability and scheduling with almost no operational surface | **Airflow — explicitly rejected.** Excellent at 50 engineers, an operational tax at one. |
| **Document parsing** | **PyMuPDF** → **pdfplumber** → **Tesseract** → vision model | latest | Cost-ordered cascade. Cheap deterministic first, expensive intelligent last. | Sending every page to a vision model — 100× the cost for a worse result on native PDFs |
| **Transcription** | **Whisper-class ASR** with diarisation | large-v3 class | Unlocks the highest-value untouched corpus in the market | Skipping audio — abandoning the actual differentiator |
| **Media handling** | **ffmpeg** | latest | Universal. Audio-only extraction cuts download volume ~50–100×. | Downloading full video |
| **LLM — extraction** | **Frontier model, schema-enforced structured output** | current best | Accuracy here determines everything downstream. This is the one place to pay for the best. | A cheap model on extraction — false economy; bad facts poison the corpus permanently |
| **LLM — bulk classification** | **Small fast model** | current best small | 90% of volume is triage. Use the cheap model for the easy majority. | Frontier model on everything — 10–30× the bill for no gain |
| **LLM plumbing** | **Direct provider SDKs + Pydantic + Instructor-style validation** | — | Thin, debuggable, no framework lock-in | **LangChain / heavy agent frameworks — rejected.** Abstraction over an API you must understand precisely; the debugging cost exceeds the saved code. |
| **Prompt/eval management** | **Versioned prompts in git + a golden test set** | — | Prompts are code. They get diffs, reviews and regression tests. | Prompts pasted in notebooks — unreproducible extraction, which is fatal |
| **ML — baseline** | **XGBoost** + **scikit-learn** | 2.x / 1.x | Best-in-class on small tabular data. Still beats deep learning here, decisively. | A neural network on 4,000 rows — worse, slower, unexplainable |
| **ML — the real model** | **NumPyro** (JAX) or **PyMC** | 5.x | Hierarchical Bayesian modelling with proper uncertainty. **This is the technical moat.** | Flat ML — overfits thin jurisdictions and lies confidently |
| **Survival analysis** | **lifelines**, then **scikit-survival** | latest | Handles right-censored pending applications correctly | Linear regression on completed cases — systematically optimistic, destroys trust |
| **Explainability** | **SHAP** + posterior contributions | latest | Every driver in a memo must be defensible | An unexplained score — unsellable to a committee |
| **Experiment tracking** | **MLflow** | 2.x | Every model version, dataset hash, metric and calibration curve recorded. **Mandatory** — the public accuracy record depends on reproducibility. | Notebooks and memory |
| **API framework** | **FastAPI** + **Pydantic v2** | latest | Typed contracts, auto-generated OpenAPI, async. Best in class in Python. | Django — too much machinery; Flask — too little typing |
| **Auth** | **Clerk** or **WorkOS** (enterprise SSO) | — | Never build auth. WorkOS specifically because enterprise buyers demand SAML/SSO. | Rolling your own — a security incident waiting to happen |
| **Frontend framework** | **Next.js** (App Router) + **React 19** | 15+ | Server components cut client bundle size; best-in-class DX; trivial deployment | An SPA — slower first paint, worse SEO on the public accuracy pages that are the marketing |
| **Styling** | **Tailwind CSS 4** + **shadcn/ui** + Radix primitives | 4.x | Fast, consistent, accessible by default. shadcn is copy-in, not a dependency — no lock-in. | A component library you cannot restyle |
| **Maps** | **MapLibre GL JS** + vector tiles from PostGIS `ST_AsMVT` | 5.x | Open source, no per-view billing, self-served tiles. **Removes an uncapped cost line entirely.** | Mapbox/Google Maps — excellent, with a bill that scales with usage |
| **Data grid** | **TanStack Table** | v8 | Headless, virtualised — handles a 500-row portfolio screen without lag | A heavyweight enterprise grid |
| **Charts** | **Observable Plot** or **Recharts** | latest | The reliability curve is the most important chart in the company; it must be exact | A dashboard library that cannot draw a calibration plot properly |
| **Client state / data** | **TanStack Query** + **Zod** | latest | Zod validates every API response at the boundary. Bad data must never render silently. | Unvalidated fetches |
| **PDF generation** | **Templated HTML → headless Chromium** | — | Pixel-exact, versionable, uses the same components as the web UI | A PDF library — fighting layout in code for a document that must look excellent |
| **Object storage** | **Cloudflare R2** (or S3) | — | **Zero egress fees**, S3-compatible. The raw corpus will be terabytes and gets re-read often. | S3 with heavy egress — the reprocessing bill scales badly |
| **Hosting** | **One Hetzner dedicated server** (Docker Compose) — or Fly.io/Railway + **Neon** managed Postgres | — | A single powerful box is dramatically cheaper and simpler. Managed Postgres if you would rather not own backups. | Kubernetes — rejected outright. AWS from day one — a full-time job disguised as infrastructure. |
| **Containers** | **Docker** + **Docker Compose** | latest | Reproducible, one file, runs identically on the laptop and the server | Bare-metal installs — unreproducible |
| **CDN / edge / DNS / WAF** | **Cloudflare** | — | Free tier covers everything needed; DDoS protection and caching included | Nothing in front of the origin |
| **CI/CD** | **GitHub Actions** | — | Lint, type-check, test, build, deploy on push. **Non-negotiable even solo** — it is the only thing preventing a bad prompt or migration reaching production. | Manual deploys |
| **Error tracking** | **Sentry** | — | Best in class, free tier sufficient | Log-grepping |
| **Metrics / uptime** | **Better Stack**, or Prometheus + Grafana | — | Managed for speed; self-hosted if cost matters | No monitoring |
| **Data-quality monitoring** | Custom checks + **Great Expectations** (optional) | — | **More important than uptime monitoring here.** Track freshness, extraction rate, quote-verification rate, schema violations. | Only monitoring servers — the actual failure mode is silently stale or wrong data |
| **Secrets** | **1Password/Doppler** + env injection | — | Never in git | `.env` committed |
| **Backups** | Nightly `pg_dump` + WAL archiving to R2, **restore tested weekly** | — | An untested backup is not a backup | Assuming the provider handles it |

### 7.3 The website stack, in depth

You specifically asked about the website, so here is the reasoning in full rather than a table row.

**[DECISION] Next.js 15 App Router + React 19 + TypeScript strict + Tailwind 4 + shadcn/ui + MapLibre.**

Why this is the correct answer and not just a popular one:

1. **Two audiences, one codebase.** The public accuracy page must be fast, crawlable and shareable — it is the primary marketing asset. The logged-in application must be a rich, stateful analyst tool. Next.js server components serve the first perfectly and client components serve the second. A pure SPA would handicap the marketing surface; a pure static site could not run the app.
2. **The map is the product's face, and MapLibre makes it free.** Serving vector tiles directly from PostGIS via `ST_AsMVT` means the geospatial data never leaves the database and there is no per-map-view bill. At portfolio-screening volumes a commercial map SDK becomes a real and unpredictable cost line.
3. **shadcn/ui is copy-in, not a dependency.** The components live in your repo and can be modified freely. For a product whose credibility depends on a bespoke, precise presentation of uncertainty, an un-restylable component library is a trap.
4. **Zod at the boundary.** Every API response is validated before it renders. In a risk product, silently rendering a malformed score is worse than showing an error.
5. **Accessibility for free.** Radix primitives under shadcn mean keyboard navigation and screen-reader support work by default. Enterprise and government-adjacent buyers ask about this in procurement.

**Performance budget:** public pages under 100 KB of JS and a Largest Contentful Paint under 1.5 s on a 4G connection; the app shell under 300 KB. Enforced in CI, because performance rots silently.

### 7.4 Repository layout

A single monorepo. **[DECISION]** One repo, because one person context-switching across four repos loses more time than any separation-of-concerns benefit gains.

```
auspice/
├─ apps/
│  ├─ web/                 # Next.js: public accuracy site + logged-in app
│  └─ api/                 # FastAPI service
├─ packages/
│  └─ shared-types/        # OpenAPI-generated TS types — one source of truth
├─ pipeline/
│  ├─ registry/            # Stage 0: jurisdictions, boundaries, election calendars
│  ├─ adapters/            # Stage 1: legistar.py, civicplus.py, accela.py, opengov.py, municode.py
│  ├─ ingest/              # fetch, hash, store, dead-letter
│  ├─ parse/               # Stage 2: pdf, ocr, chunking
│  ├─ transcribe/          # Stage 3: audio pipeline
│  ├─ extract/             # Stage 4: schemas/, prompts/, verify.py
│  ├─ resolve/             # Stage 5: entity resolution
│  ├─ graph/               # Stage 6: models, migrations, loaders
│  ├─ features/            # Stage 7: point-in-time feature builders
│  └─ flows/               # Prefect flow definitions
├─ models/
│  ├─ baseline/            # XGBoost
│  ├─ hierarchical/        # NumPyro
│  ├─ survival/            # lifelines
│  ├─ rulechange/          # hazard model
│  └─ eval/                # calibration, backtests, reliability curves
├─ ledger/                 # §8.2 hashed public prediction ledger
├─ memo/                   # HTML templates → PDF
├─ tests/
│  ├─ golden/              # hand-labelled extraction fixtures — the regression suite
│  └─ unit/
├─ infra/
│  ├─ docker-compose.yml
│  └─ migrations/
└─ docs/
   ├─ METHODOLOGY.md       # public: how the model works
   ├─ NEUTRALITY.md        # public: the charter in §8.6
   └─ DATA_SOURCES.md      # public: every source, with refresh cadence
```

Those three files in `docs/` are **published on the website**. Publishing your methodology is counter-intuitive and is a core part of the trust architecture (§8).

### 7.5 Running cost — real numbers

**[ASSUMPTION]** Month-one estimates, deliberately conservative.

| Line | Monthly | Note |
|---|---|---|
| Dedicated server (Hetzner, ~64 GB RAM, NVMe) | $60–120 | Runs Postgres, API, workers, everything |
| Object storage (R2, ~1–5 TB raw corpus) | $15–75 | Grows; zero egress is the reason it stays cheap |
| Cloudflare | $0–25 | Free tier is genuinely sufficient at first |
| Sentry, Better Stack | $0–50 | Free tiers |
| Auth (Clerk/WorkOS) | $0–99 | Free below first user thresholds |
| Domain, email | $10–30 | |
| **Infrastructure subtotal** | **$85–400** | |
| **LLM inference** | **$400–2,500** | **The real cost line, and the one to actively manage** |
| Transcription | $50–300 | Scoped to top counties only |
| **Total** | **~$550–3,200/month** | |

**Cost-control levers, in order of impact:**
1. **Cache by content hash + prompt version.** Reprocessing unchanged documents must cost zero. This alone is usually a 5–10× saving.
2. **Triage with the cheap model.** Roughly 90% of documents are irrelevant to a given use class; do not pay frontier prices to discover that.
3. **Batch APIs** where latency does not matter — typically ~50% cheaper.
4. **Extract once, re-derive features many times.** Facts live in Postgres; feature changes never re-invoke a model.
5. **Escalate, never default.** Cheap deterministic parsing first; a model only when parsing fails.

### 7.6 Explicitly rejected, and why

| Rejected | Genuinely good at | Why it is wrong here |
|---|---|---|
| **Kubernetes** | Multi-team, multi-service scale | Weeks of setup, permanent operational tax, for one service on one box |
| **Kafka** | High-throughput event streaming | Daily batch is the correct cadence. This is not a streaming problem. |
| **Snowflake / BigQuery** | Petabyte analytics | The dataset fits on a laptop. DuckDB is faster for this and free. |
| **dbt** | Team-scale SQL transformation | Real value, real overhead; adopt at month six if the SQL sprawls |
| **Neo4j** | Deep graph traversal | Depth 2–4 hops. Postgres CTEs suffice. Revisit only on evidence. |
| **Dedicated vector DB** | Billion-scale ANN | pgvector handles this scale; a second store is a second sync bug |
| **LangChain / agent frameworks** | Rapid prototyping | Abstraction over APIs you must understand exactly. Debugging cost exceeds saved code. |
| **Fine-tuning a custom model** | Narrow repetitive tasks at scale | Premature. Schema-enforced prompting with a frontier model is better and instantly changeable. Revisit at month nine on cost grounds only. |
| **Microservices** | Independent team deployment | One person. One service. |
| **A native mobile app** | Consumer products | The users are analysts at desks with two monitors |
| **Blockchain for the prediction ledger** | Trustless multi-party settlement | A SHA-256 hash published publicly, plus an optional third-party timestamp, achieves the same credibility with none of the cost or the credibility hit |

### 7.7 Upgrade triggers — when each choice is allowed to change

Defining these in advance prevents both premature scaling and stubbornness.

| Change | Only when |
|---|---|
| Add Neo4j | A required query needs >5 hops or CTEs exceed 2 s at p95 |
| Add a warehouse | The corpus exceeds ~2 TB of structured data or 3+ people query it daily |
| Add Kubernetes | ≥3 engineers and ≥5 independently deployed services |
| Fine-tune a model | LLM spend exceeds $10K/month **and** the task set is stable for 60 days |
| Split the monorepo | ≥4 engineers with genuinely separate release cadences |
| Move off one server | Sustained p95 latency >800 ms or a real availability commitment in a signed contract |

---

## 8. The trust architecture

This is the most important section in the document. Nobody hands a $500 million decision to a black box from an unknown company. Trust here is not earned by branding — it is **engineered, then proven in public**.

Seven mechanisms, in order of power.

### 8.1 Published calibration

**The claim:** if Auspice says 70%, it happens about 70% of the time.

**The implementation:** a public page, updated monthly, no login required, showing the reliability curve, the Brier score, the base-rate benchmark, the sample size, and the trend over time.

**Why no competitor will copy it:** for a data vendor, publishing an accuracy score is pure downside — it creates a liability and invites comparison. For Auspice it is the entire positioning. **The asymmetry is structural, not accidental.**

### 8.2 Prospective, timestamped, hashed public predictions

**This is the moat. Everything else is execution.**

The mechanism:
1. Identify pending public applications — filed, not yet decided.
2. Score them **before** any decision exists.
3. Publish `{application_id, prediction, interval, model_version, features_hash, timestamp}` and the **SHA-256 of the full record** to a public, append-only ledger.
4. Optionally anchor the daily ledger hash to an independent timestamping authority.
5. When reality resolves, grade it publicly. No edits. No deletions. No retroactive changes — the append-only property is the whole point.

**Why this cannot be beaten by money or headcount:**

| Asset | Can a funded competitor replicate it? |
|---|---|
| The web app | Yes, in a weekend |
| The pipeline | Yes, in 4–8 weeks |
| The model | Yes, in 2–4 weeks |
| The dataset | Yes, in 3–6 months with a team |
| **Twelve months of timestamped, publicly verified, correct calls** | **No. Not with any amount of money.** |

A competitor starting today is twelve months behind **permanently**. They cannot buy time. This is why §12 puts "publish 25 predictions" on **day 25**, ahead of billing, onboarding and polish. Every day of delay is a day of moat that can never be recovered.

### 8.3 Evidence-linked outputs

Every number expands into the ordinance clause, the vote tally, the minute, the docket page, or the timestamped transcript line.

Customers do not have to believe the model — they can check it. **In enterprise sales, auditability beats accuracy.** A slightly less accurate system whose reasoning can be verified will out-sell a more accurate black box every time, because the buyer's real job is defending a decision.

Enforced mechanically: the quote-verification step in §6.4 discards any extraction whose quote is not found verbatim in the stored source. **Hallucinated citations are eliminated structurally, not by trust.**

### 8.4 Explicit abstention — the system is allowed to say "I don't know"

Abstention rule:

```
abstain if:
    n_comparable_decisions < 3
    AND cluster_pooling_weight > 0.8
    AND credible_interval_width > 0.35
```

When it abstains, the customer is shown what *is* known — the rules, the board, the recent history — and told plainly that a probability would be dishonest.

> A system that always answers is trusted exactly once.

Competitors will not copy this, because in a demo it looks like weakness. In production it is the reason a customer renews. **`abstention_precision` is tracked as a first-class metric** (§6.9) to prove abstention is intelligent rather than lazy.

### 8.5 The public misses log

Wrong calls are published with a written explanation of what the model missed and what changed as a result.

Counter-intuitive, and the fastest trust-builder available: **nobody who is hiding results volunteers their failures.** Publishing misses is a costly signal, and costly signals are the only credible ones.

### 8.6 The neutrality charter

Published as `NEUTRALITY.md` on the website, and binding:

1. Auspice takes **no land positions**, ever.
2. Auspice does **no brokerage, development, lobbying, or expediting**.
3. Auspice never advocates for or against an application.
4. The same data is available to developers, lenders, insurers, **counties and community groups** — the last two at zero or near-zero cost.
5. Auspice models **published voting records and stated positions**, never inferred personal motives.
6. No customer can pay to change a score, see a competitor's queries, or suppress a result.

Rule 6 is the one that will be tested by a large customer with a large cheque. **The answer must be no, in writing, the first time.** One exception destroys the asset permanently, and the asset is the only thing here that is not copyable.

### 8.7 Skin in the game — once earned, and only in this order

| Stage | Commitment | Precondition |
|---|---|---|
| 1 | Publish accuracy | Day 25 |
| 2 | Fee-back guarantee on materially wrong calls | 6 months of calibration data |
| 3 | Warranty product with a defined payout | 12 months, ECE < 0.08 |
| 4 | Parametric delay insurance with a carrier or MGA | 24 months, actuarially reviewed |

Financial exposure to your own accuracy is the strongest trust signal that exists. **It is also the fastest way to go bankrupt if offered before calibration is proven.** The order is not negotiable.

### 8.8 Why not trust anyone else — in one sentence

> Every other company in this space sells **information**. Auspice sells a **number it is publicly accountable for**. The industry has plenty of data vendors and no rating agency.

### 8.9 Things Auspice will never do

- Never predict how a **named individual** will vote. Aggregate board behaviour only. Modelling individuals is legally reckless and ethically indefensible.
- Never infer or imply motive, corruption, or bad faith.
- Never sell a "guaranteed approval" or an introduction to an official.
- Never let a customer's identity influence a score.
- Never quietly revise a published prediction.
- Never present a score without its interval and its `data_as_of` date.

---

## 9. Competition

Stated plainly: **this is not an empty market, and any pitch claiming to be first is false.** Real, funded companies work adjacent to this. The gap is not the data — it is the accountable forecast.

### 9.1 The landscape

```
                    BACKWARD-LOOKING            FORWARD-LOOKING
                    (what happened)             (what will happen)
                 ┌───────────────────────┬───────────────────────┐
  RULES / CODE   │ Zoneomics, Gridics,      │                      │
  (what is       │ Municode                 │        — empty —     │
   allowed)      │                          │                      │
                 ├───────────────────────┼───────────────────────┤
  PROCESS /      │ GatherGov, Shovels,      │                      │
  POLITICS       │ permit trackers          │   ◄── AUSPICE        │
  (who decides,  │                          │                      │
   and will they)│                          │                      │
                 ├───────────────────────┼───────────────────────┤
  GRID / POWER   │ Enverus, Pearl Street    │ GridCare, Verse,     │
                 │                          │ Paces                │
                 └───────────────────────┴───────────────────────┘
```

The bottom-right cell is well funded. **The middle-right cell — forward-looking political and process risk — is where Auspice sits, and it is the least occupied.**

### 9.2 Competitor by competitor

#### GatherGov — the closest direct competitor
- **What they do well:** local government meeting and agenda intelligence, entitlement tracking. Genuinely useful, and genuinely in this space.
- **Where they stop:** they tell you what **happened**. No calibrated probability, no time-to-decision distribution, no published accuracy record.
- **How we win:** forecast rather than archive; publish calibration; model the political layer rather than just surfacing the documents.
- **Honest risk:** they have distribution and a head start on the document layer. If they add a calibrated forecast and publish accuracy, this becomes a real fight. **They are the company to watch.**
- **Relationship:** competitor. Possibly an acquirer.

#### Zoneomics / Bassett.ai
- **What they do well:** broad zoning-data coverage across the US, plus an AI zoning assistant.
- **Where they stop:** they answer what is allowed **by right**. They cannot answer whether a discretionary body will approve. **Rules are not politics** — and the money is lost in the gap between them.
- **How we win:** we treat their answer as one input feature (`by_right`, `setback_compliance_margin`) rather than the conclusion.
- **Relationship:** potential data supplier, potential acquirer.

#### Gridics
- **What they do well:** zoning code as structured data and APIs, largely sold to cities.
- **Where they stop:** code-as-data, not risk prediction, and not cross-jurisdiction comparison. Their customer is the city; ours is the capital.
- **Relationship:** potential supplier.

#### Shovels
- **What they do well:** excellent building-permit and contractor records by API.
- **Where they stop:** strictly backward-looking. A record of past permits with no decision layer on future ones.
- **How we win:** different question entirely. Their data is a useful confirmation signal for us.
- **Relationship:** natural partner.

#### Paces
- **What they do well:** site selection for renewables and data centres — **the same customer, the adjacent problem.**
- **Where they stop:** primarily land and grid screening; political approval probability is not the core product.
- **How we win:** depth on the human layer, and calibration.
- **Relationship:** the most likely partner or acquirer in the list.

#### GridCare (~$64M raised) and Verse (~$54M raised, Nvidia-backed)
- **What they do well:** finding grid headroom and accelerating interconnection. Serious money and serious teams.
- **Where they stop:** they solve the **electrical** gate. Auspice solves the **human** gate.
- **How we win:** we are not competing. A site with perfect grid headroom and a hostile county is still dead — and they cannot tell you that.
- **Relationship:** **API customers.** They need the political layer, will not build it, and have budget. This is the single most promising early licensing conversation.

#### Enverus / Pearl Street
- **What they do well:** serious interconnection-queue analytics; Enverus has real energy-market distribution.
- **Where they stop:** energy only, grid only, no land-use or political layer.
- **Honest risk:** Enverus has the balance sheet to acquire into this space. That is an outcome, not only a threat.

#### KPMG, CBRE, BDO, Baker Tilly, Cresa — site selection and location advisory
- **What they do well:** deep human judgement, real relationships, genuine expertise.
- **Where they stop:** $150K–$500K per engagement, 8–16 weeks, unrepeatable, uncalibrated, unaccountable, and structurally incapable of screening 300 sites.
- **How we win:** 20–50× cheaper, same-day, comparable across a portfolio, and **scored**. We do not replace them on the final site — we replace the first 290 sites of their work, which is the part they do worst and enjoy least.

#### The real competitor: local counsel plus institutional gut feel
- **What it does well:** genuinely excellent in a single familiar jurisdiction. Often better than any model on one site.
- **Where it fails:** not portable, not comparable, not scalable to a portfolio, and impossible for a credit committee to underwrite. Invalidated by one election.
- **How we win:** **never compete on one site.** Compete on 300 sites, which no lawyer can do at any price. Then be the input the lawyer uses.

> **[DECISION]** Sales conversations must always open with the portfolio screen, never with a single-site score. Single-site is where we look weakest against a good lawyer; portfolio is where we are the only option in existence.

### 9.3 Competitive summary table

| Company | Forward-looking? | Political layer? | Calibrated? | Public accuracy record? | Cross-jurisdiction? |
|---|---|---|---|---|---|
| GatherGov | Partial | Yes | No | No | Yes |
| Zoneomics / Bassett | No | No | No | No | Yes |
| Gridics | No | No | No | No | Partial |
| Shovels | No | No | No | No | Yes |
| Paces | Partial | Partial | No | No | Yes |
| GridCare / Verse | Yes (grid) | No | Unknown | No | Yes |
| Enverus / Pearl Street | Yes (grid) | No | No | No | Yes |
| Consultancies | Yes (human) | Yes | No | No | No |
| Local counsel | Yes (human) | Yes | No | No | No |
| **Auspice** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

The fourth column is empty for everyone else. **That column is the business.**

### 9.4 The four durable advantages

1. **Published calibration.** Nobody else will do it, because for a data vendor it is pure downside. The asymmetry is structural.
2. **A timestamped public record.** Cannot be bought, accelerated, or back-dated. **The only asset in this business that money cannot shortcut.**
3. **Forecast, not archive.** Everyone else reports the past. The buyer is deciding about the future and will pay far more for that.
4. **Time as an output.** Probability is half the answer; **duration** determines whether a project pencils. Modelling time-to-decision as a distribution, with censoring handled correctly, is rare and immediately valuable.

Of those, only #2 is genuinely unassailable. **Therefore the strategy is to maximise the rate of accumulation of #2 and treat everything else as support.**

### 9.5 Attack scenarios and defences

| Scenario | Likelihood | Defence |
|---|---|---|
| GatherGov adds a forecast and publishes accuracy | Medium | Be twelve months ahead on the ledger. Consider a partnership or acquisition conversation early rather than late. |
| An incumbent with distribution (CoStar, Enverus, Zoneomics) bolts this on | Medium | They own data, not accountability. Also: license to them — a wholesale outcome is a good outcome. |
| A well-funded startup copies the approach with ten engineers | Medium–high | Only the record matters and it is time-locked. Start publishing in week four, not month six. |
| A hyperscaler builds it internally | Low–medium | They will — for themselves. They will not sell it to competitors, will not publish accuracy, and will not cover jurisdictions they are not currently in. |
| Government publishes standardised data and removes the moat | Low | The moat is the forecast and the record, not the raw data. Better public data makes Auspice cheaper to run. **This is upside, not risk.** |
| An open-source clone appears | Low | The corpus, the transcripts and the ledger are the asset. Publishing the method openly is already the plan (§7.4). |

### 9.6 Battlecards — what to actually say

| They say | Say this |
|---|---|
| "We already use Zoneomics." | "Good — keep it. Zoneomics tells you what the code permits. It cannot tell you that this board denied three of the last four applications like yours. We use their answer as one of our inputs." |
| "Our land-use counsel handles this." | "They should, on the final site. How many candidate sites did you look at before picking it? If the answer is more than twenty, your counsel never saw the other nineteen. That is where the money is lost." |
| "How do I know your number is right?" | "You do not have to take my word for it. Here is our public accuracy page and our prediction ledger, with every call we have made and every one we got wrong. Nobody else in this market will show you that." |
| "This is just AI guessing." | "No language model produces our number. The number comes from a statistical model that is back-tested and calibrated. The AI reads documents; the statistics do the forecasting. That is exactly why we can publish an accuracy score and nobody else does." |
| "Too expensive." | "It is $5,000. One site you walk away from early saves eight figures. What did the last site you abandoned at month fourteen cost you?" |
| "We can build this internally." | "You can — for the counties you are already in. You cannot build a twelve-month public accuracy record retroactively, and your credit committee will still want a third party to have signed the opinion." |

---

## 10. Go-to-market

### 10.1 The beachhead, defined precisely

**[DECISION]** US data centres, top 40 counties by announced pipeline, discretionary rezoning and special-use applications only.

Why this exact wedge and not a broader one:

| Criterion | Why data centres in 40 US counties wins |
|---|---|
| Pain intensity | A blocked site costs eight figures. Highest pain per project of any vertical. |
| Buyer sophistication | Institutional, numerate, already buys diligence products |
| Willingness to pay | Pays in USD, has a budget line for consultants already |
| Data availability | Public, English, and concentrated on five civic platforms |
| Decision volume | Enough recent decisions to train and validate a model |
| Political salience | Rising fast, which makes it more predictable, not less |
| Feasible in 30 days | **Only if narrow.** 40 counties is achievable; 3,000 is not. |

> Depth beats breadth absolutely. A calibrated model for 40 counties is a business. A shallow model for 3,000 counties is a demo that dies in the first customer meeting.

### 10.2 The first 40 conversations

Day 28–30. Target mix: 20 developers, 10 brokers and advisors, 10 lenders and funds.

Sourcing: public rezoning applications name the applicant and their consultants. **Every application in the corpus is a lead with a documented, current, expensive problem.** The dataset is also the prospect list — that is a rare and valuable property.

Opening message (short, specific, no pitch):

> Subject: 3 of the last 4 data centre applications in [County] were denied
>
> I built a model that scores permission risk for data centre sites — probability of approval and expected months to decision, with the precedent decisions it is based on.
>
> I ran your [County] site: it scores 0.34, mainly because of the overlay ordinance adopted in April and two board seats facing election. There are two sites 30 km away where this use is by right, scoring 0.81 and 0.76.
>
> Happy to send the one-page memo, free. If it is useful, we can talk.

**Why this works:** it leads with a specific fact about their actual site, delivers value before asking for anything, and the free memo is the demo. **[ASSUMPTION]** a 15–25% reply rate on this, versus 1–3% for a generic pitch.

### 10.3 Pricing and packaging

| Tier | Price | Includes | Target |
|---|---|---|---|
| **Single memo** | $2,500–7,500 | One site, full memo, 48-hour turnaround | Entry point, and the trust-builder |
| **Screen** | $2,000/mo | 50 sites/mo, portfolio ranking, alerts | Small developers |
| **Team** | $4,000–8,000/mo | Unlimited sites, monitoring, API access, 3 memos/mo | The core plan — most revenue |
| **Enterprise / API** | $50K–500K/yr | Bulk API, custom jurisdictions, SSO, SLA | Lenders, brokerages, grid-analytics platforms |
| **County / community** | $0 | Full access to their own jurisdiction's data | Neutrality, and free data-quality feedback |

**Pricing principles:**
1. **Anchor against the loss, never the alternative tool.** The comparison is an eight-figure write-off, not a $200/month SaaS subscription.
2. **Never sell time savings.** "Saves your analyst three weeks" is a $200/month pitch. "You are about to buy land you will never be allowed to use" is a $8,000/month pitch.
3. **The first memo can be free.** The memo is the product demo, and it is the cheapest possible customer acquisition cost.
4. **Do not discount; add scope.** Discounting a risk product signals the number is negotiable, which implies the number is soft.

### 10.4 Distribution — the accuracy page is the marketing

**[DECISION]** No paid acquisition in year one. The distribution engine is the public record itself.

| Channel | Mechanism |
|---|---|
| **The public ledger** | Predictions on pending applications are inherently newsworthy in the counties they concern. Local press and trade press cover the calls. |
| **The monthly accuracy report** | A recurring, citable artefact. Analysts and journalists cite whoever publishes the numbers. |
| **Jurisdiction profiles, public and indexed** | "[County] data centre approval rate" is exactly what a developer searches. Free profiles capture that search intent. |
| **Quarterly state-of-permitting report** | The industry has no permission benchmark. Publishing one makes Auspice the reference. |
| **Being right in public, loudly** | Correctly calling a contested denial three months early is worth more than any advertisement. |

The strategy is to become **the thing people cite**. Citations are distribution, and they compound like the ledger does.

### 10.5 Objection handling

| Objection | Response |
|---|---|
| "Your sample size is small." | "Correct, and we show you exactly how small, per jurisdiction. When it is too small we refuse to give a number. Ask any competitor to show you their sample size." |
| "Politics is unpredictable." | "Partly. But 3 of the last 4 denials, a new overlay ordinance and an election in eight months are all facts, not predictions. We are not forecasting the unpredictable part — we are pricing the knowable part that is currently ignored." |
| "We need national coverage." | "We cover 40 counties properly and abstain elsewhere. Would you rather have a real answer for the 40 counties that hold most of your pipeline, or a fabricated answer for 3,000?" |
| "What if you're wrong?" | "Sometimes we are, and we publish those. Over the next six months we will offer a fee-back guarantee once the calibration data supports it. We are not asking you to trust us — we are showing you the record." |
| "Legal will need to review this." | "Send them our methodology page and the disclaimer. We are explicit that this is a probabilistic opinion, not legal advice, and we never model individual officials." |

### 10.6 Partnerships, in priority order

1. **Grid-analytics companies (GridCare, Verse, Paces class).** They have the grid layer, the customers and the budget, and lack the political layer. **Highest-probability early licensing revenue.**
2. **Project-finance lenders.** The strategic prize — see §11.1, line 4.
3. **Land brokerages.** Distribution into every listing.
4. **Zoning-data vendors.** Buy their rules layer rather than rebuilding it; focus effort on the political layer where the differentiation is.
5. **An insurer or MGA.** Year two conversation, opened in year one so the data requirements are known early.

---

## 11. Business model and money

### 11.1 Five revenue lines, switched on in this order

Each line is unlocked by evidence produced by the previous one. The order is the strategy.

| # | Line | Price | Why it works | Turn on |
|---|---|---|---|---|
| **1** | **Per-site memo** | $2,500–7,500 | Entitlement consulting in Los Angeles runs $25K–$300K+; a single-site data centre certification study was priced at $25,000. Same-day, 5–50× cheaper. | **Day 30** |
| **2** | **Team subscription** | $2,000–8,000/mo | Unlimited screening plus monitoring alerts. **Monitoring is what makes it recurring.** | Month 2–3 |
| **3** | **API / data licence** | $50K–500K/yr | Brokerages, lenders and grid startups need the political layer and will not build it. Highest margin, wholesale. | Month 4–9 |
| **4** | **Lender diligence fee** | Per deal, mandated | **The strategic prize.** Become a standard diligence line item beside appraisal, title and environmental Phase I — markets created *entirely* by lenders requiring them. | Month 9–18 |
| **5** | **Risk transfer** | Premium share | Parametric permission-delay cover with a carrier. Converts a calibrated model from software revenue into a balance sheet. | Year 2–3 |

**Line 4 deserves emphasis.** Environmental Phase I assessments are a large, durable, recurring market that exists for one reason: **lenders require them.** Nobody buys one voluntarily. If a permission opinion becomes a financing condition, demand stops being a sales problem and becomes structural. That is the single highest-leverage objective in this entire plan, and it is why lender conversations start in month one even though the revenue arrives in month twelve.

### 11.2 Unit economics

**[ASSUMPTION]** all figures.

| Line item | Per memo | Per subscription month |
|---|---|---|
| Price | $5,000 | $4,000 |
| Marginal LLM + compute cost | $8–40 | $30–120 |
| Amortised data-acquisition cost | ~$150 | ~$150 |
| Human review time (v1, ~30 min) | ~$50 | ~$100 |
| **Gross margin** | **~95%** | **~93%** |

The margin is high because **the cost is in building the corpus once, not in serving an answer**. That is the definition of a data asset, and it is why the first ninety days must be spent on the corpus rather than the interface.

### 11.3 Revenue path — deliberately conservative

| Horizon | Assumption | Revenue |
|---|---|---|
| Day 30 | 3 paid pilots at $2,500 | **$7,500** — the point is proof of willingness to pay, not the amount |
| Month 6 | 12 teams at $4,000/mo | ~$576K ARR |
| Month 12 | 60 teams at $4,000/mo + 6 API deals at $200K | **~$4.1M ARR, no sales team** |
| Year 3 | Diligence-fee adoption by 2 lenders + 1 insurance partnership | $20M+ ARR, structurally defensible |

**The only number that matters in the first thirty days is the first one: did somebody actually pay.** Everything after it is extrapolation.

### 11.4 Cost structure, year one

| Line | Monthly | Note |
|---|---|---|
| Infrastructure | $85–400 | §7.5 |
| LLM inference | $400–2,500 | The real variable cost |
| Transcription | $50–300 | Scoped to top counties |
| Legal (entity, terms, E&O review) | ~$400 amortised | Do not skip — §15 |
| E&O insurance | ~$200–600 | Required before selling opinions |
| **Total** | **~$1,100–4,200/mo** | A business that can be run to profitability on the first three customers |

### 11.5 Honest market sizing

It would be easy to claim the geospatial analytics market — roughly **$93–123 billion in 2026**, with Asia-Pacific at about **27.5%** and India around **$6 billion** — and call that the opportunity. That would be dishonest. Auspice is not a geospatial analytics vendor.

The correct frame is **fees on de-risking capital expenditure**:

- Several trillion dollars of data centre capex, plus trillions more in energy, transmission and housing, must each pass a permission gate.
- Third-party diligence typically costs **5–20 basis points** of project cost.
- Therefore the addressable fee pool is in the **tens of billions of dollars annually**.
- **[ASSUMPTION]** realistically capturable within five years: **hundreds of millions**.

> **The honest ceiling:** as a data and software business this is a **$100M–$1B revenue** company. It becomes materially larger only if the insurance leg works — at which point the revenue is premium on trillions of dollars of exposure rather than subscriptions on a few thousand seats. **Plan for the first. Build so the second stays possible.**

---

## 12. The 30-day build plan, day by day

### Week 1 — Ground truth before pipelines

| Day | Task | Deliverable |
|---|---|---|
| 1 | Pick the 40 counties from announced pipeline data. Build the jurisdiction registry: boundaries, bodies, seats, election dates, home-rule status, civic platform. | `jurisdiction`, `decision_body`, `decision_maker` populated |
| 2 | **Hand-label every data centre application 2023–2026** in those counties: outcome, dates, votes. By hand. No automation. | ~300–800 labelled rows — **the most valuable asset created this month** |
| 3 | Postgres + PostGIS + pgvector schema and Alembic migrations. Parcel and boundary geometry loaded. | Database live, spatial joins working |
| 4–5 | Adapters for the two largest civic platforms. Content-addressed raw store on R2. | Agendas, minutes and staff reports flowing |
| 6–7 | Adapters three, four and five. Ordinance and code sources. Dead-letter queue and freshness dashboard. | Ingestion covering ≥90% of the 40 counties |

**Why day 2 comes before day 4:** without labels there is nothing to validate against, and a pipeline built before the labels exist will collect the wrong things. **Labels before pipelines. This is the most commonly inverted decision in projects like this.**

### Week 2 — From documents to a graph

| Day | Task | Deliverable |
|---|---|---|
| 8 | Document cascade: PyMuPDF → pdfplumber → Tesseract, with legibility gating and structural chunking | Text with page and character offsets preserved |
| 9 | Extraction schemas and prompts, versioned in git. Quote-verification step. | Facts landing with verified provenance |
| 10 | Golden test set of 100 hand-checked extractions. Regression suite in CI. | Extraction accuracy measurable, not assumed |
| 11 | Entity resolution: bodies, members, applicant clusters, parcels | The graph is connected rather than a pile of rows |
| 12 | Transcription pipeline for the top 10 counties | Hearing transcripts searchable and citable |

### Week 3 — The model, and the honest test

| Day | Task | Deliverable |
|---|---|---|
| 13 | Point-in-time feature builders, bi-temporal. Base-rate benchmark model. | The benchmark every later model must beat |
| 14 | XGBoost baseline. Temporal split. SHAP drivers. | First real signal reading |
| 15–16 | **The decision point.** Hierarchical NumPyro model. Calibration curve, Brier score, ECE, coverage on held-out 2026 decisions. | **KILL CRITERION: if it cannot beat the base rate, stop and change the wedge. Do not proceed on hope.** |
| 17–18 | Survival model for time-to-decision, with censoring and competing risks. Rule-change hazard model. | P10/P50/P90 timelines |
| 19–20 | Alternative-site ranker. Abstention rule. Explanation generation. | The full score object of §5.6 |

### Week 4 — Surfaces, the ledger, and revenue

| Day | Task | Deliverable |
|---|---|---|
| 21 | FastAPI endpoints. OpenAPI → generated TS types. | Typed API |
| 22 | Next.js app: site search, score view, evidence drawer, portfolio upload, MapLibre map | The working product |
| 23 | Memo generator: HTML → Chromium → PDF | The thing that gets paid for |
| 24 | Public jurisdiction profiles. Methodology, neutrality and data-source pages published. | SEO and trust surfaces live |
| **25** | **Score 25 pending applications. Publish the hashed ledger and the accuracy page.** | **The moat clock starts. Highest-priority day of the month.** |
| 26 | Free memos to 15 named prospects | Value delivered before asking |
| 27–29 | 40 conversations | Real objections, real pricing feedback |
| 30 | Close 3 paid pilots at $2,500 | **Revenue, or the thesis changes** |

### Explicitly deferred to month 3+

Multi-tenant permissions. Automated billing (invoice manually for the first ~20 customers). Onboarding flows. Branding. A second vertical. A second country. Mobile anything. SSO. Any feature that is not calibration, evidence, or the alternative-site ranker.

---

## 13. Month 2 to month 12

| Period | Focus | Milestone that proves it worked |
|---|---|---|
| Month 2 | Widen to 150 counties. Ship Monitor and alerts. | First subscription converted from a memo customer |
| Month 3 | Hierarchical model replaces the baseline in production | Calibration holds on counties with <5 historical decisions |
| Month 4 | First public monthly accuracy report | An outside party cites the Brier score |
| Month 5–6 | Second vertical: utility-scale solar and storage | Same graph, new use class — proves the architecture generalises |
| Month 6–7 | **Asia entry: Korea, Malaysia, Japan** | National-scale coverage in markets with dozens, not thousands, of jurisdictions |
| Month 8–9 | API and licensing motion | First $200K wholesale contract, ideally with a grid-analytics company |
| Month 9–10 | Lender channel | **One lender requires a Auspice memo as a financing condition** |
| Month 10–11 | Fee-back guarantee launched | Six months of calibration data supports a financial commitment |
| Month 11–12 | India entry via title and lender risk | Pilot with one NBFC or bank on stalled-project exposure |

**First hires, in order:** (1) a data engineer for ingestion breadth, (2) a former land-use planner or entitlement lawyer for domain truth and label quality, (3) an enterprise seller. **[DECISION]** The planner is hired before the seller. Label quality is the ceiling on everything, and a domain expert catches errors no engineer can see.

---

## 14. Risks and kill criteria

Stated honestly, with the failure condition written down in advance. Deciding the kill criteria *before* the emotional investment exists is the only way they get honoured.

| # | Risk | Severity | Honest assessment | Mitigation | Kill criterion |
|---|---|---|---|---|---|
| 1 | **The signal is genuinely weak** — outcomes are closer to random than the thesis assumes | **Fatal** | The single largest risk. Political decisions may be less predictable than the precedent data suggests. | Test on day 15–16, before building anything else | **Cannot beat the base rate by a meaningful margin on held-out 2026 decisions → stop. Change the wedge or the country.** |
| 2 | **Too few decisions per jurisdiction** | High | Many counties have 1–5 relevant decisions. Flat models will overfit badly. | Hierarchical pooling; abstain below the data-depth threshold | If >60% of target jurisdictions require abstention, the wedge is wrong |
| 3 | **Nobody pays** — the pain is real but the budget is not | High | Recognised risk, not eliminated. Diligence budgets exist, but new line items are slow. | Free memos as the demo; anchor against the loss; lender channel as the structural fix | Zero paid pilots from 40 qualified conversations → reposition to the lender or insurer buyer |
| 4 | **Extraction quality silently degrades** | High | Portals change layouts constantly. Failures are quiet. | Golden regression set in CI; quote verification; freshness SLAs; extraction-rate alerts | — |
| 5 | **A funded competitor moves first on calibration** | Medium | GatherGov is the realistic candidate. | Publish predictions in week four, not month six | — |
| 6 | **Access is restricted** — portals block scraping or add barriers | Medium | Real, and partially mitigated by law. | Respect `robots.txt`; use documented APIs; formal public-records requests; per-source rate limits | — |
| 7 | **Reputational attack** — "a tool to help developers beat communities" | Medium | A genuine and fair criticism if handled badly. | Free county and community tier; published neutrality charter; **never model individual officials' motives** | — |
| 8 | **Regime change invalidates history** — a new law resets the base rates | Medium | This is why the rule-change hazard model exists rather than being optional. | Model rule change explicitly; include election proximity as a feature; time-decay old decisions | — |
| 9 | **Legal exposure** — a customer loses money and blames the score | Medium | Manageable with correct structuring, fatal if ignored. | Opinion not advice; explicit disclaimers; E&O cover; intervals always shown; §15 | — |
| 10 | **Solo-operator bandwidth** | Medium | 30 days is genuinely tight for this scope. | The deferral list in §12; ruthless scope discipline | — |
| 11 | **India-specific execution risk** | High (for India only) | Land records are far less machine-readable than the headline digitisation figures suggest. | Do not enter India in month one. Enter via the lender and title-risk buyer, not the developer. | — |
| 12 | **The insurance leg never materialises** | Low severity | It is upside, not the base case. | The plan is profitable as software; insurance is optional. | — |

> The most likely way this fails is **risk #1**. That is precisely why day 15–16 is a hard, honest, pre-committed test rather than a checkpoint that can be rationalised past.

---

## 15. Legal, ethical, and regulatory

### 15.1 Opinion, not advice — the core structural choice

**[DECISION]** Auspice produces a **probabilistic opinion**, explicitly not legal advice, not an appraisal, and not a guarantee.

Implementation requirements:

- Every memo and every API response carries an explicit disclaimer.
- **Never say "will be approved".** Always a probability with an interval.
- Every score is stamped with `data_as_of` and `model_version`.
- Never advise on legal strategy, only on observed probability and precedent.
- Terms of service reviewed by a lawyer before the first sale — **not after**.
- **Errors and omissions insurance in place before selling opinions.** Non-negotiable.
- No unauthorised practice of law: describe what bodies have decided, never what the customer should legally do.

This mirrors the structure of credit rating agencies, whose ratings are opinions, and appraisers, whose valuations are opinions. **The precedent for a paid, accountable, non-advisory opinion is well established. Follow that pattern exactly.**

### 15.2 Data access legality

| Source type | Access basis | Rules followed |
|---|---|---|
| Agendas, minutes, staff reports | Published public record | `robots.txt` respected; documented APIs preferred; polite rate limits |
| Meeting audio and video | Public broadcast under open-meeting law | Audio-only extraction where possible; source URLs retained |
| Ordinances and codes | Public law | Municode and equivalent APIs where available |
| Parcel and assessor data | Public record, sometimes fee-bearing | Fees paid where required; licence terms honoured |
| Court and tribunal dockets | Public record | Jurisdiction-specific terms respected |
| Anything behind a paywall or licence | **Only with a licence** | No exceptions, ever |

Operating rules: identify the crawler honestly with a contact address; cache aggressively so the same page is never fetched twice; back off immediately on 429 or 503; use formal public-records requests where scraping is unwelcome. **The goal is to be the least burdensome consumer of these systems, because access is the business and burning it is unrecoverable.**

### 15.3 The ethical question, taken seriously

The fair criticism: *does this help capital defeat communities?*

The honest answer, and the design response:

1. **The same information is genuinely useful to both sides.** A county learns how its own process performs. A community group learns what the record actually shows. Both get it free.
2. **Better prediction reduces conflict rather than increasing it.** A developer who learns in week one that a site is hostile does not spend eighteen months fighting a community that never wanted the project. **The fights that are avoided are avoided for both sides.**
3. **Modelling institutions, never individuals.** Aggregate body behaviour and published voting records only. Never inferred motive. Never a prediction about a named person.
4. **Radical methodological transparency.** Method, sources and accuracy all published. Anyone can audit the claims.
5. **No advocacy, no expediting, no land positions.** Auspice never has a stake in an outcome.

**Hard lines, permanent:** no modelling of individual officials' motives; no inference of corruption; no "guaranteed approval" product; no paid influence on scores; no selling of community-organiser data to developers.

### 15.4 Jurisdiction-specific notes

| Region | Specific exposure | Response |
|---|---|---|
| **US** | Open-records and open-meeting laws are favourable. E&O and disclaimer discipline are the main needs. | Standard structure above |
| **EU / UK** | GDPR applies to named officials in decision records. Public-task and legitimate-interest bases must be documented. | Minimise personal data; document the lawful basis; honour erasure requests where applicable |
| **India** | **Defamation exposure is materially higher**, and land disputes can involve genuinely dangerous parties. Publishing that a specific parcel is encumbered carries real risk. | **Never publish claims about specific private parties.** Report only what the official record states, cite it precisely, and sell aggregate and jurisdictional risk rather than accusations about individuals |
| **Korea / Japan / Malaysia** | Local language records; personal-information laws; consultation records may be sensitive | Local-language extraction; conservative handling of named residents; aggregate reporting |

---

## 16. Metrics and instrumentation

What gets measured, and the target. **[ASSUMPTION]** on all targets — they are commitments, not observations.

### 16.1 Model quality — the metrics that determine whether the company is real

| Metric | Target | Why |
|---|---|---|
| Brier score vs. base rate | 25%+ improvement | The single honest test of whether there is signal |
| Expected Calibration Error | < 0.08 | The published promise |
| 80% interval coverage | 76–84% | Intervals must mean what they say |
| Time-to-decision MAE | < 25% of median duration | Duration drives whether a project pencils |
| Abstention precision | > 0.85 | Proves abstention is intelligent, not lazy |
| AUC on held-out year | — | Tracked, but calibration matters more than ranking |

### 16.2 Data quality — monitored more closely than uptime

| Metric | Target |
|---|---|
| Source freshness within SLA | > 98% of sources |
| Extraction success rate | > 92% of legible documents |
| Quote-verification pass rate | > 99% (below this, extraction is unsafe) |
| Entity-resolution precision | > 0.97 |
| Manual-review corrections per 100 extractions | < 3, trending down |
| Dead-letter queue depth | Drained weekly to zero |

### 16.3 Product and commercial

| Metric | Target | Note |
|---|---|---|
| Time to first score | < 90 seconds | |
| Memo generation time | < 5 minutes | |
| Evidence-drawer open rate | > 40% of score views | **The best single proxy for trust.** Customers who check the evidence are the ones who renew. |
| Free memo → paid conversion | > 20% | |
| Sites screened per customer per month | > 25 | Low usage means it is a curiosity, not a workflow |
| Logo retention, month 6 | > 90% | Monitoring makes churn structurally low |
| Published predictions | ≥ 25/month, monotonically increasing | **The moat metric. Never allowed to stall.** |

### 16.4 The single most important dashboard

One page, checked daily:

1. Predictions published, cumulative
2. Predictions resolved, and the running Brier score
3. Sources within freshness SLA, as a percentage
4. Quote-verification pass rate, last 24 hours
5. Paying customers, and revenue

> If lines 1 and 2 are healthy, the company is compounding something that cannot be bought. **Nothing else on any dashboard matters more than those two lines.**

---

## 17. Open questions and known unknowns

Written down rather than glossed over, because pretending these are settled is how plans fail quietly.

| # | Question | Why it matters | How it gets resolved |
|---|---|---|---|
| 1 | **Is the signal strong enough?** | Everything depends on it | Day 15–16 test on held-out 2026 decisions |
| 2 | How thin can a jurisdiction be before pooling stops helping? | Determines coverage claims | Measure abstention rate by data depth; publish it |
| 3 | Do transcripts add real predictive lift over documents alone? | Justifies the transcription cost and the differentiation claim | Ablation study: model with and without transcript features |
| 4 | Will developers pay, or only lenders? | Determines the entire GTM sequence | 40 conversations in days 27–30 |
| 5 | Is per-memo or subscription the right primary motion? | Pricing architecture | Offer both in the pilots; watch which is chosen unprompted |
| 6 | How fast do the five civic platforms change their layouts? | Sets true maintenance cost | Instrument adapter breakage from day one |
| 7 | Does the model transfer to solar and storage without re-architecture? | Tests whether this is a platform or a point solution | Month 5–6 second vertical |
| 8 | Which Asian market is genuinely first? | Korea, Malaysia and Japan all have live pain | Assess data accessibility and language cost before committing |
| 9 | Is the India entry point the lender, the title insurer, or the state government? | Wrong entry point wastes a year | Month 11–12 pilot; do not guess earlier |
| 10 | Will an insurer actually underwrite on this model? | Determines whether the ceiling is $1B or far larger | Open the conversation in year one; expect a two-year cycle |
| 11 | **Is the name "Auspice" clear for use?** | A company-name conflict scan on 26 August 2026 found no collision in real estate, infrastructure, govtech or risk. Six earlier candidates were rejected on conflict: **Verdict** (GlobalData's B2B media brand), **Quorum** (Quorum Analytics — public-affairs software, directly adjacent), **Assent** (Assent Inc — regulatory compliance), **Precedent** (legal and insurance AI), **Bellwether** (Google X geospatial climate risk), **Entitle** (acquired by BeyondTrust). **A formal trademark search has NOT been done.** | USPTO, EUIPO and India TM Registry searches in the relevant classes, plus domain acquisition, before any public launch |
| 12 | Should the methodology be fully open-sourced? | Maximum trust vs. maximum imitation | Publish the method; keep the corpus, the labels and the ledger proprietary. **[DECISION]** — the asset is the data and the record, never the algorithm |

---

## 18. Sources

Every factual claim in this document traces to one of these. Grouped by region. All accessed August 2026.

### 18.1 United States — blocked capital and opposition

- Data Center Watch, blocked and delayed projects report — https://www.datacenterwatch.org/report
- Business Roundtable, permitting reform: **650+ projects stalled, $1.5T investment held back, $1.7–2.4T GDP impact** — https://www.businessroundtable.org/bipartisan-permitting-reform-would-help-america-build-faster
- Wood Mackenzie via WTVB: **stalled permits threaten $121B in wind and solar; ~7 GW stalled on federal land in 2025** — https://wtvbam.com/2026/06/29/stalled-us-permits-threaten-121-billion-in-wind-and-solar-investment-report
- Sabin Center / Columbia Law, opposition to renewable energy facilities, June 2025 edition: **395 local restrictions across 41 states** — https://climate.law.columbia.edu/content/opposition-renewable-energy-facilities-united-states-june-2025-edition
- Utility Dive on the Sabin report — https://www.utilitydive.com/news/local-opposition-renewable-energy-projects-growing-sabin-report/718817/
- Hastings Environmental Law Journal, restrictive siting: **~15% of US counties effectively ban utility-scale wind or solar** — https://repository.uclawsf.edu/cgi/viewcontent.cgi?article=1663&context=hastings_environmental_law_journal
- World Resources Institute, restrictive siting laws — https://www.wri.org/insights/clean-energy-restrictive-siting-laws
- DCD, community acceptance as the toughest bottleneck — https://www.datacenterdynamics.com/en/opinions/why-data-center-projects-are-getting-blocked-and-how-developers-can-improve-community-buy-in/
- Global Data Center Hub, permitting and zoning as the largest delay source — https://www.globaldatacenterhub.com/p/permitting-zoning-and-environmental
- Data Center Knowledge, plays that de-risk delays — https://www.datacenterknowledge.com/data-center-construction/building-data-centers-faster-plays-that-de-risk-delays
- Capstone, investor risk from local opposition and Dillon's Rule dynamics — https://capstonedc.com/insights/data-center-investors-face-growing-risk-from-local-opposition/

### 18.2 United States — 2026 moratoria and denials (evidence the trend is accelerating)

- Boone County, Indiana — https://boonecounty.in.gov/2026/06/15/19190/
- Linn County, Iowa — https://www.linncountyiowa.gov/m/newsflash/Home/Detail/4487
- Sarasota County, Florida — https://www.yourobserver.com/news/2026/jul/11/data-centers-rejected-sarasota-county/
- Newton County, Georgia, Resolution R-040726b — https://www.newtoncountyga.gov/DocumentCenter/View/7830/Resolution-R-040726b
- Fort Worth, Texas, zoning commission — https://fortworthreport.org/2026/07/08/zoning-commissioners-deny-data-center-rules-return-ordinance-to-fort-worth-city-council/
- Cheyenne, Wyoming, moratorium rejected (opposition is not uniform) — https://capcity.news/community/city/2026/05/27/cheyenne-city-council-rejects-data-center-moratorium/

### 18.3 United States — jurisdictional fragmentation and housing

- National Zoning Atlas methodology: **~33,000 zoning jurisdictions; 740,000+ pages of code; ~6,700 mapped (~20%)** — https://www.zoningatlas.org/how
- Hartford Courant, how zoning reshaped development — https://www.courant.com/2025/05/04/how-zoning-quietly-reshaped-the-world/
- Council of Economic Advisers, permitting requirements and housing cost — https://bidenwhitehouse.archives.gov/cea/written-materials/2024/08/13/reforming-permitting-requirements-to-lower-the-cost-of-building-new-housing-and-increase-housing-affordability/
- WGI, **7.4 months average delay from organised opposition** — https://publications.wginc.com/affordable-housing
- Washington State Legislature, **~$46,000 per home in delay cost** — https://app.leg.wa.gov/committeeschedules/Home/Document/290020

### 18.4 United States — demonstrated willingness to pay

- Boone County / Whitestown data centre certification proposal: **$25,000 for a single-site study** — https://whitestown.in.gov/wp-content/uploads/2021/12/Data_Center_Certification_Boone_County_10.13.2021_Final_Proposal.pdf
- JDJ Consulting, Los Angeles entitlement costs: **$25K–$300K+** — https://jdj-consulting.com/entitlement-costs-in-los-angeles-2025-a-detailed-guide/
- KPMG site selection and project development — https://kpmg.com/us/en/capabilities-services/advisory-services/capital-advisory/infrastructure-advisory/site-selection-project-development.html
- CBRE site selection and location strategy — https://www.cbre.com/services/plan-lease-and-occupy/site-selection-and-location-strategy
- UNC School of Government, perspectives on the site-selection process — https://ced.sog.unc.edu/2025/11/07/perspectives-on-the-business-location-and-site-selection-process/

### 18.5 Competitors

- GatherGov, land entitlement guide — https://gathergov.com/articles/land-entitlement-guide
- Zoneomics launches Bassett.ai — https://www.zoneomics.com/blog/zoneomics-launches-bassett.ai-the-ai-operating-system-for-zoning-intelligence
- Gridics zoning data API — https://gridics.com/zoning-data-api/
- Shovels — https://www.shovels.ai/blog/
- GridCare raises $64M — https://siliconangle.com/2026/05/15/gridcare-raises-64m-speed-ai-data-center-projects/
- Verse raises $54M, Nvidia-backed — https://www.bloomberg.com/news/articles/2026-06-18/nvidia-backed-startup-aims-to-speed-ai-data-center-grid-connection
- Paces — https://www.datacenterdynamics.com/en/company/paces
- Enverus acquires Pearl Street Technologies — http://enverus.com/newsroom/undo-the-queue-enverus-acquires-pearl-street-technologies-to-solve-for-a-more-reliable-resilient-grid

### 18.6 Capital scale and grid

- Dell'Oro: **data centre capex surpasses $3T by 2030** — https://www.delloro.com/news/ai-buildout-maintains-momentum-as-data-center-capex-surpasses-3-trillion-by-2030/
- McKinsey via DCD: **up to $6.7T** — https://www.datacenterdynamics.com/en/news/ai-could-drive-67-trillion-investment-in-data-centers-maybe-claims-mckinsey/
- JPMorgan via DCD: **$5T global data centre and AI infrastructure spend** — https://www.datacenterdynamics.com/en/news/jpmorgan-global-data-center-and-ai-infra-spend-to-hit-5-trillion-demand-for-compute-remains-astronomical/
- IEA, Energy and AI: **945 TWh by 2030** — https://www.iea.org/reports/energy-and-ai/executive-summary
- Berkeley Lab queue data: **2,061 GW in interconnection queues; ~13% completion rate** — https://emp.lbl.gov/queues
- FERC Docket RM26-4 — https://www.ferc.gov/rm26-4
- BCG, **$15T infrastructure gap** — https://www.bcg.com/publications/2026/infrastructure-investments-in-an-uncertain-world
- McKinsey, bridging global infrastructure gaps: **$3.3T/yr, ~60% in emerging markets** — https://www.mckinsey.com/~/media/mckinsey/business%20functions/operations/our%20insights/bridging%20global%20infrastructure%20gaps/bridging-global-infrastructure-gaps-in-brief.pdf
- WEF, **$97T need, $18T gap** — https://www.weforum.org/stories/2019/01/infrastructure-around-the-world-failing-heres-how-to-make-it-more-resilient
- MarketScale, energy transition **$3.17T in 2026; 1,650 GW stalled by grid backlogs** — https://www.marketscale.com/industries/energy/energy-transition-market-reaches-317-trillion-in-2026-as-grid-connection-backlogs-stall-1650-gw-of-capacity

### 18.7 India

- Assetly, India property dispute crisis: **66% of civil cases are property disputes**; NJDG 4,87,54,355 pending, 1,10,68,892 civil (14 Apr 2026) — https://assetlyhq.com/blog/india-property-dispute-crisis
- Drishti IAS, Centre for Policy Research 66% figure — https://www.drishtiias.com/current-affairs-news-analysis-editorials/news-editorials/17-07-2026/print/manual
- Reuters on the Daksh study: **conflicts over land stall projects worth billions** — https://www.reuters.com/article/world/conflicts-over-land-in-india-stall-projects-worth-billions-of-dollars-report-idUSKBN13B073
- The Hindu, conclusive land titling: World Bank data and **NITI Aayog — land disputes average 20 years** — https://www.thehindu.com/news/national/the-hindu-explains-why-does-india-need-conclusive-land-titling/article33891718.ece
- CPR-LRI, understanding land conflict: **~30% of Supreme Court land litigation** — https://cprindia.org/understanding-land-conflict-in-india-and-suggestions/
- Stanford Law / RRI & ISB: **₹12 trillion of investment impacted; >25% of 80 high-value projects stalled** — https://law.stanford.edu/publications/the-extent-causes-and-implications-for-indias-land-policies-story-of-uttar-pradesh
- Business Standard: **₹10.79 lakh crore locked in 1,626 stalled housing projects, ~432,000 homes** — https://www.business-standard.com/finance/personal-finance/10-lakh-crore-stuck-in-stalled-housing-projects-warns-investment-advisor-125090900554_1.html
- PropEquity: **~2,000 projects, 5.08 lakh units, 42 cities** — https://www.business-standard.com/industry/news/nearly-2-000-housing-projects-stalled-across-42-cities-propequity-124081500404_1.html
- Moneycontrol, NCR 240,610 units (₹1.81 lakh cr) and MMR 128,870 units (₹1.84 lakh cr) — https://www.moneycontrol.com/news/indias-most-delayed-residential-projects/
- CNBC-TV18, SWAMIH II ₹15,000 cr — https://www.cnbctv18.com/real-estate/indias-stalled-housing-projects-are-slowly-reviving-through-court-rulings-funding-and-new-developers-ws-l-19902121.htm
- NDTV Profit on MoSPI, June 2026: **1,847 projects, ₹4.92 lakh crore cost overrun** — https://www.ndtvprofit.com/economy/indias-mega-infrastructure-push-faces-rs-4-92-lakh-crore-cost-overrun-across-1-900-projects-mospi-report-11834645
- MoSPI flash report: **average time overrun 36.59 months**; causes include land acquisition, forest and environmental clearances, technical approval and encroachment — https://ipm.mospi.gov.in/ReportPage/ViewPdf?id=57&path=Content%5CArchiveReport%5Cflash%5C2023-24%5CFR_dec_2023.pdf
- PRS India, land records and titles: **mutation 47%, digitally signed RoR 28%, cadastral maps 46%** — https://prsindia.org/policy/analytical-reports/land-records-and-titles-india
- PIB, DILRMP progress claim (~95% digitisation of records of rights) — https://www.pib.gov.in/PressReleasePage.aspx?PRID=2068408
- DILRMP MIS dashboard — https://dilrmp.gov.in/
- Rajya Sabha Unstarred Question 3966, 27 March 2026 — https://www.sansad.in/getFile/annex/270/AU3966_vRU3NA.pdf?source=pqars
- Yahoo Finance, **India's stranded renewable projects double to >50 GW** — https://sg.finance.yahoo.com/news/indias-stranded-renewable-projects-double-103715673.html
- Construction World, land acquisition delays in solar; 147 GW connectivity granted; **Great Indian Bustard zones up to 48 months** — https://www.constructionworld.in/energy-infrastructure/power-and-renewable-energy/delays-in-solar-power-projects-due-to-land-acquisition-issues/69668
- Saur Energy, **CERC: land and approval delays are not grounds to exit an awarded 200 MW wind project** — https://www.saurenergy.com/solar-energy-news/land-approval-delays-cant-be-grounds-to-exit-awarded-wind-project-cerc-12054155
- Lexology, LARR versus the 500 GW target — https://www.lexology.com/library/detail.aspx?g=d619fee1-29d0-4387-baf1-52b704efb82e
- S&R Associates, encumbrance and agricultural-conversion diligence for clean energy land — https://www.snrlaw.in/use-of-land-for-clean-energy-projects-in-india/
- ASSOCHAM–PwC, 28 May 2026: simplified land and power approvals needed — https://pop.panurgyoem.com/expert-time/ASSOCHAMPwC-Report-Calls-for-Simplified-Land-and-Power-Approvals-to-Boost-IT-Data-Centre-Investments-21-14219
- Economic Times, **>$100B announced; strategic land-buying wave** — https://m.economictimes.com/industry/services/property-/-cstruction/digital-infrastructure-demand-drives-new-wave-of-strategic-land-buying/amp_articleshow/131467447.cms
- Economic Times / Axis Capital: **3–3.6 GW by 2030, 7–8 GW by 2035; ₹44–54 cr per MW; ~18-month power sanction** — https://m.economictimes.com/tech/artificial-intelligence/indias-data-centre-capacity-may-reach-3-3-6-gw-by-2030-hyperscalers-to-drive-growth-axis-capital/amp_articleshow/132800861.cms
- DCD, **state governments as the new kingmakers** — https://www.datacenterdynamics.com/en/opinions/state-governments-the-new-kingmakers-in-indias-hyperscale-data-center-race
- RE24, draft National Data Centre Policy 2025 and the Supreme Court August 2025 environmental-clearance ruling — https://re24.energy/india-data-centre-boom-digital-infrastructure/
- Kathmandu Post (regional comparison): Nepal's 17 pride projects may take 41 years — https://kathmandupost.com/money/2026/03/16/nepal-s-17-pride-projects-may-take-41-years-to-finish-warns-world-bank

### 18.8 Asia excluding India

- Reuters, Malaysia's resource anxiety: **$35B into Johor post-Singapore moratorium; 8× growth toward 7,000 MW; February 2026 Iskandar Puteri protests "first of their kind"; a 50 MW data centre uses the water of 2,200 households and the power of 22,000** — https://www.reuters.com/world/asia-pacific/malaysias-resource-anxiety-tests-asias-fastest-data-centre-build-out-2026-07-24
- Jakarta Post syndication — https://www.thejakartapost.com/business/2026/07/27/malaysias-resource-anxiety-tests-asias-fastest-data-center-build-out
- Malay Mail, **Johor Menteri Besar: no approval for high-water data centres** — https://www.malaymail.com/news/malaysia/2026/03/10/johor-mb-onn-hafiz-no-approval-for-data-centres-with-high-water-demand-welfare-comes-first/212089
- The Diplomat, water rights and data centres in Johor — https://thediplomat.com/2026/04/whose-water-powers-the-cloud-data-centers-and-the-right-to-water-in-johor/
- Aliran, civil-society call for a national data centre pause — https://m.aliran.com/civil-society-voices/why-malaysia-must-pause-its-data-centre-boom
- Seoul Economic Daily, **patchwork rules stall Korean data centres; Geumcheon-gu requires majority consent of residents within 200 m** — https://en.sedaily.com/opinion/2026/08/26/patchwork-rules-stall-data-centers-threatening-koreas-ai
- Korea Herald, **all 25 Seoul district heads unanimous, August 2026** — https://www.koreaherald.com/article/10840432
- Korea Herald, June 2026 local elections and siting politics — https://www.koreaherald.com/article/10766206
- Japan Times, urban opposition; data centres zoned as offices rather than industrial; **residents sued a permit inspector in March 2026** — https://www.japantimes.co.jp/news/2026/07/18/japan/society/japan-data-centers-opposition/
- Japan Times, data centre pushback — https://www.japantimes.co.jp/environment/2026/06/21/data-center-pushback/
- Japan Today, opposition in cramped urban Japan — https://japantoday.com/category/tech/opposition-to-data-centres-grows-in-cramped-urban-japan
- DC Byte, community pushback as a growing APAC risk — https://www.dcbyte.com/news-blogs/community-pushback-is-a-growing-risk-for-apac-data-centre-development/
- JLL data centre outlook: **APAC 32 → 57 GW by 2030, ~12% CAGR** — https://www.jll.com/en-us/insights/market-outlook/data-center-outlook
- Cushman & Wakefield via DCD: **~$1T APAC asset value by 2030, requiring ~$280B capex** — https://www.datacenterdynamics.com/en/news/apac-data-center-asset-values-could-reach-1-trillion-by-2030-cushman-wakefield/
- CBRE, 2026 Asia-Pacific data centre trends and outlook — https://www.cbre.com/insights/reports/2026-asia-pacific-data-centre-trends-and-outlook
- McKinsey, Asia-Pacific as the next engine of data centre demand — https://www.mckinsey.com/featured-insights/future-of-asia/countries-and-regions/southeast-asia/southeast-asia-perspectives/beyond-the-spillover-asia-pacific-the-next-engine-of-data-center-demand

### 18.9 Europe and the United Kingdom

- European Commission, referrals to the CJEU with financial sanctions over RED III permitting transposition — https://ec.europa.eu/commission/presscorner/api/files/document/print/en/ip_26_839/IP_26_839_EN.pdf
- European Commission, accelerating permitting for renewable energy (two-year cap) — https://reforms-investments.ec.europa.eu/accelerating-permitting-renewable-energy_en
- SolarPower Europe, EU permitting state of play — https://www.solarpowereurope.org/insights/thematic-reports/eu-renewable-energy-permitting-state-of-play
- IEA, support to accelerating renewable energy permitting — https://www.iea.org/reports/iea-support-to-accelerating-renewable-energy-permitting-arpe
- WindEurope, **Germany's Overriding Public Interest reform → 15 GW of onshore wind permitted in 2024, roughly 7× the level five years earlier** — https://windeurope.org/news/simplify-and-accelerate-is-the-way-forward-europe-still-takes-too-long-to-permit-wind-farms/
- Net Zero Pathfinders, onshore wind permitting in Germany (5–10 year consent timelines) — https://www.netzeropathfinders.com/best-practices/onshore-wind-permitting-germany
- Realyse, UK planning bottlenecks: **12–18 month reserved-matters discharge; completions outside the top 50 builders down 16% YoY to Q1 2026** — https://www.realyse.com/blogs/planning-bottlenecks-uk-housing-pipeline-2026
- The Guardian, "sludge in the system": UK housing delivery obstacles — https://www.theguardian.com/business/2026/apr/26/sludge-in-the-system-myriad-problems-stymie-labours-15m-new-homes-pledge

### 18.10 Market sizing (context only — see §11.5 for why these are not claimed as TAM)

- GlobeNewswire, geospatial analytics forecasts by region — https://www.globenewswire.com/news-release/2026/04/22/3279192/28124/en/geospatial-analytics-market-trends-and-global-growth-forecasts-broken-down-by-region-2019-2032.html
- Fortune Business Insights, geospatial analytics market — https://www.fortunebusinessinsights.com/geospatial-analytics-market-102219
- Research and Markets, geospatial analytics **$122.96B (2026) → $243.83B (2030)** — https://www.researchandmarkets.com/reports/5767473/geospatial-analytics-market-report

---

## 19. Appendices

### 19.1 Glossary

Every term used in a non-obvious way in this document.

| Term | Definition |
|---|---|
| **Permission** | The full set of consents a project needs from public bodies and the public before construction can lawfully begin. Broader than "permit": it includes discretionary votes, moratoria, appeals and litigation. |
| **Permission risk** | The probability that a project will not receive those consents, or will receive them so late that the economics fail. The variable this company prices. |
| **Entitlement** | US industry term for the process of obtaining land-use approval (rezoning, special-use permits, variances) before building permits. |
| **By-right** | A use already permitted under existing zoning, requiring only ministerial approval. Low permission risk by definition. |
| **Discretionary approval** | An approval where a body may lawfully say no even if all technical criteria are met. This is where nearly all of the variance lives. |
| **Moratorium** | A temporary local ban on accepting or deciding applications of a given type. The single most destructive event for a project timeline. |
| **Special-use permit / conditional-use permit** | A discretionary permission for a use allowed only under specified conditions. |
| **Variance** | Relief from a specific dimensional or use requirement, granted by a board of adjustment or appeals. |
| **Interconnection queue** | The waiting list to connect a generator or large load to the transmission grid. Berkeley Lab tracks ~2,061 GW queued with a ~13% historical completion rate. |
| **Dillon's Rule** | US legal doctrine under which local governments hold only powers expressly granted by the state. Determines whether a state can pre-empt local opposition — a first-order variable in the model. |
| **Home rule** | The opposite doctrine: local governments hold broad autonomous power. Higher permission risk, because local politics is decisive. |
| **Permission Graph** | This company's core dataset: a normalised graph of every body that can say no, its members, its published decisions, its stated positions, its procedural rules and its calendar. |
| **Jurisdiction registry** | Stage 0 of the pipeline: the authoritative list of jurisdictions in scope, with boundaries, governing bodies, election calendars and data-source adapters. |
| **CivicAdapter** | The Python `Protocol` every source connector implements, so a new civic platform can be added without touching the pipeline. |
| **Freshness SLA** | The maximum permitted staleness for each data type, published per jurisdiction. A commitment, not an aspiration. |
| **Calibration** | Whether stated probabilities match observed frequencies. If the model says 70% and the event happens 70% of the time, it is calibrated. The central product claim. |
| **Brier score** | Mean squared error of probabilistic forecasts. Lower is better. Target: at least 25% better than the base rate. |
| **ECE (Expected Calibration Error)** | Average gap between predicted probability and observed frequency across probability bins. Target: below 0.08. |
| **Credible interval** | The Bayesian analogue of a confidence interval. An 80% credible interval should contain the truth ~80% of the time; target coverage 76–84%. |
| **Partial pooling / hierarchical model** | Statistical structure that lets a data-poor jurisdiction borrow strength from similar jurisdictions, while data-rich ones rely on their own history. The reason coverage can exceed data depth. |
| **Abstention** | The product's refusal to answer when evidence is too thin. Triggered when fewer than 3 comparable decisions exist, pooling weight exceeds 0.8, and the credible interval is wider than 0.35. |
| **Prospective ledger** | A public, hash-committed record of predictions made *before* outcomes are known. The only credible proof of forecasting skill, and the one asset a competitor cannot buy. |
| **Base rate** | The unconditional approval rate for a class of application. The benchmark any model must beat to be worth anything. |
| **Evidence drawer** | The UI surface that shows the exact quoted source text behind every factor in a score. The mechanism that converts a number into something defensible in a credit memo. |

### 19.2 Feature dictionary

The model's input features, grouped. **[ASSUMPTION]** — the specific predictive weight of each is unknown until the day 15–16 test.

**A. Jurisdiction structure**
- Dillon's Rule vs. home rule; state pre-emption statutes in force
- Governing body size, composition, term length, at-large vs. district seats
- Required vote threshold (simple majority, supermajority, unanimity)
- Whether a planning commission recommendation is binding or advisory
- Statutory decision deadlines and whether they are enforced in practice

**B. Decision history**
- Base approval rate for the use class, 5-year and 10-year windows
- Approval rate conditional on organised opposition appearing
- Median and p90 time from application to decision
- Rate of deferrals and continuances (the quiet killer of timelines)
- Rate of approval with conditions so onerous the applicant withdraws

**C. Political composition and trajectory**
- Individual member voting records on comparable applications
- Stated public positions from transcripts and minutes
- Months until the next election for each seat
- Turnover rate of the body over the last three cycles
- Whether any current member campaigned on the issue

**D. Opposition signal**
- Count and trend of objections filed on comparable applications
- Presence of an organised group; whether it has retained counsel
- Historical success rate of that specific group
- Local press volume and sentiment on the use class
- Prior litigation on comparable applications in the jurisdiction

**E. Application characteristics**
- Use class and requested relief (rezoning, special use, variance, combination)
- Site size, adjacency to residential, adjacency to protected land
- Water and power demand relative to local capacity — the dominant 2026 objection theme in Johor, Korea and increasingly the US
- Applicant identity and local track record
- Whether a community benefit agreement is offered

**F. Rule-change risk**
- Live moratorium, or a moratorium proposed in the last 12 months
- Comprehensive plan or zoning code update in progress
- Count of comparable jurisdictions in the same state that restricted this use in the last 24 months (the contagion feature)
- Pending state legislation that would pre-empt or empower the locality

### 19.3 What a customer actually receives

For a single site query, the deliverable is:

1. **A probability** — approval probability with an 80% credible interval, or an explicit abstention.
2. **A time distribution** — p10, p50 and p90 months to decision, not a single date.
3. **A rule-change probability** — the chance the rules themselves change before a decision is reached.
4. **The top drivers** — ranked factors, each with its direction and magnitude.
5. **The evidence drawer** — the verbatim quoted source behind every factor, with a link and a retrieval date.
6. **The comparable set** — the specific prior decisions the estimate is built on, so the reasoning can be audited.
7. **The calibration context** — how the model has historically performed on this jurisdiction class and this use class.
8. **A dated, versioned PDF memo** — citable in a credit committee, with the model version stamped on it.

### 19.4 The five sentences that define this company

1. **Every large physical project on earth is priced for cost, engineering and demand — and guesses at permission, which is the largest single source of variance.**
2. **Permission risk is knowable, because the bodies that decide it publish their decisions, their members, their rules and their calendars — in tens of thousands of incompatible places.**
3. **The product is a calibrated probability and a time distribution for a specific project at a specific location, with the evidence attached.**
4. **The moat is not the model and not the data — it is the public, hash-committed record of predictions made before outcomes were known, which no amount of capital can retroactively purchase.**
5. **The company is worth building only if the day 15–16 signal test passes; if it fails, it must be killed, and this document says so in writing.**

---

*End of document.*
