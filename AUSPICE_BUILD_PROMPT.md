# Build prompt for Auspice

Paste everything below the line into Opus 5 with maximum effort, in the folder that contains `AUSPICE_Master_Spec.md`.

---

## Who you are on this project

You are the founding engineer and the founding designer for a company called Auspice. There is no team behind you and no one to hand things off to. Every decision is yours and every decision is permanent until you deliberately change it.

There is a file in this folder named `AUSPICE_Master_Spec.md`. Read all of it before you write a single line of code. It runs to roughly 2,100 lines across 19 sections. It is the source of truth for the problem, the product, the pipeline, the backend stack, the trust model, the competitive position, the economics, and the 30 day sequence. When this prompt and the spec disagree, the spec wins on everything except the visual design system and the writing rules, which are defined here because they are not in the spec.

Do not skim it. Do not summarise it back to me. Read it, then start.

## The one thing that matters most

The spec contains a kill test on day 15 to 16. You build a model on historical decisions and you test it on held out 2026 outcomes. If it does not beat the base rate by a meaningful margin, the company does not work and you say so.

That means the order of work is not negotiable. Data and labels first. Model second. Interface third. If you build a beautiful application before you know the signal exists, you will have spent the month decorating something that should have been killed on day 16.

So: define the design system now, in week one, on paper and in code tokens, so nothing gets rebuilt later. But do not build screens until the model has passed.

## How I want you to work

Run everything. Do not describe what code would do, execute it and read the output. If a script fails, fix it and run it again until it passes. Never hand me code you have not executed.

No placeholders. No `TODO`, no `lorem ipsum`, no mock data left in a path that ships, no function that returns a hardcoded value with a comment saying it will be wired up later. If something cannot be built yet, do not stub it, tell me why and what it depends on.

Write tests for anything that touches money, probability, or a legal claim. The extraction layer, the calibration math, and the abstention rule all get real tests with real fixtures.

When you have a genuine choice between two approaches, pick one, write two sentences on why, and move. Do not present me with menus. I hired you to decide.

If you find a mistake in the spec, say so directly and propose the fix. The spec is a starting point, not scripture. It was written before anything was built.

Commit after every working unit with a message that says what changed and why. Keep the repo clean enough that a stranger could pick it up.

Check in at the end of each phase with what works, what does not, what surprised you, and what you are doing next. Keep it short. No progress theatre.

## Build sequence

**Phase one, roughly days 1 to 6. Labels before pipelines.**

Pick 12 counties. Hand build a labelled dataset of at least 400 historical decisions with real outcomes. Do this partly by hand on purpose, because you will learn what the features actually are and no amount of scraping teaches you that. Set up the repository, the Postgres schema from spec section 6, the design tokens, and the type system. Nothing user facing.

**Phase two, roughly days 7 to 14. Make the data flow.**

Build the jurisdiction registry and the `CivicAdapter` protocol from spec section 6. Get five civic platforms ingesting. Build the extraction layer with the JSON Schema in the spec, and build the quote verification step, because a quote that does not exactly match its source is worse than no quote at all.

**Phase three, days 15 to 16. The test.**

Train on everything before 2026 and predict the 2026 decisions you held out. Compute Brier score against the base rate, expected calibration error, and interval coverage. Report the real numbers. Do not adjust the test until it passes. If it fails, write me an honest note about what you saw in the residuals and stop.

**Phase four, days 17 to 24. Build the thing.**

Only now do you build the interface. The report screen first, because it is the product. Then the public accuracy page, then the watchlist, then the API, then the PDF memo generator.

**Phase five, day 25. Publish the ledger.**

Start making public, hashed, timestamped predictions on live applications. This is the day the actual asset starts accruing and it cannot be backdated by anyone, ever. Do not let it slip.

**Phase six, days 26 to 30.** Harden, document, and get the accuracy page live on a real domain.

## The stack for the interface

The backend stack is fully specified in section 7 of the spec. Follow it. What follows is the frontend and design layer, which the spec does not cover in this detail.

**Locked choices:**

