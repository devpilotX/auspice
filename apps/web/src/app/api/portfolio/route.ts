/**
 * Server side proxy for portfolio screening.
 *
 * Why this exists. `/v1/portfolio` requires an API key. The portfolio screen is a client component, and
 * `lib/api.ts` sent no key at all, so the request only ever succeeded in development, where an empty
 * `AUSPICE_API_KEYS` makes `KeyRing.is_open` true and every caller is treated as an enterprise principal.
 * In production `Settings` refuses to start without keys, so the browser received 401 and the wedge feature
 * of the whole product was unreachable outside a laptop. There was no route handler anywhere in this app to
 * proxy through, so there was nowhere for the key to live except the client bundle, where it must never be.
 *
 * The key is read from `AUSPICE_API_KEY`, without the `NEXT_PUBLIC_` prefix, which is what keeps it on the
 * server. `src/app/report/[publicId]/page.tsx` already reads it the same way for the same reason.
 *
 * ## What this is not
 *
 * It is not an open relay. A route that forwards anything to an authenticated endpoint has donated the
 * key to the internet. Three limits apply before anything is forwarded: a byte cap on the request, a cap
 * on the number of sites, and a rate limit per client address.
 *
 * The rate limit is a token bucket in this process, and its weaknesses are the same as the ones
 * `apps/api/app/ratelimit.py` documents for its own: it does not survive more than one Node process, and
 * it is no defence against a distributed source, because per address limiting cannot be. It stops a loop,
 * a misconfigured client and a scraper, which is what is actually likely. Stated here rather than
 * discovered later.
 *
 * Note also that the API applies its own limit to `/v1/portfolio`, at 0.5 per second with a burst of 3.
 * That one is charged to the key, so every visitor to this page shares it. This limit exists so one
 * visitor cannot consume the shared allowance for everyone.
 */

import { apiBaseUrl } from "@/lib/api-origin";

/** The API accepts up to 500 sites per request. Matching it here means the refusal names the real reason. */
const MAX_SITES = 500;

/**
 * A byte cap, checked before the body is read into memory.
 *
 * 500 sites of the widest plausible row is well under 200 kB. A megabyte leaves generous headroom and
 * still refuses a body that could not be a portfolio.
 */
const MAX_BYTES = 1_000_000;

const LIMIT_PER_SECOND = 0.5;
const LIMIT_BURST = 3;
const IDLE_EVICT_MS = 300_000;

interface Bucket {
  tokens: number;
  last: number;
}

/**
 * Buckets keyed by client address, swept so the map cannot grow without bound.
 *
 * An unbounded map keyed by address is itself a denial of service, because a client rotating addresses
 * exhausts memory. A swept bucket is recreated full, which is safe: a client idle long enough to be
 * evicted has earned a full bucket anyway.
 */
const buckets = new Map<string, Bucket>();
let lastSweep = 0;

function allow(key: string, now: number): number | null {
  if (now - lastSweep > 60_000) {
    lastSweep = now;
    for (const [held, bucket] of buckets) {
      if (now - bucket.last > IDLE_EVICT_MS) buckets.delete(held);
    }
  }

  let bucket = buckets.get(key);
  if (bucket === undefined) {
    bucket = { tokens: LIMIT_BURST, last: now };
    buckets.set(key, bucket);
  }

  const elapsed = Math.max(0, now - bucket.last) / 1000;
  bucket.tokens = Math.min(LIMIT_BURST, bucket.tokens + elapsed * LIMIT_PER_SECOND);
  bucket.last = now;

  if (bucket.tokens >= 1) {
    bucket.tokens -= 1;
    return null;
  }
  return Math.ceil((1 - bucket.tokens) / LIMIT_PER_SECOND);
}

/**
 * Who to charge.
 *
 * The leftmost entry of `x-forwarded-for` is the client as the nearest proxy saw it. A client can set that
 * header freely when nothing overwrites it, so this is a best effort key rather than an identity, and the
 * caps above are what actually bound the damage.
 */
function clientKey(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const first = forwarded?.split(",")[0]?.trim();
  return first !== undefined && first !== "" ? first : "unknown";
}

function json(body: unknown, status: number, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export async function POST(request: Request): Promise<Response> {
  const wait = allow(clientKey(request), Date.now());
  if (wait !== null) {
    return json(
      {
        detail:
          `Too many requests. This screen allows ${LIMIT_PER_SECOND} per second with a burst of ` +
          `${LIMIT_BURST}. Retry in ${wait} second(s).`,
      },
      429,
      { "retry-after": String(wait) },
    );
  }

  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > MAX_BYTES) {
    return json({ detail: `That request is larger than ${MAX_BYTES} bytes.` }, 413);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ detail: "That request body is not JSON." }, 400);
  }

  // Shape checked here rather than trusted, because whatever passes this point is sent with a key
  // attached. The API validates it properly; this only refuses what obviously is not a portfolio.
  if (typeof body !== "object" || body === null || !("sites" in body)) {
    return json({ detail: "Expected an object with a sites array." }, 400);
  }
  const sites = (body as { sites: unknown }).sites;
  if (!Array.isArray(sites)) {
    return json({ detail: "Expected sites to be an array." }, 400);
  }
  if (sites.length === 0) {
    return json({ detail: "No sites to screen." }, 400);
  }
  if (sites.length > MAX_SITES) {
    return json(
      { detail: `That is ${sites.length} sites. The most that can be screened at once is ${MAX_SITES}.` },
      400,
    );
  }

  const key = process.env.AUSPICE_API_KEY ?? "";

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/v1/portfolio`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        ...(key !== "" ? { "X-API-Key": key } : {}),
      },
      body: JSON.stringify({ sites }),
      cache: "no-store",
    });
  } catch {
    // The page distinguishes unreachable from rejected, so this has to stay distinguishable. 502 rather
    // than 500: the fault is upstream, and saying so shortens the search for whoever is on call.
    return json({ detail: "The scoring service did not answer." }, 502);
  }

  if (upstream.status === 401 || upstream.status === 403) {
    // Never pass an authentication failure through as itself. To a visitor it reads as their problem and
    // it is not: it means this deployment has no usable key. The log line is where the operator finds it.
    console.error(
      `portfolio proxy: upstream returned ${upstream.status}. AUSPICE_API_KEY is ${
        key === "" ? "not set" : "set but rejected"
      }.`,
    );
    return json({ detail: "Screening is not available on this deployment." }, 503);
  }

  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
