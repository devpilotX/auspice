/**
 * The portfolio proxy route.
 *
 * This route attaches an API key to whatever it forwards, so its input guards are the only thing standing
 * between the key and the internet. They are tested here for that reason, not for coverage.
 *
 * Every test uses a distinct x-forwarded-for value. The rate limiter holds its buckets in module state, so
 * a shared address would make the tests order dependent and the failure would look like a flake.
 */

import { expect, test } from "@playwright/test";

import { POST } from "../../src/app/api/portfolio/route";

let address = 0;
function request(body: unknown, extra: Record<string, string> = {}): Request {
  address += 1;
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  return new Request("http://localhost/api/portfolio", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": `203.0.113.${address}`,
      ...extra,
    },
    body: payload,
  });
}

const site = { jurisdiction: "us-va-loudoun", use_class: "data_center_hyperscale", relief_sought: ["rezoning"] };

/**
 * The detail string from a refusal.
 *
 * `Response.json()` is typed as returning any, and the project's eslint configuration refuses member
 * access on an any value, correctly: it is the same hole that lets a renamed field read as undefined
 * without anything failing. Narrowing once here keeps that rule intact.
 */
async function detailOf(response: Response): Promise<string> {
  const body: unknown = await response.json();
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : "";
  }
  return "";
}

test.describe("portfolio proxy, input guards", () => {
  test("refuses a body that is not JSON", async () => {
    const response = await POST(request("not json at all"));
    expect(response.status).toBe(400);
    expect(await detailOf(response)).toBe("That request body is not JSON.");
  });

  test("refuses an object with no sites array", async () => {
    const response = await POST(request({ nope: true }));
    expect(response.status).toBe(400);
    expect(await detailOf(response)).toContain("sites array");
  });

  test("refuses sites that is not an array", async () => {
    const response = await POST(request({ sites: "one, two" }));
    expect(response.status).toBe(400);
    expect(await detailOf(response)).toContain("to be an array");
  });

  test("refuses an empty list rather than forwarding it", async () => {
    const response = await POST(request({ sites: [] }));
    expect(response.status).toBe(400);
    expect(await detailOf(response)).toContain("No sites");
  });

  test("refuses more than five hundred sites and names the count", async () => {
    // 500 is the API's own cap. Matching it means the refusal states the real reason rather than a
    // number the customer cannot reconcile with the documentation.
    const response = await POST(request({ sites: Array.from({ length: 501 }, () => site) }));
    expect(response.status).toBe(400);
    const detail = await detailOf(response);
    expect(detail).toContain("501");
    expect(detail).toContain("500");
  });

  test("refuses an oversized body on the declared content length, before reading it", async () => {
    // The cap is checked against the header so a large body is refused without being read into memory.
    const response = await POST(
      request({ sites: [site] }, { "content-length": String(2_000_000) }),
    );
    expect(response.status).toBe(413);
  });
});

test.describe("portfolio proxy, rate limiting", () => {
  test("allows a burst of three then refuses with Retry-After", async () => {
    // One fixed address for this test, so the bucket is shared across the four calls on purpose.
    const fixed = () =>
      new Request("http://localhost/api/portfolio", {
        method: "POST",
        headers: { "content-type": "application/json", "x-forwarded-for": "198.51.100.7" },
        body: JSON.stringify({ sites: [] }),
      });

    // The first three spend the burst. They return 400 because the list is empty, which is fine: reaching
    // the validation stage is proof the limiter allowed them through.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const response = await POST(fixed());
      expect(response.status, `attempt ${attempt + 1} should pass the limiter`).toBe(400);
    }

    const refused = await POST(fixed());
    expect(refused.status).toBe(429);
    expect(refused.headers.get("retry-after")).not.toBeNull();
    expect(await detailOf(refused)).toContain("Too many requests");
  });

  test("a different address has its own allowance", async () => {
    const other = new Request("http://localhost/api/portfolio", {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": "198.51.100.200" },
      body: JSON.stringify({ sites: [] }),
    });
    // Not 429, because the previous test exhausted a different bucket.
    expect((await POST(other)).status).toBe(400);
  });
});
