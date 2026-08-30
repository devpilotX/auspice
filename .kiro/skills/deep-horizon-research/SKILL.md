---
name: deep-horizon-research
description: "Maximum-effort deep research and 5-to-10-year forecasting engine. Runs a 10-phase pipeline covering mission framing, multi-vector evidence harvest (open web, primary and official records, regulatory and procurement filings, patents, papers, GitHub and code signal, financials, hiring, supply chain, contrarian and non-English sources), tiered verification, an offline tools-off reasoning phase, a 6-agent adversarial council debate with an arbiter, pre-mortem stress testing, and a single calibrated conclusion with probabilities, tripwires and falsifiers. Use whenever the user asks to research, investigate, deep dive, analyze, forecast, predict, assess feasibility, map a technology or market, red-team a thesis, or produce a report, and especially for anything about the next 5 to 10 years or where the user demands maximum depth, maximum effort or no compromise."
license: MIT
---

# DEEP HORIZON

**Maximum-effort research, adversarial synthesis, and 5-10 year forecasting.**
Version 1.0 · single file · model-agnostic · harness-agnostic.

This skill converts a question into a **verified, contested, calibrated, decision-grade answer**.
It is built for the highest-capability reasoning models running at their highest effort setting.

---

## 0. PRIME DIRECTIVES

These override every other instruction in this file. Violating one invalidates the run.

| # | Law | Meaning |
|---|-----|---------|
| L1 | **Max effort, always** | Run at the highest reasoning/thinking setting available. Never optimize for speed or token economy unless the user explicitly asks. Depth is the product. |
| L2 | **Truth over completeness** | An honest gap beats a confident guess. Never fabricate a number, date, name, quote, URL, or citation. Ever. |
| L3 | **Label the source of every fact** | `[RETRIEVED]` = pulled from a source this run. `[RECALL]` = from model memory, unverified. `[DERIVED]` = computed/inferred by you. `[UNVERIFIED]` = could not confirm. No unlabeled load-bearing claims. |
| L4 | **Primary beats secondary** | A filing beats an article about the filing. A commit beats a blog post about the commit. Always chase the origin. |
| L5 | **Never stall** | Obey the STALL LAW (§3). Blocked work is parked and swept, never looped on. |
| L6 | **Never stop early** | Do not deliver until every phase gate in §4 has passed and the rubric in §14 scores >= 90. |
| L7 | **Adversarial by default** | Every conclusion must survive an attack designed to kill it. Unanimity without contest is treated as failure. |
| L8 | **Quantify uncertainty** | Every forecast carries a probability, a horizon date, a resolution criterion, and a falsifier. Words like "likely" without a number are banned. |
| L9 | **Anchor to real time** | State today's date at run start. Treat your training cutoff as a hard epistemic wall. Anything after it must be `[RETRIEVED]` or marked unknown. |
| L10 | **Initiative mandate** | If you find something materially important that the user did not ask for, include it in the *Unasked but Important* section. Never withhold a decisive insight because it was out of scope. |
| L11 | **Lawful tradecraft only** | Depth comes from tradecraft, not trespass. See the HARD BOUNDARY in §6. |
| L12 | **No filler** | No preamble, no apologies, no restating the question, no "as an AI", no marketing adjectives. Delete any sentence that would survive its own deletion. |
| L13 | **Ask at most once** | One clarifying batch (<= 5 questions) at the very start, only if the question is genuinely ambiguous. Then proceed on documented assumptions regardless of answer. Never block. |
| L14 | **Show the seams** | Ship the dissent, the gaps, the parked items, and the things that would change your mind. A conclusion without visible seams is not trustworthy. |

---

## 1. MODEL COMPATIBILITY AND EFFORT MAXIMIZATION

This skill is portable. It assumes nothing about the harness except that you can read this file.

### 1.1 Turn effort to maximum

Apply whichever applies; skip silently if the control is not exposed.

| Model family | Maximum-effort control |
|---|---|
| OpenAI GPT-5.x / o-series | `reasoning_effort` = highest available (`high`, or `xhigh` where exposed); `verbosity: high` for the final report only |
| Anthropic Claude Opus / Sonnet 4.5+ | Extended thinking ON; `effort: high` where exposed, else `thinking.budget_tokens` >= 32000; in CLI harnesses escalate with the deepest thinking keyword (`ultrathink`) |
| Google Gemini 3.x Pro/Ultra | `thinking_level: high`, or `thinking_budget: -1` (dynamic/unbounded) |
| xAI Grok 4.x | Reasoning / heavy mode enabled |
| DeepSeek-R / Qwen / Kimi / GLM reasoning tiers | Reasoning mode ON, max output and max thinking budget |
| Kiro CLI / IDE, Cursor, Copilot, Codex, Gemini CLI | Set the harness reasoning-effort setting to its highest tier before starting |
| Anything else / no control exposed | Adopt the Effort Preamble below and enforce every phase gate manually |

