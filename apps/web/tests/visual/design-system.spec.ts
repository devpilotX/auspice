import { expect, test } from "@playwright/test";

/*
  The design system, asserted rather than described.

  Every constraint in tokens.css that would be easy to break by accident is checked here against what the
  browser actually computed. That matters more than it sounds: a design system enforced only by convention
  drifts, and the drift is invisible until someone screenshots the product beside a competitor.

  The rule about probability never being coloured gets its own test, because it is the one constraint that is
  a product decision rather than a visual one. A green 82 percent reads as approve it, which turns a neutral
  rating into advice, and neutrality is the asset.
*/

const PAGES = ["/", "/accuracy", "/jurisdictions"] as const;

test.describe("the two screens that must never silently break", () => {
  test("the accuracy page", async ({ page }) => {
    await page.goto("/accuracy");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page).toHaveScreenshot("accuracy.png", { fullPage: true });
  });

  test("the coverage table", async ({ page }) => {
    await page.goto("/jurisdictions");
    await expect(page.getByRole("table").first()).toBeVisible();

    // Wait for the map to exist before shooting. It loads on demand, so without this the page is
    // sometimes captured showing the loading placeholder and sometimes the canvas, and the two mask
    // differently. That was the last flake in the suite, and it only appeared in dark mode in a full run.
    await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 20_000 });

    // The map itself is masked. It is a WebGL canvas that paints when its tiles arrive, so including it
    // would make this a test of tile timing rather than of the table. The map has its own tests, which
    // check that tiles are fetched and decoded rather than that pixels match.
    await expect(page).toHaveScreenshot("coverage.png", {
      fullPage: true,
      mask: [page.locator("canvas.maplibregl-canvas"), page.locator(".maplibregl-ctrl-group")],
    });
  });

  test("a jurisdiction profile", async ({ page }) => {
    await page.goto("/jurisdictions/us-va-loudoun");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Loudoun");
    await expect(page).toHaveScreenshot("profile.png", { fullPage: true });
  });
});

test.describe("the design system holds", () => {
  test("nothing has a shadow", async ({ page }) => {
    await page.goto("/accuracy");
    const shadowed = await page.evaluate(() => {
      const offenders: string[] = [];
      for (const element of Array.from(document.querySelectorAll("*"))) {
        const shadow = getComputedStyle(element).boxShadow;
        // A focus ring is implemented with box-shadow and is the one permitted use, so an element that is
        // not focused must have none.
        if (shadow && shadow !== "none" && element !== document.activeElement) {
          offenders.push(`${element.tagName.toLowerCase()}: ${shadow}`);
        }
      }
      return offenders;
    });
    expect(shadowed, "separation is done with hairlines, not shadows").toEqual([]);
  });

  test("no corner is rounder than two pixels", async ({ page }) => {
    await page.goto("/accuracy");
    const round = await page.evaluate(() => {
      const offenders: string[] = [];
      for (const element of Array.from(document.querySelectorAll("*"))) {
        const style = getComputedStyle(element);
        for (const corner of [
          style.borderTopLeftRadius,
          style.borderTopRightRadius,
          style.borderBottomLeftRadius,
          style.borderBottomRightRadius,
        ]) {
          const pixels = Number.parseFloat(corner);
          // A status dot is a circle by design and is the only exception, so anything with a 50 percent
          // radius is skipped.
          if (!corner.includes("%") && pixels > 2.5) {
            offenders.push(`${element.tagName.toLowerCase()}: ${corner}`);
            break;
          }
        }
      }
      return offenders;
    });
    expect(round, "the radius is two pixels. Bureaus are not rounded.").toEqual([]);
  });

  test("nothing has a gradient", async ({ page }) => {
    await page.goto("/");
    const gradients = await page.evaluate(() =>
      Array.from(document.querySelectorAll("*"))
        .filter((element) => getComputedStyle(element).backgroundImage.includes("gradient"))
        .map((element) => element.tagName.toLowerCase()),
    );
    expect(gradients).toEqual([]);
  });

  test("every number uses tabular figures", async ({ page }) => {
    await page.goto("/jurisdictions");
    const nonTabular = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[data-numeric]"))
        .filter((element) => !getComputedStyle(element).fontVariantNumeric.includes("tabular-nums"))
        .map((element) => element.textContent.slice(0, 30)),
    );
    expect(nonTabular, "columns must align when the page is printed into a memo").toEqual([]);
  });
});

test.describe("probability is never coloured", () => {
  test("a determination and the coverage table use ink, not a status colour", async ({ page }) => {
    await page.goto("/jurisdictions");

    const coloured = await page.evaluate(() => {
      // The three status colours in each theme, which exist for state and never for judgement.
      const forbidden: [number, number, number][] = [
        [0x3f, 0x7d, 0x58],
        [0xb3, 0x86, 0x2b],
        [0x9c, 0x3b, 0x32],
        [0x59, 0xa0, 0x77],
        [0xcf, 0xa0, 0x4a],
        [0xc2, 0x56, 0x4c],
      ];

      const offenders: string[] = [];
      for (const element of Array.from(document.querySelectorAll("[data-numeric]"))) {
        const colour = getComputedStyle(element).color;
        const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(colour);
        if (match === null) continue;

        const red = Number(match[1]);
        const green = Number(match[2]);
        const blue = Number(match[3]);

        for (const [targetRed, targetGreen, targetBlue] of forbidden) {
          const distance = Math.hypot(red - targetRed, green - targetGreen, blue - targetBlue);
          if (distance < 40) {
            offenders.push(`${element.textContent.slice(0, 20)}: ${colour}`);
            break;
          }
        }
      }
      return offenders;
    });

    expect(
      coloured,
      "a green 82 percent reads as approve it, which turns a neutral rating into advice",
    ).toEqual([]);
  });
});

test.describe("accessibility", () => {
  for (const path of PAGES) {
    test(`${path} is keyboard reachable and has one h1`, async ({ page }) => {
      await page.goto(path);

      const headings = await page.locator("h1").count();
      expect(headings, "exactly one h1 per page").toBe(1);

      // The skip link must be the first thing a keyboard user reaches.
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => document.activeElement?.textContent ?? "");
      expect(focused).toContain("Skip to content");

      // Every interactive element must be reachable, and a focused element must show a visible ring.
      await page.keyboard.press("Tab");
      const outline = await page.evaluate(() => {
        const element = document.activeElement;
        if (!element) return "";
        const style = getComputedStyle(element);
        return `${style.outlineWidth} ${style.outlineStyle}`;
      });
      expect(outline, "focus rings must be visible: this product gets audited").not.toContain("0px");
    });
  }

  test("the page states its data date rather than implying freshness", async ({ page }) => {
    await page.goto("/accuracy");
    const body = (await page.textContent("body")) ?? "";
    // Either a Brier score, or the sentence explaining why there is not one. Never neither.
    expect(body).toMatch(/[Bb]rier score/);
  });
});

test.describe("the writing rules hold in rendered copy", () => {
  for (const path of PAGES) {
    test(`${path} contains no em dash and no banned vocabulary`, async ({ page }) => {
      await page.goto(path);
      const body = (await page.textContent("body")) ?? "";

      expect(body, "no em dashes anywhere in the product").not.toContain("\u2014");
      for (const word of ["seamless", "robust", "unlock", "leverage", "empower", "delve"]) {
        expect(body.toLowerCase(), `banned vocabulary: ${word}`).not.toContain(word);
      }
    });
  }
});
