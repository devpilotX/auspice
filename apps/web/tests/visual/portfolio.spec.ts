/**
 * The portfolio screen. Section 5.4 product 2.
 *
 * The assertion that matters is the last one. An abstention must not be renderable as a row in the ranked
 * table, because a reader scanning one ranked column reads the bottom row as the worst site whatever the
 * cell says. Sorting abstentions last is not enough; they have to be somewhere else on the page.
 */

import { expect, type Page, test } from "@playwright/test";

const SCORED = {
  label: "Pageland Road",
  jurisdiction: "Loudoun County",
  approval_probability: 0.62,
  credible_interval_80: [0.48, 0.74],
  abstained: false,
  months_p50: 14,
  rule_change_probability: 0.09,
  data_depth: 22,
  stale: false,
  public_id: "scored-site-0001",
};

const ABSTAINED = {
  label: "Cedar Rapids West",
  jurisdiction: "Linn County",
  approval_probability: null,
  credible_interval_80: null,
  abstained: true,
  months_p50: null,
  rule_change_probability: null,
  data_depth: 0,
  stale: false,
  public_id: "abstained-site-0001",
};

const RESPONSE = {
  ranked: [SCORED, ABSTAINED],
  submitted: 2,
  scored: 1,
  abstained: 1,
  note: "Ranked by approval probability. Abstentions sort last and carry no number.",
};

/**
 * Intercept the API rather than run it.
 *
 * The corpus abstains on every site today, so a live request could not exercise the scored path at all.
 * Fixing the response is the only way to assert that a scored row and an abstention render differently,
 * which is the behaviour under test. The shape is the one the API's own schema validates, and
 * `tests/unit/test_abstention_and_score.py` is what keeps the two in agreement.
 */
async function stubPortfolio(page: Page, body: unknown) {
  await page.route("**/v1/portfolio", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test.describe("portfolio triage", () => {
  test("ranks the scored sites and separates the ones we would not score", async ({ page }) => {
    await stubPortfolio(page, RESPONSE);
    await page.goto("/portfolio");

    await expect(page.getByRole("heading", { name: "Portfolio triage" })).toBeVisible();

    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    await expect(page.getByRole("heading", { name: "Ranked", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "We do not know" })).toBeVisible();

    // The scored site appears with its number. The abstention appears with no number anywhere.
    const ranked = page.getByRole("table", { name: /^Ranked by approval probability/i });
    await expect(ranked.getByText("Pageland Road")).toBeVisible();
    await expect(ranked.getByText("62%")).toBeVisible();
    await expect(ranked.getByText("Cedar Rapids West")).toHaveCount(0);

    const notScored = page.getByRole("table", { name: /would not score/i });
    await expect(notScored.getByText("Cedar Rapids West")).toBeVisible();
  });

  test("the not scored table has no probability column at all", async ({ page }) => {
    await stubPortfolio(page, RESPONSE);
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    const notScored = page.getByRole("table", { name: /would not score/i });
    const headers = await notScored.locator("th").allInnerTexts();

    // Not a blank cell and not a dash where a number would go. Both of those read as a number withheld,
    // and there is no number to withhold.
    expect(headers.map((h) => h.toLowerCase())).not.toContain("approval");
    expect(headers.map((h) => h.toLowerCase())).not.toContain("80% interval");
  });

  test("says plainly when nothing could be scored", async ({ page }) => {
    await stubPortfolio(page, {
      ranked: [ABSTAINED],
      submitted: 1,
      scored: 0,
      abstained: 1,
      note: RESPONSE.note,
    });
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    await expect(page.getByText("We did not put a number on any of these sites.")).toBeVisible();
  });

  test("no probability is coloured", async ({ page }) => {
    await stubPortfolio(page, RESPONSE);
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    // The same assertion the design system suite makes. A green 62 percent reads as advice.
    const statusColours = [
      "rgb(45, 106, 79)",
      "rgb(155, 106, 26)",
      "rgb(155, 44, 44)",
      "rgb(43, 90, 138)",
      "rgb(107, 91, 149)",
      "rgb(122, 122, 122)",
    ];
    const numerics = page.locator("[data-numeric]");
    const count = await numerics.count();
    expect(count).toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const colour = await numerics
        .nth(index)
        .evaluate((element) => window.getComputedStyle(element).color);
      expect(statusColours).not.toContain(colour);
    }
  });

  test("a pasted list replaces the rows", async ({ page }) => {
    await stubPortfolio(page, RESPONSE);
    await page.goto("/portfolio");

    await page.getByLabel("Paste a list of sites").fill(
      [
        "Site,County,Use class,Acres,MW",
        "Pageland Road,Loudoun County,data_center_hyperscale,412,300",
        "Cedar Rapids West,Linn County,solar_utility,900,",
      ].join("\n"),
    );
    await page.getByRole("button", { name: "read the list" }).click();

    // Replaced, not appended. Three blank rows plus two pasted would be five.
    await expect(page.getByRole("button", { name: /score 2 sites/ })).toBeVisible();
    await expect(page.getByLabel("Label for site 1")).toHaveValue("Pageland Road");
    await expect(page.getByLabel("Acres for site 1")).toHaveValue("412");
    await expect(page.getByLabel("Jurisdiction for site 2")).toHaveValue("us-ia-linn");
  });

  test("a county we do not cover is named, not guessed at", async ({ page }) => {
    await page.goto("/portfolio");

    await page.getByLabel("Paste a list of sites").fill(
      [
        "Good,Loudoun County,data_center_hyperscale,100,50",
        "Bad,Loudon,data_center_hyperscale,100,50",
      ].join("\n"),
    );
    await page.getByRole("button", { name: "read the list" }).click();

    // Loudon is a real county in Tennessee and one letter from Loudoun. Matching it would score the wrong
    // jurisdiction and look entirely normal doing so.
    await expect(page.getByText("1 row we could not read")).toBeVisible();
    await expect(page.getByText(/we do not cover Loudon/)).toBeVisible();
    await expect(page.getByText("line 2")).toBeVisible();
    // The good row still loaded.
    await expect(page.getByRole("button", { name: /score 1 site/ })).toBeVisible();
  });

  test("says what happened when the API does not answer", async ({ page }) => {
    await page.route("**/v1/portfolio", async (route) => {
      await route.abort("connectionrefused");
    });
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    await expect(page.getByText("The API did not answer. Nothing was scored.")).toBeVisible();
  });

  test("refuses to render an abstention carrying a probability", async ({ page }) => {
    // The malformation that would be invisible: the row would look like a low score. The Zod schema
    // rejects the whole response, so the page says it could not read the answer rather than drawing it.
    await stubPortfolio(page, {
      ranked: [{ ...ABSTAINED, approval_probability: 0.11, credible_interval_80: [0.02, 0.2] }],
      submitted: 1,
      scored: 0,
      abstained: 1,
      note: RESPONSE.note,
    });
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    await expect(page.getByText(/could not read/)).toBeVisible();
    await expect(page.getByText("11%")).toHaveCount(0);
  });

  test("refuses a summary whose counts do not add up", async ({ page }) => {
    await stubPortfolio(page, {
      ranked: [SCORED, ABSTAINED],
      submitted: 2,
      scored: 2,
      abstained: 1,
      note: RESPONSE.note,
    });
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /score \d+ sites?/ }).click();

    await expect(page.getByText(/could not read/)).toBeVisible();
  });
});
