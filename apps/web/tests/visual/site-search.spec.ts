/**
 * Site search.
 *
 * The assertions that matter are the two refusals: a near miss county name returns nothing rather than the
 * closest match, and a coordinate outside coverage says so rather than showing an empty list.
 *
 * Runs against the live API rather than a stub, because the whole feature is a spatial join and stubbing it
 * would test the input box and nothing else.
 */

import { expect, test } from "@playwright/test";

test.describe("site search", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/jurisdictions");
  });

  test("a county name offers the county", async ({ page }) => {
    await page.getByLabel("Search for a county or a coordinate").fill("loudoun");
    await expect(page.getByRole("link", { name: /Loudoun County/ }).first()).toBeVisible();
  });

  test("a state name offers every county in it", async ({ page }) => {
    await page.getByLabel("Search for a county or a coordinate").fill("virginia");
    // Three of the twelve are in Virginia.
    const links = page.locator("a[href^='/jurisdictions/us-va-']");
    await expect(links).toHaveCount(3);
  });

  test("a near miss returns nothing rather than the closest name", async ({ page }) => {
    // Loudon is a real county in Tennessee. Offering Loudoun here would be a guess presented as an answer.
    await page.getByLabel("Search for a county or a coordinate").fill("loudonx");
    await expect(page.getByText(/Nothing matches loudonx/)).toBeVisible();
    await expect(page.getByText(/than show you the closest name/)).toBeVisible();
  });

  test("a coordinate inside coverage names who decides", async ({ page }) => {
    // Inside Loudoun County, near Leesburg.
    await page.getByLabel("Search for a county or a coordinate").fill("39.1157, -77.5636");

    // Wait for the lookup itself rather than for the text to appear. The suite runs four workers against a
    // single API process, so an assertion timeout here measures contention rather than correctness. This
    // failed only in the dark project and only in a full run, which is the signature of that.
    const response = page.waitForResponse(
      (candidate) => candidate.url().includes("/v1/public/locate") && candidate.status() === 200,
    );
    await page.getByRole("button", { name: "who decides here" }).click();
    await response;

    // Assert on the resolved chain rather than on prose. The earlier locator matched the button and the
    // paragraph explaining the feature as well as the result, which is a test that passes for the wrong
    // reason until strict mode catches it.
    const chain = page.getByRole("link", { name: /County/ });
    await expect(chain.first()).toBeVisible();
    await expect(page.getByText("primary decider")).toBeVisible();
  });

  test("a coordinate outside coverage says so", async ({ page }) => {
    await page.getByLabel("Search for a county or a coordinate").fill("10, -140");

    const response = page.waitForResponse(
      (candidate) => candidate.url().includes("/v1/public/locate") && candidate.status() === 200,
    );
    await page.getByRole("button", { name: "who decides here" }).click();
    await response;

    await expect(
      page.getByText("That point is outside the twelve counties we cover."),
    ).toBeVisible();
    await expect(page.getByText("primary decider")).toHaveCount(0);
  });

  test("the lookup button appears only for a coordinate", async ({ page }) => {
    const search = page.getByLabel("Search for a county or a coordinate");
    await search.fill("loudoun");
    await expect(page.getByRole("button", { name: "who decides here" })).toHaveCount(0);
    await search.fill("39.1157, -77.5636");
    await expect(page.getByRole("button", { name: "who decides here" })).toBeVisible();
  });
});