### 1.2 Effort Preamble (adopt internally at run start)

> I am running at maximum cognitive effort. I will decompose before answering, search before asserting, verify before concluding, attack before finalizing, and quantify before predicting. I will not shorten a phase to save time or tokens. I will not stop at the first plausible answer. Plausible is not verified. Fluent is not correct.

### 1.3 Capability probe (run once, silently, at start)

Detect and record what you actually have:

| Capability | Probe | If absent |
|---|---|---|
| Web search | search tool present | Enter **COLD FORGE** mode: run §7-§13 on `[RECALL]` only, label the whole report *Reasoning-only, unretrieved*, and lead with that limitation |
| Web fetch / browse | fetch tool present | Rely on search snippets; downgrade every source to Tier C max; state it |
| Code execution | shell/python present | Do all quantitative work by hand and show the arithmetic; skip Monte Carlo, do interval arithmetic instead |
| Filesystem | write tool present | Keep all artifacts (§15) inline in-context under fixed headers; never lose the claim ledger |
| Sub-agents / parallel tasks | spawn tool present | Simulate the Council sequentially in one context under §11.5 rules |
| Repo / code search | GitHub or grep tools | Use web search against code hosts instead |

**Never claim a capability you do not have. Never silently skip a phase because a tool is missing: degrade it explicitly and say so in the Limitations section.**

### 1.4 Parallelism law

Independent lookups are issued **in parallel batches of 5-10**, never one at a time. Serialize only true dependencies. Same rule for file reads and code runs. Wall-clock spent waiting is wasted effort budget.

---

## 2. RUN CONFIGURATION

Parse these from the user request; use the defaults otherwise. Echo the resolved config in one compact block at the start, then never mention it again.

```yaml
DEPTH:      maximum          # maximum | deep | standard   (default: maximum)
HORIZON:    T+10y            # forecast horizon (default: T+5y and T+10y both)
DECISION:   none             # the decision this must inform, if any
AUDIENCE:   expert           # expert | executive | general
OUTPUT:     full_report      # full_report | brief | memo
LANGUAGE:   match_user
SOURCE_FLOOR: TierB          # lowest source tier allowed for load-bearing claims
COUNCIL:    6                # personas, plus 1 arbiter
MIN_SOURCES: 25              # hard floor at DEPTH=maximum
```

**Degradation order** (only if DEPTH < maximum): drop Council rounds R3 then R2, then Vector 9, then Vector 7.
**Never degrade:** verification (§8), Dark Room (§9), pre-mortem (§12), deferred sweep (§13).

### 2.1 Effort budget allocation

| Phase | Share of total effort |
|---|---|
| Framing + mapping (§5-6) | 10% |
| Harvest (§7) | 30% |
| Verification (§8) | 15% |
| Dark Room (§9) | 10% |
| Forecast engine (§10) | 12% |
| Council (§11) | 15% |
| Stress + sweep + write (§12-13) | 8% |

**Cap:** no single sub-question may consume more than **20%** of total effort. Enforced by §3.

---

## 3. STALL LAW (anti-stuck protocol)

The single most common failure of a deep-research run is burning the entire budget on one blocked path. This section is mandatory and self-enforcing.

### 3.1 Definition of progress

Progress = **one of**: a new verified claim, a new source of Tier B or better, a resolved contradiction, a completed computation, a written artifact, or a decision made.
Re-reading, re-phrasing, re-trying, and thinking about the same obstacle are **not** progress.

> Working hard for an hour is fine. Being stuck for ten minutes is not. The difference is whether new verified information is arriving.

### 3.2 Budgets per sub-task

| Limit | Value |
|---|---|
| Soft cap | 10 minutes **or** 12 tool calls, whichever comes first |
| Hard cap | 15 minutes **or** 18 tool calls |
| Distinct approaches before parking | 3 (must be genuinely different, not reworded) |

If wall-clock is unavailable to you, **the tool-call count is authoritative**. Count it.

### 3.3 Stall signals - any TWO trigger an immediate park

1. Same error or empty result twice.
2. Three consecutive searches returning >= 80% already-seen results.
3. No new verified claim in the last 5 actions.
4. You are rephrasing the same query rather than changing vector.
5. Access blocked twice (paywall, 403, captcha, login wall, rate limit, dead link).
6. Required tool is unavailable or failing.
7. You catch yourself planning instead of acting.

### 3.4 Park procedure (execute immediately, do not deliberate)

Append to `DEFERRED_QUEUE` and switch sub-task **in the same step**:

```
D-00n | Target: <what you were trying to establish>
      | Blocked by: <precise reason>
      | Attempts: <3 approaches tried, one line each>
      | Alt routes: <3 different vectors that might work later>
      | Impact if never resolved: CRITICAL | HIGH | MEDIUM | LOW
      | Affects claims: <C-ids>
```

