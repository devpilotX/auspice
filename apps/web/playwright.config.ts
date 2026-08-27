import { defineConfig, devices } from "@playwright/test";

/*
  Visual regression on the two screens that must never silently break: the accuracy page and the report.

  The accuracy page is the moat and the marketing, and it is the one page a sceptical buyer reads closely.
  The report is the product. A layout regression on either is not a cosmetic problem, it is a credibility
  problem, and a credibility problem is the only kind this company cannot recover from.

  Three settings that are decisions rather than defaults.

  Animations are disabled. There are exactly two in the product, the drawer at 180ms and the determination
  number counting into place at 400ms, and both would make a screenshot comparison flake for no benefit.

  The threshold is tight, at two tenths of a percent of pixels. A looser threshold hides exactly the class of
  regression this catches, which is a hairline moving by a pixel or a number changing weight.

  One browser. Chromium is what the PDF memo renders in, so the screen and the printed document share a
  layout engine and a regression in one shows up in the other.
*/

export default defineConfig({
  testDir: "./tests/visual",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",

  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.002,
      animations: "disabled",
      caret: "hide",
      scale: "css",
    },
  },

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // A fixed viewport, because a screenshot comparison against a variable one compares nothing.
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    timezoneId: "UTC",
    locale: "en-GB",
  },

  projects: [
    {
      name: "light",
      use: { ...devices["Desktop Chrome"], colorScheme: "light" },
    },
    {
      // Dark mode is a real second theme with its own token values, so it gets its own baselines rather
      // than being assumed to follow from the light ones.
      name: "dark",
      use: { ...devices["Desktop Chrome"], colorScheme: "dark" },
    },
  ],

  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run start",
        url: "http://127.0.0.1:3000",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
