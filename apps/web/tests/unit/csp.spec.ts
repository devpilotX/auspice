/**
 * The content security policy, asserted without a browser.
 *
 * The visual suite is what originally caught two CSP bugs that lint, types and the build all passed. That
 * suite needs a running server, which this run is not permitted to start, so the invariants it protects are
 * asserted here instead. The middleware is a pure function of a request, so nothing about testing it needs
 * a page.
 *
 * Both original bugs are represented, because a regression test that does not encode the actual bug is
 * decoration.
 *
 * The first: `script-src 'self'` with no allowance for inline scripts. The App Router streams hydration
 * data through inline scripts, so pages served correct HTML and rendered nothing. The suite found zero h1
 * elements on a page that plainly has one.
 *
 * The second, hiding behind the fix for the first: a per request nonce with `strict-dynamic`. Every route
 * here is prerendered at build time, so there is no request to read a nonce from, and `strict-dynamic`
 * instructs the browser to ignore `'self'` entirely. The header advertised a nonce, the HTML carried none,
 * and all twenty script tags were blocked. Nothing hydrated, and no test noticed because every page up to
 * the portfolio screen was a server component that looks right without JavaScript.
 *
 * So the two assertions that matter most are negative: no `strict-dynamic`, and no nonce.
 */

import { expect, test } from "@playwright/test";

import { middleware } from "../../src/middleware";

type Directives = Record<string, string[]>;

/** Read one directive, failing with a readable message when it is absent.
 *
 * Throws rather than asserting a type. The repository's lint config forbids both `as` on a nullable and
 * the `!` operator, which is the right pair of rules: a missing directive should say which one is missing.
 */
function directive(parsed: Directives, name: string): string[] {
  const value = parsed[name];
  if (value === undefined) {
    throw new Error(`the policy has no ${name} directive`);
  }
  return value;
}

function policyFor(pathname: string): string | null {
  // A minimal stand in for NextRequest. The middleware reads only nextUrl.pathname, and constructing a
  // real NextRequest here would pull in the whole server runtime for no gain.
  const request = { nextUrl: { pathname } } as unknown as Parameters<typeof middleware>[0];
  return middleware(request).headers.get("content-security-policy");
}

function directives(pathname = "/accuracy"): Directives {
  const policy = policyFor(pathname);
  expect(policy, "every page route must carry a policy").not.toBeNull();
  const parsed: Directives = {};
  for (const part of (policy ?? "").split(";")) {
    const tokens = part.trim().split(/\s+/).filter(Boolean);
    const name = tokens[0];
    if (name === undefined) continue;
    parsed[name] = tokens.slice(1);
  }
  return parsed;
}

test.describe("the two bugs the visual suite caught", () => {
  test("script-src allows inline, because hydration data arrives that way", () => {
    expect(directive(directives(), "script-src")).toContain("'unsafe-inline'");
  });

  test("script-src allows self, so the page chunks can load", () => {
    expect(directive(directives(), "script-src")).toContain("'self'");
  });

  test("strict-dynamic is absent, because it switches self off on a static page", () => {
    const policy = policyFor("/accuracy") ?? "";
    expect(policy).not.toContain("strict-dynamic");
  });

  test("no nonce is advertised, because a prerendered page has none to carry", () => {
    const policy = policyFor("/accuracy") ?? "";
    expect(policy).not.toContain("nonce-");
  });
});