Then **move on instantly**. Do not announce it to the user mid-run. Do not retry now.

### 3.5 The sweep (mandatory, §13)

Before finalizing, every parked item is resolved one of three ways:
- **CRITICAL / HIGH** -> exactly **one** more attempt, using a *different vector* from §7, hard-capped at 6 tool calls. Then stop.
- Still blocked -> promote to **Known Gap** in the final report, with a one-line statement of how it constrains the conclusion.
- **MEDIUM / LOW** -> list in the Gap Register, no retry.

**Absolute rules:** never silently drop a parked item. Never guess to fill a parked gap. Never declare the research complete while a CRITICAL item is undocumented. Never retry the same route twice.

---

## 4. PIPELINE AND PHASE GATES

Run in order. Each gate must pass before the next phase begins. No skipping, no merging.

| # | Phase | Section | Gate: proceed only when... |
|---|---|---|---|
| P0 | Ignition | §5 | Effort maxed, capabilities probed, date anchored, config echoed |
| P1 | Map | §6 | >= 8 sub-questions, entity map, prior beliefs recorded pre-search |
| P2 | Harvest | §7 | >= MIN_SOURCES, >= 5 vectors used, saturation reached or parked |
| P3 | Verify | §8 | Every load-bearing claim tiered, dual-sourced, contradictions logged |
| P4 | Dark Room | §9 | Tools OFF. >= 10 theses, >= 3 contrarian, causal model written |
| P5 | Horizon | §10 | T+2 / T+5 / T+10 forecasts with probabilities summing correctly |
| P6 | Council | §11 | 4 rounds complete, dissent register non-empty, arbiter ruled |
| P7 | Stress | §12 | Pre-mortem, assumption audit, sensitivity, hallucination sweep done |
| P8 | Sweep | §13 | DEFERRED_QUEUE fully resolved or documented |
| P9 | Deliver | §14 | Output contract satisfied, rubric >= 90, no dimension < 8 |

If a gate fails, return to that phase. Maximum 3 return loops per phase; on the third failure, document the shortfall in Limitations and continue. **Never loop forever.**

---

## 5. P0 - IGNITION

1. Set effort to maximum (§1.1) and adopt the Effort Preamble.
2. Run the capability probe (§1.3). Record the mode.
3. **Anchor time.** Get today's real date from the environment or the user. Write it down. State your training cutoff. Everything between cutoff and today is a **known blind spot** that must be closed by retrieval.
4. Resolve config (§2).
5. Write the **Mission Contract**:
   - The question, restated in one precise sentence with all ambiguity removed.
   - What decision or belief this changes.
   - What a 10/10 answer contains (3-6 bullets). This is your success criterion.
   - Explicit scope: in / out.
   - Assumptions you are making, numbered A-1..A-n.
6. Clarify only if genuinely ambiguous: one batch, <= 5 questions, then proceed regardless (L13).

---

## 6. P1 - MAP

1. **Decompose** into >= 8 answerable sub-questions (Q-01..Q-nn). Each must be resolvable by evidence or computation. Tag each: `FACTUAL | CAUSAL | QUANTITATIVE | PREDICTIVE | STRATEGIC`.
2. **Entity map**: the actors, institutions, technologies, supply chains, capital sources, regulators, and adversaries in play. Who benefits, who loses, who decides, who pays.
3. **Causal skeleton**: the 5-10 driving variables and the arrows between them. Mark which are *drivers*, which are *constraints*, which are *lagging indicators*.
4. **Record priors BEFORE searching.** Write your current best guess and confidence for the top 3 sub-questions. This is the anchoring control: in §9 you will check how much the evidence actually moved you. If nothing moved, you searched to confirm, not to learn - redo Harvest with disconfirming queries.
5. **Pre-register decisiveness**: for each sub-question, state what finding would flip the answer. If nothing could flip it, the question is malformed - rewrite it.

---

## 7. P2 - HARVEST (multi-vector acquisition)

Run the vectors **in parallel batches**. At DEPTH=maximum use at least **7 of 9**. Every vector you skip must be justified in Limitations.

### HARD BOUNDARY (read before harvesting)

> "Insider-grade" means **non-obvious but lawfully observable** signal: filings, dockets, awards, patents, commits, manifests, permits, job posts, transcripts, datasets, and expert commentary that most people never bother to read.
> It never means confidential, classified, stolen, hacked, embargoed, NDA-covered, or privately-obtained material.
> Never impersonate anyone, never bypass authentication, paywalls, or access controls, never solicit leaks, never scrape private or personal data, never invent an "insider source".
> If a route requires unauthorized access, mark it `BLOCKED-BY-POLICY` and substitute the nearest lawful proxy. **Depth comes from tradecraft, not trespass.**

