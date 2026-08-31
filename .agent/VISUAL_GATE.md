# The visual gate

Why the four screenshot baselines were stale, how that was established, and what will break them next.

Written because the answer took five CI runs to find and the next person should not have to repeat it.

## What the gate is

`apps/web/tests/visual/design-system.spec.ts` takes three full page screenshots: the accuracy page, the
coverage table and a jurisdiction profile. The tolerance is a `maxDiffPixelRatio` of 0.002, which is two
tenths of one percent of pixels, and it is deliberately that tight: a looser threshold hides the class of
regression the suite exists to catch, which is a hairline moving by a pixel or a number changing weight.

It runs on `windows-latest` because Playwright suffixes a snapshot filename with the platform that
recorded it and every committed baseline is `-win32.png`. On ubuntu it would look for `-linux.png`, find
nothing, and report a missing snapshot, which reads as a regression and is not one.

## The finding

The baselines were last written on 2026-08-27 in commit `bda5c332`. The visual job did not exist then, and
the audit run that followed was not permitted to start a server, so **they had never once been executed
until this job ran them**. The first execution failed on four of sixty eight tests:

| Test | Symptom |
|---|---|
| the accuracy page, light and dark | 5725 pixels differ, dimensions identical |
| a jurisdiction profile, light and dark | expected 1280x2156, received 1280x1781, 29358 pixels differ |

The coverage table passed, which is what made the first two explanations wrong.

## Why it was not the brand rename

The obvious answer was the rename of the public brand in this branch, which changed the header wordmark and
the footer disclaimer. That was recorded as the reason in the pull request description before any of this
ran, and it is wrong.

The coverage page carries the identical header and footer and its screenshot passes. A change to shared
layout produces the same absolute pixel difference on every page, so it would have broken all three.

## What it actually was

Neither `apps/web/src/app/accuracy/page.tsx` nor `apps/web/src/app/jurisdictions/[slug]/page.tsx` has any
commit on `main` after the baselines were recorded, and neither they nor `components/primitives.tsx` nor
`styles/tokens.css` are touched by this branch. The page code is therefore identical to the code that
produced the images, so the difference had to be data.

It was. The baselines were recorded against a developer database that held two published ledger entries.
CI seeds a fresh database from the committed registry and labels only, so its ledger is empty. That is the
whole of the accuracy page difference: the counts change in place and the height does not move. It also
explains why the coverage table passes, because its freshness column reads never in both environments,
`auspice ingest run` having been executed in neither.

## How that was proved rather than argued

The received image sits inside a 20 MB artifact that cannot be read without downloading and unzipping it,
so the argument could not be settled from the log. A data state diagnostic was added to the supervised
step instead, printing both payloads field by field before the build runs. It confirmed, against values
derived independently from `data/registry/jurisdictions.yaml` and `data/labels/decisions.yaml` beforehand:

```
accuracy   published 0, resolved 0, pending 0, chain entries 0, brier_score None
           anchor statement: Nothing has been published yet, so there is nothing to anchor.
Loudoun    2 bodies, Board of Supervisors 9 seats quorum 5, Planning Commission 9 seats quorum 5
           3 instruments, all three Loudoun rows from the labels file
           2 upcoming elections, 2027-11-02 and 2031-11-04, from anchor year 2023 on a 4 year term
           data_depth 0, discretion_index None, approval rates empty, freshness never
```

Every value is what the committed data implies. Both pages render correctly. Nothing was missing and
nothing was broken, so the expected images were the wrong side of the comparison.

The diagnostic stays in the workflow. It costs one HTTP request per page and it is the difference between
a screenshot failure that can be attributed and one that cannot.

## What was done

The baselines were re-recorded against the committed seed, so the gate is now reproducible from the
repository alone rather than from one laptop. Running the suite afterwards with no update flag gives
68 passed and no retries.

Re-recording needs Windows, so it is a `workflow_dispatch` input on the ci workflow called
`update_snapshots`. It runs the suite with `--update-snapshots` and commits the images back to the branch.
It is off by default and the pull request path never writes. Read the data state diagnostic first and
confirm the pages are right, because re-recording without that is how a real regression gets blessed as a
new baseline.

Only four images changed. `coverage-light-win32.png` and `coverage-dark-win32.png` were left byte
identical, which is a useful independent check that the re-record rewrote only what was genuinely stale.

## What will break these baselines next, and when

**The profile screenshot contains two election dates and they are derived rather than listed.**
`registry/elections.py` computes them from a term length and an anchor year, and the loader materialises a
window from twelve years back to eight years forward of the load date. The profile endpoint then returns
the next four elections on or after the current date.

Loudoun's Board of Supervisors sits on a four year term anchored on 2023, so the page shows 2027-11-02 and
2031-11-04 today. **After 2027-11-02 it will show 2031 and 2035 and the screenshot will fail.** That is not
a regression and it is not a reason to loosen the tolerance. Re-record with the dispatch above, or pick a
jurisdiction whose profile carries no date for this test.

The same applies the day the first prediction is published, because the accuracy page counts are in its
image.

## What this gate does not cover

Only the three pages above are compared as pixels, and only at 1280 wide in the two themes. The report
screen has no baseline. Nothing here proves the container image builds or that the memo renders, both of
which remain unverified because docker is absent from the machine this branch was written on.