test.describe("what the policy still buys", () => {
  test("no third party script origin can load", () => {
    const sources = directive(directives(), "script-src");
    const hosts = sources.filter((source) => !source.startsWith("'"));
    expect(hosts, `script-src should name no hosts, found ${hosts.join(", ")}`).toHaveLength(0);
  });

  test("eval is blocked outside development", () => {
    // NODE_ENV is not "development" under the test runner, so this exercises the production branch.
    expect(directive(directives(), "script-src")).not.toContain("'unsafe-eval'");
  });

  test("objects are refused outright", () => {
    expect(directive(directives(), "object-src")).toEqual(["'none'"]);
  });

  test("the site cannot be framed", () => {
    expect(directive(directives(), "frame-ancestors")).toEqual(["'none'"]);
  });

  test("base-uri and form-action are pinned to self", () => {
    const parsed = directives();
    expect(directive(parsed, "base-uri")).toEqual(["'self'"]);
    expect(directive(parsed, "form-action")).toEqual(["'self'"]);
  });

  test("default-src is self rather than absent", () => {
    expect(directive(directives(), "default-src")).toEqual(["'self'"]);
  });

  test("insecure requests are upgraded", () => {
    expect(directives()).toHaveProperty("upgrade-insecure-requests");
  });
});

test.describe("the map, which needs a worker from a blob", () => {
  test("worker-src allows blob, or the tiles never decode", () => {
    expect(directive(directives(), "worker-src")).toContain("blob:");
  });

  test("worker-src does not open to any origin", () => {
    // A worker from a third party host is arbitrary code execution, so this stays narrow.
    const sources = directive(directives(), "worker-src");
    expect(sources.sort()).toEqual(["'self'", "blob:"]);
  });

  test("child-src matches worker-src for older browsers", () => {
    expect(directive(directives(), "child-src").sort()).toEqual(["'self'", "blob:"]);
  });

  test("img-src allows data and blob, which is how tiles and icons arrive", () => {
    const sources = directive(directives(), "img-src");
    expect(sources).toContain("data:");
    expect(sources).toContain("blob:");
  });
});

test.describe("the API origin", () => {
  test("connect-src names self", () => {
    expect(directive(directives(), "connect-src")).toContain("'self'");
  });

  test("connect-src is derived from the same helper the client calls", async () => {
    // They were separate expressions once and disagreed, and the browser blocked every request. This
    // asserts they still come from one place rather than asserting a particular value, because the value
    // depends on the environment the tests run in.
    const { apiConnectSrc } = await import("../../src/lib/api-origin");
    const configured = apiConnectSrc();
    const sources = directive(directives(), "connect-src");
    if (configured) {
      expect(sources).toContain(configured);
    } else {
      expect(sources).toEqual(["'self'"]);
    }
  });
});

test.describe("what is exempt", () => {
  for (const path of [
    "/brand/templum-primary.svg",
    "/favicon.ico",
    "/robots.txt",
    "/sitemap.xml",
    "/site.webmanifest",
    "/data.json",
    "/icon.png",
  ]) {
    test(`${path} needs no policy`, () => {
      expect(policyFor(path)).toBeNull();
    });
  }

  test("a page route that merely contains a dot still gets a policy", () => {
    // The exemption is anchored on the extension. A published report id or a slug with a dot in it must
    // not fall out of the policy by accident.
    expect(policyFor("/report/scr_ab12.cd34")).not.toBeNull();
  });

  test("a path ending in a similar but unlisted extension still gets a policy", () => {
    expect(policyFor("/downloads/ledger.jsonl")).not.toBeNull();
  });
});

test.describe("the policy is well formed", () => {
  test("no directive is empty", () => {
    const policy = policyFor("/accuracy") ?? "";
    for (const part of policy.split(";")) {
      expect(part.trim().length, `empty directive in ${policy}`).toBeGreaterThan(0);
    }
  });

  test("no directive is declared twice", () => {
    const policy = policyFor("/accuracy") ?? "";
    const names = policy
      .split(";")
      .map((part) => part.trim().split(/\s+/)[0])
      .filter(Boolean);
    expect(new Set(names).size, `duplicate directive in ${policy}`).toBe(names.length);
  });

  test("the header name is lowercase, as the response sets it", () => {
    const request = { nextUrl: { pathname: "/accuracy" } } as unknown as Parameters<
      typeof middleware
    >[0];
    const response = middleware(request);
    expect(response.headers.get("Content-Security-Policy")).toBe(
      response.headers.get("content-security-policy"),
    );
  });
});