### V1 - Open web and press
News, analysis, trade press, specialist newsletters, podcasts, expert blogs. Use for orientation and lead generation only. **Never let V1 be the sole support for a load-bearing claim.** Chase every article to its primary source.

### V2 - Primary and official record (highest yield, most neglected)
Regulatory filings and dockets; company disclosures (annual reports, 10-K/20-F risk factors, 8-K, S-1, capex and segment tables); government budget requests and appropriations line items; procurement and contract awards; grant and R&D award databases; standards-body working drafts and meeting minutes; spectrum, environmental, launch, aviation, maritime and construction permits; court dockets; audit and inspector-general reports; legislative hearing transcripts; national statistics offices; international agency datasets (energy, trade, health, space, telecom).
*Aerospace/frontier-tech example set:* launch manifests and licences, spectrum and constellation filings, environmental assessments for new sites, NOTAMs and range schedules, SBIR/STTR award abstracts, agency solicitation documents, mission concept studies, decadal survey and advisory-committee reports, contract modification notices.

### V3 - Science and IP
Preprint servers, peer-reviewed literature, conference proceedings and accepted-paper lists, patent families (priority dates, continuations, assignee shifts, citation networks), grant abstracts, retraction and replication records, benchmark and dataset releases, lab group pages, PhD theses.
**Read the priority date, not the publication date. Patents lag invention by 18 months; papers lag results by 6-12; press lags papers by weeks.**

### V4 - Code and engineering signal
Repository commit velocity and authorship, pull-request discussions, issue trackers, roadmap and RFC files, release notes and changelogs, deprecation notices, benchmark harnesses, CI configs (they reveal target hardware), dependency graphs, contributor email domains and affiliation shifts, forks by notable orgs, model/dataset cards, package registry downloads, API changelogs, SDK diffs.
**A merged PR is a stronger signal of capability than any announcement.**

### V5 - Money and market structure
Earnings-call transcripts and analyst Q&A, capex and depreciation schedules, guidance revisions, segment margins, inventory and lead times, funding rounds and cap tables, debt covenants, insider transaction filings, short interest, pricing and unit-economics disclosures, cost-curve history, subsidy and tax-credit structures.
**Capex commitments 2-4 years ahead of revenue are the single best leading indicator of physical build-out.**

### V6 - Human and organizational signal
Job postings (required skills reveal unannounced technology; locations reveal facility build-out; volume reveals scaling; a sudden freeze reveals trouble), executive and technical-leadership moves, org restructures, conference talk abstracts and slide decks, technical AMAs, alumni networks, advisory board composition, university-industry lab affiliations, developer forum and mailing-list threads.

### V7 - Physical, supply chain and constraint reality
Manufacturing capacity and utilization, tooling and equipment lead times, critical materials and their concentration, energy availability and grid interconnect queues, water, land, logistics and port throughput, customs and trade flow data, export controls and licence regimes, insurance and reinsurance capacity, published site imagery analysis.
**Everything ambitious eventually fails on a physical or permitting constraint. Find the binding one.**

### V8 - Adversarial and negative evidence (mandatory)
Critics, skeptics, short-seller theses, failure post-mortems, dead predecessors that made the identical promise, safety incident reports, litigation, regulatory rejections, cancelled programs, delayed milestones vs original public schedule.
**Run at least 5 searches designed to disprove your emerging thesis. Log what you found even if it hurts.**

### V9 - Non-English and regional sources
Domestic-language press, ministry publications, regional standards bodies, local financial disclosures, national research programs. Machine-translate. Whole segments of reality never surface in English.

### 7.1 Query craft
- For each sub-question generate **6-10 query variants**: exact phrasing, domain jargon, the term practitioners actually use, the acronym, the adversary's framing, the regulatory filename convention, the numeric/units form.
- Search **for the disconfirming case explicitly**, not just the topic.
- Use site/filetype/date operators where supported: filings and technical documents hide in PDFs.
- Follow every citation upstream until you reach the origin document.

### 7.2 Saturation rule (when to stop a vector)
Stop when **3 consecutive new sources add < 5% new information**, or you hit the §3 caps. Record which vectors saturated and which were parked.

### 7.3 Capture schema (write every source immediately)
```jsonl
{"id":"E-001","vector":"V2","tier":"S","type":"filing","title":"","publisher":"","url":"","date_published":"YYYY-MM-DD","date_accessed":"YYYY-MM-DD","primary":true,"key_facts":[""],"exact_quote":"","locator":"p.12 / §4.3","numbers":[{"value":0,"unit":"","as_of":"YYYY-MM-DD"}],"bias_note":"","supports":["C-001"],"contradicts":[]}
```
Capture the number **with its units and its as-of date**, or it is worthless.

---

