import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/*
  Unit tests for the pure logic in src/lib.

  Scoped deliberately narrowly. Playwright already covers what the pages render, and duplicating that
  here in a simulated DOM would give two suites that disagree about the same behaviour. What Playwright
  cannot cover cheaply is the parsing: a CSV with a quoted county name, a markdown construct the reader
  refuses, a megawatt figure with a unit suffix. Those are functions with arguments and return values,
  and they belong in a test that runs in a second without a browser.

  The environment is node rather than jsdom, because nothing under test touches the DOM. Adding jsdom
  would add a dependency and a startup cost to test string handling.
*/

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // The visual suite lives in tests/ and is run by Playwright. Without this exclusion Vitest tries to
    // collect it, fails on the Playwright imports, and reports a broken suite that is not broken.
    exclude: ["node_modules/**", ".next/**", "tests/**"],
  },
});
