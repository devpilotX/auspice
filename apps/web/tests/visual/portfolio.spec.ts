import { expect, test } from "@playwright/test";

/*
  The portfolio page has three jobs that matter: it must preserve input order while the user is editing,
  rank only sites the model actually scored, and keep abstentions out of that ranking. A lender cannot
  distinguish "worst site" from "site the evidence does not support" if those two lists are collapsed.

  The browser intercepts the Next.js route that the client calls. Its handler owns the separately tested
  server-side proxy to /v1/portfolio, which Playwright browser routing cannot intercept.
*/

type SiteResult = {
  input_index: number;
  name: string;
  address: string;
  probability: number | null;
  interval_low: number | null;
  interval_high: number | null;
  confidence: "high" | "medium" | "low" | null;
  abstained: boolean;
  abstention_reasons: string[];
  comparable_count: number;
  top_positive_drivers: { label: string; effect: string }[];
  top_negative_drivers: { label: string; effect: string }[];
};

const RESULTS: SiteResult[] = [
  {
    input_index: 0,
    name: "Ironwood",
    address: "1 Grid Road, Leesburg VA",
    probability: 0.74,
    interval_low: 0.62,
    interval_high: 0.84,
    confidence: "high",
    abstained: false,
    abstention_reasons: [],
    comparable_count: 31,
    top_positive_drivers: [{ label: "Same use approved nearby", effect: "+8 pp" }],
    top_negative_drivers: [{ label: "Election before likely hearing", effect: "-3 pp" }],
  },
  {
    input_index: 1,
    name: "Juniper",
    address: "2 Relay Lane, Phoenix AZ",
    probability: null,
    interval_low: null,
    interval_high: null,
    confidence: null,
    abstained: true,
    abstention_reasons: ["Fewer than five comparable decided applications"],
    comparable_count: 2,
    top_positive_drivers: [],
    top_negative_drivers: [],
  },
  {
    input_index: 2,
    name: "Keystone",
    address: "3 Power Court, Manassas VA",
    probability: 0.51,
    interval_low: 0.34,
    interval_high: 0.68,
    confidence: "low",
    abstained: false,
    abstention_reasons: [],
    comparable_count: 12,
    top_positive_drivers: [{ label: "Staff recommendation", effect: "+5 pp" }],
    top_negative_drivers: [{ label: "Opposition trend", effect: "-7 pp" }],
  },
];

async function enterSites(page: import("@playwright/test").Page) {
  const input = page.getByLabel("Sites to rank");
  await input.fill(
    [
      "Ironwood | 1 Grid Road, Leesburg VA | data_center | 300 | 420",
      "Juniper | 2 Relay Lane, Phoenix AZ | data_center | 180 | 300",
      "Keystone | 3 Power Court, Manassas VA | industrial | 80 | 120",
    ].join("\n"),
  );
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/portfolio", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        scored: [RESULTS[0], RESULTS[2]],
        abstained: [RESULTS[1]],
        summary: { submitted: 3, scored: 2, abstained: 1 },
      }),
    });
  });
  await page.goto("/portfolio");
});

test("ranks scored sites and separates abstentions", async ({ page }) => {
  await enterSites(page);
  await page.getByRole("button", { name: "Rank sites" }).click();

  await expect(page.getByRole("heading", { name: "Ranked sites" })).toBeVisible();
  await expect(page.getByText("2 scored")).toBeVisible();
  await expect(page.getByText("1 abstained")).toBeVisible();

  const rows = page.locator("table").first().locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Ironwood");
  await expect(rows.nth(1)).toContainText("Keystone");

  const abstained = page.locator('[aria-label="Sites not scored"]');
  await expect(abstained).toContainText("Juniper");
  await expect(abstained).toContainText("Fewer than five comparable");
});

test("renders drivers and intervals for committee review", async ({ page }) => {
  await enterSites(page);
  await page.getByRole("button", { name: "Rank sites" }).click();

  const ironwood = page.locator("table").first().locator("tbody tr").filter({ hasText: "Ironwood" });
  await expect(ironwood).toContainText("74%");
  await expect(ironwood).toContainText("62–84%");
  await expect(ironwood).toContainText("Same use approved nearby");
  await expect(ironwood).toContainText("Election before likely hearing");
});

test("rejects malformed lines before making a request", async ({ page }) => {
  await page.getByLabel("Sites to rank").fill("Only a name");
  await page.getByRole("button", { name: "Rank sites" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "Line 1 needs five fields: name, address, use class, capacity MW, acres.",
  );
  await expect(page.getByRole("heading", { name: "Ranked sites" })).not.toBeVisible();
});
