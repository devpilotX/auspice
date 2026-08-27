/**
 * The coverage map.
 *
 * A map is the hardest thing on this site to test meaningfully, because a canvas that draws nothing looks
 * exactly like a canvas that draws correctly to any assertion about the DOM. So these check the things that
 * actually break: whether the tiles were fetched and returned, whether the worker was allowed to start, and
 * whether the map is optional in the way the page claims it is.
 */

import { expect, test } from "@playwright/test";

test.describe("coverage map", () => {
  test("fetches vector tiles and reports no console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => {
      errors.push(error.message);
    });

    const tiles: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes("/v1/tiles/jurisdictions/")) tiles.push(response.status());
    });

    await page.goto("/jurisdictions");

    // The map arrives after the page, so wait for its canvas rather than for a timeout.
    await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(2500);

    expect(tiles.length, "no tile requests were made, so the map is drawing nothing").toBeGreaterThan(0);
    expect(
      tiles.filter((status) => status === 200).length,
      `no tile returned 200. Statuses: ${tiles.join(", ")}`,
    ).toBeGreaterThan(0);

    // The CSP had to grant worker-src blob: for MapLibre to decode tiles. Without it the map is silent and
    // empty, and the only evidence is a console error, which is exactly the failure mode that shipped twice
    // on this project already.
    const blocked = errors.filter((message) => /Content Security Policy|worker/i.test(message));
    expect(blocked, `the browser blocked something the map needs: ${blocked.join(" | ")}`).toHaveLength(0);
    expect(errors, `console errors: ${errors.slice(0, 3).join(" | ")}`).toHaveLength(0);
  });

  test("the map does not carry a probability", async ({ page }) => {
    // Fill opacity encodes decision depth. If a future change bound it to a probability, the caption would
    // be the only thing saying otherwise, so the caption is asserted.
    await page.goto("/jurisdictions");
    await expect(page.getByText(/Shading is decision depth, not probability/)).toBeVisible();
  });

  test("the coverage table stands on its own", async ({ page }) => {
    // The whole justification for loading the map lazily is that the page is complete without it. Block the
    // chunk and the tiles, and the table must still be there.
    await page.route("**/tiles/**", (route) => route.abort());
    await page.goto("/jurisdictions");

    await expect(page.getByRole("table", { name: /Counties covered/i })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Loudoun County" })).toBeVisible();
  });

  test("a county is a link to its profile", async ({ page }) => {
    await page.goto("/jurisdictions");
    await expect(page.locator("a[href='/jurisdictions/us-va-loudoun']").first()).toBeVisible();
  });
});