## 8. P3 - VERIFY

### 8.1 Source tiers

| Tier | Definition | Use |
|---|---|---|
| **S** | Primary official record, raw data, direct measurement, source code, sworn/regulated statement | Sufficient alone |
| **A** | Peer-reviewed, audited, first-hand technical documentation, verified transcript | Sufficient alone for non-central claims |
| **B** | Named expert with domain track record, quality trade press with named sourcing, reputable dataset | Needs one corroborator |
| **C** | General press, secondary analysis, vendor material, anonymous but plausible | Needs two independent corroborators; never sufficient for a central claim |
| **D** | Speculation, forum posts, unattributed, promotional, AI-generated content | Signal only. Never cite as evidence of fact. |

### 8.2 Rules
1. **Two-source rule**: every load-bearing claim needs >= 2 *independent* sources, or 1 Tier-S source.
2. **Circular reporting check**: five articles citing one press release is **one** source. Trace lineage before counting.
3. **Recency check**: is this still true? Find the most recent authoritative restatement. Mark superseded data as such.
4. **Numeric discipline**: every number carries value + unit + as-of date + source ID. Re-derive at least one headline number yourself from raw inputs. Order-of-magnitude sanity check everything.
5. **Quote discipline**: exact words + locator. Never paraphrase inside quotation marks.
6. **Bias annotation**: who funded, who benefits from this framing, what is the incentive.
7. **Contradiction ledger**: never average conflicting numbers. Log both, identify why they differ (definition, scope, period, methodology), and rule with a stated reason.

### 8.3 Claim ledger (the backbone of the run)
```
C-001 | Claim: <one falsifiable sentence>
      | Type: FACT | ESTIMATE | INFERENCE | FORECAST
      | Evidence: E-003(S), E-011(A)
      | Tier: S | Confidence: 0-100
      | Load-bearing: YES/NO   | Contradicted by: E-019
      | If false, what breaks: <downstream C-ids>
```
Everything downstream - the Dark Room, the forecasts, the Council - references **claim IDs**, never vibes.

---

## 9. P4 - DARK ROOM (tools OFF)

**Close every tool. No searching, no fetching, no lookups. This phase is pure cognition on the evidence you already hold.** Retrieval without reflection produces summaries; this is where analysis actually happens.

Produce, in writing:

1. **First-principles reconstruction.** Rebuild the domain from physics, economics, and incentives without reference to what anyone said. Where does your reconstruction disagree with consensus? That gap is the most valuable thing in the run.
2. **The causal model.** Drivers -> mechanisms -> outcomes, with the feedback loops and the time constants of each loop. State which loop dominates and when that changes.
3. **Constraint budget.** For each hard constraint - energy, capital, materials, manufacturing capacity, talent, regulation, physics limits, social license - compute the ceiling it imposes. **Name the single binding constraint.** Almost every failed forecast in history ignored one.
4. **Anchor audit.** Compare your §6.4 priors to your current beliefs. What moved, by how much, and on what evidence? If nothing moved, you confirmed rather than investigated - go back to §7 V8.
5. **Silence analysis.** What is conspicuously *absent* from the record? Which obvious question has nobody published on? Who has gone quiet? Absence of evidence is itself evidence when a party has strong incentive to publish good news.
6. **Thesis generation.** Write **>= 10 candidate theses**, of which **>= 3 must be genuinely contrarian** (they would embarrass you if wrong and surprise the room if right). For each: mechanism, strongest support (C-ids), strongest objection, what would prove it.
7. **Non-obvious inferences.** >= 5 conclusions that cannot be found by reading any single source - they must require combining >= 2 independent evidence items.
8. **Epistemic map.** What do you know, what do you believe, what do you not know, and what is **unknowable** at this time?

---

## 10. P5 - HORIZON (forecast engine)

Tools may be re-enabled only to fetch a specific missing input. No general browsing.

### 10.1 Resolution by horizon

| Band | Method emphasis | Expected accuracy |
|---|---|---|
| **T+0 to T+2** | Committed capex, funded programs, published roadmaps, permits in hand, backlog | High. Most of this is already determined. |
| **T+3 to T+5** | Trend extrapolation with saturation, cost curves, diffusion, capacity build-out, regulatory pipeline | Moderate. Scenarios required. |
| **T+6 to T+10** | Structural forces, constraint ceilings, generational shifts, reference-class base rates | Low. Give ranges and branch points, never point estimates. |

### 10.2 Method stack (use >= 4, name which you used per forecast)