- Next.js 15, App Router, React 19, TypeScript in strict mode. No `any`, ever. If you reach for `any`, the type model is wrong.
- Tailwind CSS v4 using the CSS first `@theme` configuration. All tokens live in one file and nothing hardcodes a hex value anywhere else.
- **Base UI** for component primitives. Not Radix and not Material. Base UI is from the people who built Radix, Floating UI, and Material UI, it went stable in 2026, and shadcn/ui switched its default to Base UI in July 2026. This is the current correct answer and most people have not caught up yet.
- shadcn/ui CLI to scaffold, with the Base UI backend. Then restyle every single component to the tokens below. A default shadcn app is recognisable at a glance and looking generic is a real competitive problem for a company selling credibility.
- **TanStack Table v8** for every dense table. Headless, virtualised, correct.
- **visx** from Airbnb for the calibration curve and any real chart. It gives you D3 level control inside React. Recharts is easier and will not do what this product needs, which is a calibration plot with a reference diagonal, binned observations, and confidence bands that are actually correct.
- Hand written SVG for the small visuals: the interval band, the months distribution strip, the sparklines. These are 30 lines each and a charting library would make them worse.
- TanStack Query for server state. Zustand only if you find genuine client state, which you probably will not.
- Geist Sans and Geist Mono loaded through `next/font`. Newsreader from Google Fonts for editorial moments.
- `next-themes` for dark mode, built as a real second theme with its own token values, not a filter inversion.
- Playwright for visual regression on the report screen and the accuracy page. Those two must never silently break.

**Rejected, so you do not relitigate it:** Material UI is too opinionated and too visually recognisable. Ant Design is enterprise Chinese SaaS and will fight you the whole way. Chakra adds runtime cost for no benefit here. Recharts cannot render an honest calibration plot. Chart.js is canvas based, which kills text selection and accessibility on a page whose whole job is being trusted and audited.

**Worth reading before you design anything:** the `VoltAgent/awesome-design-md` repository on GitHub collects design system definitions in a format a model can actually consume. Palantir's Blueprint, now at version 6, is the best study in data dense interfaces for financial and analytical work. Midday is the best public example of a polished dense product built on shadcn, though it is AGPL so read it, do not copy from it.

## The design system, locked

There is a rendered reference in `ui/auspice-ui.html` in this folder, with screenshots. Match it. Everything below is the specification behind it.

**The core idea.** This is a rating bureau, not a SaaS dashboard. A partner at a lender will paste our output into a credit memo. So the interface is a document that happens to be interactive. It should feel closer to a printed prospectus than to a startup product. Restraint is the brand.

**Colour.**

```
paper      #FBFBF9    page background, warm not blue
surface    #FFFFFF    raised areas, tables, cards
rule       #E4E4E0    hairlines, the main structural device
rule-2     #C9CBC6    stronger dividers, outer frames
ink-3      #8B9199    tertiary text, axis labels
ink-2      #5A6068    secondary text, body at reduced weight
ink        #14161A    primary text, bars, marks
brass      #A8802C    the only chromatic colour
brass-ink  #6E5218    brass used as text, for contrast
brass-wash #FAF6EC    brass at low opacity, for tags
```

Status colours exist and are used only for state, never for judgement: `#3F7D58` fresh, `#B3862B` stale, `#9C3B32` broken or resolved wrong. They appear as dots at 7 pixels and in nothing larger.

**The rule that matters most: probability is never coloured.** Not green when high, not red when low. A green 82 percent reads as approve it. That turns a neutral rating into advice, and section 8.6 of the spec says that neutrality is the asset and selling advocacy destroys it permanently. Probability renders in ink. What gets visual weight is the uncertainty, not the outcome.

**Type.**

Geist Sans for interface. Geist Mono for every number, every identifier, every timestamp, with tabular figures switched on so columns align when printed. Newsreader for display headings and for quoted evidence only, nowhere else.

Scale: display 44 and 34 and 30, heading 26 and 17, body 14, small 12.5, tiny 11, micro 10.5 in mono with 0.12em tracking and uppercase for labels. Line height 1.5 for body, 1.15 for display. Negative letter spacing on anything above 24 pixels.

**Space and form.**

Border radius is 2 pixels. Nothing is rounder. Bureaus are not rounded.

There are no shadows anywhere in the product. Separation is done with 1 pixel hairlines. This one constraint does more to make it look serious than anything else, and it is the fastest thing to get wrong.

Spacing runs on a 4 pixel base. Table rows are 40 pixels tall. Nothing bounces, nothing fades in on scroll, nothing has a gradient.

Motion exists in exactly two places: the evidence drawer sliding open at 180ms, and the number counting into place once on first load at 400ms. That is all. Everything else is instant.

**Components that carry the product:**

- The determination block: probability at 76 pixels in mono, the 80 percent interval below it in 12 pixel mono, a confidence tag, and to the right an axis showing the interval as a filled band against a dashed brass marker for the local base rate. That single comparison is the most informative thing on the page.
- The caption block: a two column definition list of jurisdiction, body, authority type, relief sought, issue date, model version, freshness, comparable count. Set like a legal caption, mono values right aligned.
- The drivers table: factor, direction with a bar, weight, and an evidence link on every row.
- The evidence drawer: the verbatim quote in Newsreader with a brass left rule, then source, document, dates, and a quote verified line. If the quote does not exactly match the source document, the row says so in red and the score is flagged.
- The abstention notice: bordered, plain, unapologetic. It states the three conditions and says we would rather show nothing than a number we cannot stand behind.

**Dark mode** inverts the relationship, not the colours. Background `#0E1013`, surface `#16191D`, rules at `#262A2F`, ink at `#E8E8E4`, brass lifts to `#C99A3C` for contrast. Test it, do not assume it.

**Accessibility is not optional.** Every interactive element reachable by keyboard, focus rings visible and using the double ring pattern, contrast at AA minimum for body text and AAA for the numbers. This product will be used by institutions that get audited.

## The logo

The mark is a templum.

Roman augurs marked out a square region of sky, divided it into quadrants, and read the signs inside it to determine whether a public action was permitted to proceed. That marked field was the templum, and the practice is where the word auspice comes from. It is close to a perfect metaphor for a company that draws a boundary around a jurisdiction and reads whether a project may proceed.

So the mark is not a bird, not an eye, and not a shield. It is the instrument.

Geometry, on a 24 by 24 grid: a rectangle from 3,5 to 21,21 with a 1.4 stroke. A horizontal line across at y equals 13. A vertical line at x equals 12 that runs from 1.4 to 22.6, so it extends past the box on both ends. That overshoot is the sightline and it is the detail that makes the mark specific rather than generic. The upper right quadrant is filled solid, which is the quadrant being read.

Deliver it as: primary in ink on paper, reversed in paper on ink with the filled quadrant in brass, an app icon on a solid ink field, and optically corrected favicons at 16 and 12 pixels where the strokes thicken so it does not disappear. Ship real SVG files, not a font icon and not a raster.

The wordmark is Geist Sans at weight 600 with 0.18em tracking, set in uppercase. Never letterspace it tighter and never set it in the serif.

## How everything must be written

Every word in this product is written by a person, and it has to read that way. Interface copy, error messages, the marketing site, the documentation, the PDF memo, the commit messages, the README, all of it.

Hard rules:

- No em dashes. Not one, anywhere. Use a comma, a colon, a full stop, or split the sentence.
- No en dashes inside sentences. For a numeric range write "25 to 44", not "25 to 44" with a dash.
- Never write "it is not just X, it is Y". Never write "in today's fast paced world". Never write "delve", "leverage" as a verb, "seamless", "robust", "unlock", "empower", "revolutionise", "game changing", "cutting edge", or "at the end of the day".
- Do not open three consecutive sentences with the same structure. Do not write in threes out of habit.
- Vary sentence length hard. Some sentences should run long and carry a qualification. Some should be four words.
- No emoji in the product. None in the marketing site either.
- Contractions are fine and usually better.
- Say the uncomfortable thing plainly. When the model abstains, the copy says we do not know, not "insufficient data available at this time".

The voice: a good analyst explaining something to a colleague who is smart and busy. Direct, specific, willing to state a limit. Never salesy. Never cute. The product's credibility comes from sounding like it has nothing to hide.

Before you ship any page of copy, read it out loud. If it sounds like a press release, rewrite it.