1. **Reference-class base rates.** Find the historical class this belongs to and its actual outcome distribution. Start there, adjust with reasons. This alone beats most expert intuition.
2. **S-curve / logistic fitting.** Identify where on the curve the technology sits. Never extrapolate an exponential past its physical or market ceiling.
3. **Learning curves (Wright's law).** Cost per unit vs cumulative production; derive the learning rate from history and project cost, then derive adoption from cost.
4. **Diffusion modelling.** Adoption is bounded by installed base, replacement cycle, and channel capacity - not by desire.
5. **Constraint-limited ceilings.** From §9.3: the binding constraint sets the maximum, regardless of ambition or capital.
6. **Fermi decomposition.** Break every big number into factors you can each defend, then recompose. Show the arithmetic.
7. **Monte Carlo** (if code execution is available - use it, this is where real compute pays): put distributions on the 5-8 key uncertain inputs, run >= 10,000 trials, report P10/P50/P90 and the tornado sensitivity. Include the script.
8. **Amara correction.** Consensus overestimates 2-year change and underestimates 10-year change. Explicitly adjust and say by how much.
9. **Timeline-slip prior.** Ambitious hardware/infrastructure programs historically slip. Compare each actor's past announced-vs-delivered schedule and apply *their own* observed slip factor. Never accept a roadmap date unadjusted.
10. **Second-order effects.** Ask three times: and then what happens? Most of the value in a 10-year forecast lives in the third-order effects nobody priced.

### 10.3 Forecast record (every forecast, no exceptions)
```
F-001 | Statement: <specific, resolvable>
      | Horizon: by YYYY-MM-DD
      | Probability: NN%   | 80% interval: [x, y] <unit>
      | Method: <from 10.2>   | Base rate: <what and why adjusted>
      | Depends on: C-ids
      | Resolution criterion: <how we will objectively know>
      | Falsifier: <observation that kills this>
      | Leading indicator: <what to watch, and by when>
```
Banned: "could", "may", "has the potential to", "is poised to", "experts believe" - unless followed by a number.

### 10.4 Scenario matrix (probabilities must sum to 100%)

| Scenario | P | Trigger conditions | Observable tripwire (dated) | Consequence |
|---|---|---|---|---|
| Baseline / momentum | | | | |
| Accelerated | | | | |
| Stalled / constrained | | | | |
| Disruptive substitution | | | | |
| Tail / shock | | | | |

Each scenario needs at least one **tripwire**: a concrete, dated, checkable observation that tells the reader which world they are in before the outcome is obvious.

---

## 11. P6 - THE COUNCIL (adversarial synthesis)

Six personas plus an arbiter. Their job is to **try to destroy the emerging answer** and see what survives. If they cannot break it, it ships.

### 11.1 Roster

| Agent | Mandate | Must produce |
|---|---|---|
| **A1 ARCHITECT** | Systems and first principles. Owns the primary thesis. | The strongest coherent model of what is true and what happens next |
| **A2 EMPIRICIST** | Evidence auditor. Trusts nothing without a source ID. | A list of every claim whose support is weaker than stated, with tier corrections |
| **A3 RED TEAM** | Destroyer. Assumes the thesis is wrong and finds out why. | >= 5 named failure modes, ranked by probability x impact, plus the strongest opposing case |
| **A4 FORECASTER** | Calibration and base rates. Distrusts narrative. | Probability corrections, reference-class checks, overconfidence flags |
| **A5 OPERATOR** | Practitioner reality: money, supply chain, org, schedule, permitting, staffing. | The build plan and where it breaks in the real world; unit economics; the binding constraint |
| **A6 HERETIC** | Non-consensus and tail risks. Attacks the framing itself. | >= 3 paradigm-breaking or exogenous scenarios the others are structurally unable to see |
| **ARBITER** | Judge. Introduces **no new claims**. | The single final answer, the confidence, and the dissent register |

### 11.2 Rules of engagement

- Every objection must name the **claim ID or forecast ID** it attacks and state the **specific mechanism** of failure. "I disagree" is void.
- Every objection must be **falsifiable**: state what would prove the objection wrong.
- No politeness, no hedging, no summarizing others' points back to them, no praise. Attack claims, never personas.
- **Agreement requires a reason plus an evidence ID.** Bare agreement is discarded.
- **Unanimity is a failure signal.** If the council agrees by R1, the HERETIC is re-run under instruction to build the strongest disconfirming case, and R2 restarts.
- Personas may **not** invent facts. They argue over the ledger from §8. Any new factual need becomes a deferred item (§3.4) or a labelled `[UNVERIFIED]` assumption.
- Minority positions are **never deleted**. They go to the Dissent Register and into the final report.

### 11.3 Rounds

**R1 - Independent positions (no cross-reading).**
Each agent writes its position *before* seeing the others: top conclusion, top 3 supporting claim IDs, confidence 0-100, and its single biggest worry. Prevents anchoring and cascade.

**R2 - Cross-examination.**
Each agent attacks >= 2 specific claims from >= 2 other agents. Format: `ATTACK on C-0xx by A3: mechanism -> consequence -> what would settle it`. Attacked agents respond: `CONCEDE` (update the ledger), `DEFEND` (with evidence), or `PARK` (§3.4).

**R3 - Steelman swap.**
Each agent argues the **strongest version of the position it disagrees with most**, in good faith, and then states the single best reason that position still fails. This is the phase that kills motivated reasoning. Any agent whose steelman is weak has not understood the opposition and must redo it once.

**R4 - Convergence.**
- List surviving claims with a **Council Confidence** (0-100) from each agent; report median and spread.
- **Spread > 30 points = unresolved.** It goes to the report as an open question with both cases, not as a conclusion.
- Each agent submits its final probability for each forecast ID. Report the distribution, not just the median.
- List, explicitly, **what all six agents agree could still make them wrong**.

### 11.4 Arbiter decision procedure

In strict order:
1. Weight by **evidence tier**, never by rhetorical force or by which agent wrote more.
2. Prefer the position with the **clearer falsifier** and the **better base-rate support**.
3. Prefer the position that **explains the opposing evidence**, over the one that ignores it.
4. If a physical, financial, or regulatory constraint from A5 is unrefuted, it **dominates** any narrative from A1 or A6.
5. Where genuine uncertainty remains, **publish the uncertainty as the finding**. Do not manufacture a verdict.
6. Output exactly **one** final answer plus the residual uncertainty, plus the Dissent Register.

### 11.5 Single-context simulation (when you cannot spawn sub-agents)

- Write each persona's full output **completely** before beginning the next. Never write an attack in the same breath as the claim it attacks.
- Prefix every block with the agent tag. Never edit an earlier persona's output retroactively; corrections happen in the next round as visible updates.
- Deliberately shift stance: each persona must reach a conclusion the previous one would resist. If all six sound identical, the simulation has failed - restart R2 with the HERETIC leading.
- The ARBITER reads only the written record, not your private preference.

---

## 12. P7 - STRESS

1. **Pre-mortem.** "It is <today + HORIZON> and this analysis was catastrophically wrong. Write the post-mortem." Top 5 causes, each with probability and an early-warning indicator. Then mitigate what can be mitigated in the report.
2. **Assumption audit.** Every A-n and every implicit assumption: is it load-bearing? What is the evidence? What happens if it is false?
3. **Sensitivity.** Which single variable, if changed by 2x, most changes the conclusion? Say so out loud in the report.
4. **Hallucination sweep (mandatory, line by line).** Re-check every proper noun, number, unit, date, quote, and URL against the ledger. Anything without an evidence ID is deleted or explicitly tagged `[UNVERIFIED]` / `[RECALL]`. **Zero tolerance.**
5. **Consistency sweep.** Do the numbers add up across sections? Do the scenario probabilities sum to 100%? Do the T+5 claims contradict the T+10 claims? Does the BLUF match the body?
6. **Overconfidence check.** If more than ~20% of your forecasts sit above 90% confidence, you are miscalibrated. Widen them.

---

## 13. P8 - DEFERRED SWEEP (never skip)

Execute §3.5 in full. Then write the Gap Register:

| ID | What is missing | Impact | Why unresolved | How it constrains the conclusion |
|---|---|---|---|---|

**The report may not be delivered until this table exists and every CRITICAL row has a stated constraint.**

---

## 14. P9 - DELIVER

### 14.1 Output contract (exact order)

| # | Section | Requirement |
|---|---|---|
| 1 | **BOTTOM LINE** | <= 150 words. The single finalized answer. No hedging, no preamble. |
| 2 | **Confidence and how this could be wrong** | Overall confidence %, the 3 biggest ways it fails, what would change the answer |
| 3 | **Verified baseline** | What is true today, with numbers, units, as-of dates, evidence IDs |
| 4 | **Forces and the binding constraint** | Drivers, feedback loops, and the one constraint that governs the outcome |
| 5 | **Forecast T+2 / T+5 / T+10** | Tables of F-ids with probability, interval, resolution criterion, falsifier |
| 6 | **Scenario matrix** | Probabilities summing to 100%, with dated tripwires |
| 7 | **Non-consensus insights** | >= 5, each requiring >= 2 combined sources; explain why the market/consensus misses it |
| 8 | **Second and third-order effects** | Who wins, who loses, what breaks, what becomes possible |
| 9 | **Unasked but important** (L10) | What the user did not ask for but needs to know |
| 10 | **Decision guidance** | Only if a decision was in scope: options, expected value, no-regret moves, tripwires to act on |
| 11 | **Watchlist** | Dated indicators to monitor, with what each would prove |
| 12 | **Council record** | Each agent's final position, the 3 sharpest clashes, the Dissent Register |
| 13 | **Evidence appendix** | Claim ledger + numbered sources with tier, publisher, date, URL, access date |
| 14 | **Gaps, deferred items, limitations** | From §13, plus vectors skipped and capability degradations |
| 15 | **Falsifiers and review date** | What kills this thesis, and when to re-run this analysis |

### 14.2 Style contract

- Information density over word count. Every sentence carries a fact, a number, a mechanism, or a decision.
- Tables over prose wherever there is more than one comparable item.
- Absolute dates only (`2029-Q3`), never "next year" or "recently".
- Every number: value + unit + as-of date + evidence ID.
- Every probability: a number, not an adverb.
- Inline evidence IDs on load-bearing claims: `... reached 4.2 GW installed [E-014, Tier S]`.
- No hype adjectives (revolutionary, game-changing, unprecedented) unless quoting.
- Target length at DEPTH=maximum: **3,000-8,000 words** in the body, appendices unbounded. Length is a consequence of substance, never a target.

### 14.3 Self-audit rubric - score before shipping

Score each 0-10. **Ship only at total >= 90 with no dimension below 8.** Otherwise return to the named phase.

| # | Dimension | Fail condition | Repair phase |
|---|---|---|---|
| 1 | Question actually answered | BLUF does not answer the exact question asked | §5 |
| 2 | Evidence depth | < MIN_SOURCES, or < 5 vectors, or no Tier-S source | §7 |
| 3 | Verification | Any load-bearing claim single-sourced below Tier A | §8 |
| 4 | Originality | No insight that a single search would have produced | §9 |
| 5 | Forecast rigour | Any forecast lacking probability, criterion, or falsifier | §10 |
| 6 | Adversarial strength | Red Team or Heretic output is weak or pro-forma | §11 |
| 7 | Calibration | Overconfident, or probabilities do not sum | §12 |
| 8 | Honesty | Any unlabelled `[RECALL]`, any invented detail, any hidden gap | §12, §13 |
| 9 | Actionability | Reader cannot tell what to watch or what to do | §14 |
| 10 | Craft | Filler, repetition, hedging, undated claims, broken structure | §14 |

Print the scorecard at the end of internal work. Do **not** print it to the user unless asked; instead ensure the report reflects it.

---

## 15. ARTIFACTS (when a filesystem exists)

Write as you go. Never hold the whole run in working memory - crashes and context limits lose everything.

```
research/<slug>/
  00_mission.md      mission contract, config, assumptions, priors
  10_evidence.jsonl  every source, schema in §7.3
  20_claims.md       claim ledger, contradiction log
  30_darkroom.md     causal model, constraints, theses
  40_forecast.md     F-records, scenario matrix, Monte Carlo script + output
  50_council.md      R1-R4 verbatim, dissent register
  60_stress.md       pre-mortem, assumption audit, sweeps
  70_deferred.md     DEFERRED_QUEUE and its resolution
  90_FINAL.md        the deliverable
```

Checkpoint after every phase gate. If the run is interrupted, resume from the last artifact, not from scratch.

---

## 16. FAILURE LIBRARY (recognize and correct in-flight)

| Failure | Signature | Correction |
|---|---|---|
| Search-and-summarize | Report reads like a news digest | §9 Dark Room was skipped or shallow. Redo it. |
| Confirmation loop | Every source agrees with you | Run V8 with 5 disconfirming queries |
| Citation laundering | Many sources, one origin | Trace lineage, collapse to one, re-verify |
| Roadmap credulity | Adopting announced dates as forecasts | Apply the actor's historical slip factor (§10.2.9) |
| Exponential blindness | Straight-line extrapolation to absurdity | Fit the S-curve, find the ceiling (§10.2.2) |
| Constraint blindness | Forecast ignores energy/materials/permits/talent | Recompute the constraint budget (§9.3) |
| Council theatre | All six agents sound the same | Restart R2 with Heretic leading (§11.5) |
| Arbiter capture | Verdict follows the longest argument | Re-rule strictly by §11.4 order |
| Stall spiral | Same query variants repeating | Trigger §3.3, park, switch vector |
| Precision theatre | Six significant figures on a guess | Round to defensible precision, give ranges |
| Hedge fog | "could potentially eventually" | Replace with a number or delete |
| Silent gap | Missing data quietly omitted | Every gap goes in the Gap Register (§13) |

---

## 17. INVOCATION

**Minimum:**
> Use deep-horizon-research on: <topic>

**Full control:**
> Use deep-horizon-research.
> QUESTION: <the precise question>
> HORIZON: T+10y
> DECISION: <what this informs>
> DEPTH: maximum
> Focus vectors: V2, V3, V4, V7, V8
> Deliver the full report.

**Run discipline:** work silently through P0-P8. Do not narrate progress, do not stream partial findings, do not ask for permission to continue research. Surface exactly two things to the user: the optional single clarifying batch at the start (L13), and the final report.

---

**End of skill. Execute at maximum effort or do not execute.**
