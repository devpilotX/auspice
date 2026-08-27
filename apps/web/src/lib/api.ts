/**
 * The API client.
 *
 * Section 7.3 rule 4: every response is validated at the boundary before it renders. In a risk product,
 * silently rendering a malformed score is worse than showing an error, so the schemas here are the
 * narrow gate everything passes through.
 *
 * The schemas are hand written rather than generated, and that is deliberate for exactly one reason:
 * generated types describe the shape the server promises, while these describe the shape this interface
 * refuses to render without. They are stricter on purpose. `packages/shared-types` holds the generated
 * version, and `npm run types:generate` keeps it current for consumers who want the full surface.
 */

import { z } from "zod";

import { apiBaseUrl } from "./api-origin";

const BASE_URL = apiBaseUrl();

const probability = z.number().min(0).max(1);

export const jurisdictionLinkSchema = z.object({
  level: z.string(),
  name: z.string(),
  slug: z.string(),
  role: z.string(),
  data_depth: z.number().int().nonnegative(),
  discretion_index: probability.nullable(),
});

export const timeToDecisionSchema = z.object({
  p10: z.number().positive(),
  p50: z.number().positive(),
  p90: z.number().positive(),
  basis: z.enum(["fitted", "empirical"]),
});

export const determinationSchema = z
  .object({
    approval_probability: probability.nullable(),
    credible_interval_80: z.tuple([probability, probability]).nullable(),
    interval_kind: z.enum(["credible", "bootstrap"]).nullable(),
    confidence: z.enum(["low", "medium", "high"]).nullable(),
    abstained: z.boolean(),
    abstention_reasons: z.array(z.string()),
    time_to_decision_months: timeToDecisionSchema.nullable(),
    probability_of_rule_change_before_decision: probability.nullable(),
    local_base_rate: probability.nullable(),
  })
  // The same invariant the Python model enforces, restated here so a malformed response cannot render.
  // A number without an interval, or an abstention carrying a number, is refused rather than drawn.
  .refine(
    (value) =>
      value.abstained
        ? value.approval_probability === null
        : value.approval_probability !== null && value.credible_interval_80 !== null,
    {
      message:
        "A determination must either abstain with no number, or carry both a probability and an interval.",
    },
  );

export const evidenceSchema = z.object({
  evidence_id: z.string(),
  document_id: z.string(),
  document_title: z.string().nullable(),
  document_kind: z.string().nullable(),
  source_url: z.string(),
  page: z.number().int().positive().nullable(),
  quote: z.string().min(1),
  // An unverified quote never renders. The API refuses to send one; this refuses to draw one.
  verified: z.literal(true),
  retrieved_on: z.string().nullable(),
  speaker: z.string().nullable(),
  timestamp: z.string().nullable(),
});

export const driverSchema = z.object({
  factor: z.string(),
  group: z.string(),
  direction: z.enum(["positive", "negative", "neutral"]),
  weight: probability,
  plain_language: z.string().min(1),
  evidence_id: z.string().nullable(),
  value: z.number().nullable(),
});

export const precedentSchema = z.object({
  application_id: z.number().int(),
  external_id: z.string().nullable(),
  jurisdiction: z.string(),
  similarity: probability,
  outcome: z.string(),
  vote: z.string().nullable(),
  months_to_decision: z.number().nullable(),
  decided_on: z.string().nullable(),
  objection_grounds: z.array(z.string()),
  evidence_id: z.string().nullable(),
  basis: z.record(z.string(), z.number()),
});

export const provenanceSchema = z.object({
  model_version: z.string(),
  model_kind: z.string(),
  feature_set_version: z.string(),
  dataset_hash: z.string(),
  data_as_of: z.string(),
  documents_used: z.number().int().nonnegative(),
  jurisdiction_data_depth: z.string(),
  pooled: z.boolean(),
  pooling_weight: probability,
  pooling_note: z.string().nullable(),
  stale: z.boolean(),
  staleness_days: z.number().int().nullable(),
  features_missing: z.array(z.string()),
  disclaimer: z.string(),
});

export const scoreSchema = z.object({
  public_id: z.string(),
  generated_at: z.string(),
  site: z.object({
    parcel_ids: z.array(z.string()),
    label: z.string().nullable(),
    longitude: z.number().nullable(),
    latitude: z.number().nullable(),
    jurisdiction_chain: z.array(jurisdictionLinkSchema).min(1),
    use_class: z.string(),
    requested_relief: z.array(z.string()).min(1),
    by_right: z.boolean().nullable(),
    acres: z.number().nullable(),
    capacity_mw: z.number().nullable(),
  }),
  determination: determinationSchema,
  drivers: z.array(driverSchema),
  precedents: z.array(precedentSchema),
  mitigations: z.array(
    z.object({
      action: z.string(),
      expected_delta: z.number(),
      basis: z.string(),
    }),
  ),
  alternatives: z.array(
    z.object({
      jurisdiction: z.string(),
      jurisdiction_slug: z.string(),
      distance_km: z.number().nonnegative(),
      by_right: z.boolean().nullable(),
      approval_probability: probability.nullable(),
      abstained: z.boolean(),
      expected_value_rank: z.number(),
      note: z.string().nullable(),
    }),
  ),
  evidence: z.array(evidenceSchema),
  provenance: provenanceSchema,
  features_hash: z.string(),
});

export const accuracySchema = z.object({
  published: z.number().int().nonnegative(),
  resolved: z.number().int().nonnegative(),
  pending: z.number().int().nonnegative(),
  answered: z.number().int().nonnegative(),
  abstained: z.number().int().nonnegative(),
  brier_score: z.number().nullable(),
  chain: z.object({
    entries: z.number().int().nonnegative(),
    ok: z.boolean(),
    broken_at: z.number().int().nullable(),
    reason: z.string().nullable(),
    head: z.string().nullable(),
  }),
  misses: z.array(
    z.object({
      seq: z.number().int(),
      public_id: z.string().nullable(),
      jurisdiction: z.string().nullable(),
      predicted: z.number().nullable(),
      outcome: z.string().nullable(),
      note: z.string().nullable(),
    }),
  ),
  statement: z.string(),
  kill_test: z.unknown().nullable(),
});

export const jurisdictionSummarySchema = z.object({
  slug: z.string(),
  name: z.string(),
  kind: z.string(),
  region: z.string().nullable(),
  legal_framework: z.string().nullable(),
  civic_platform: z.string().nullable(),
  data_depth: z.number().int().nonnegative(),
  discretion_index: probability.nullable(),
  bodies: z.number().int().nonnegative(),
  elections_known: z.number().int().nonnegative(),
  has_boundary: z.boolean(),
  freshness: z.enum(["fresh", "stale", "broken", "never"]),
  hours_since_refresh: z.number().nullable(),
});

export const instrumentRowSchema = z.object({
  kind: z.string(),
  citation: z.string().nullable(),
  title: z.string().nullable(),
  adopted_on: z.string().nullable(),
  expires_on: z.string().nullable(),
  restrictions: z.record(z.string(), z.unknown()),
  applies_to_use_classes: z.array(z.string()),
});

export const bodyRowSchema = z.object({
  name: z.string(),
  kind: z.string(),
  seats: z.number().int().nullable(),
  quorum: z.number().int().nullable(),
  vote_threshold: z.string().nullable(),
  recommendation_is_binding: z.boolean().nullable(),
});

export const electionRowSchema = z.object({
  body: z.string(),
  election_date: z.string(),
  seats_contested: z.number().int().nullable(),
});

export const jurisdictionProfileSchema = z.object({
  summary: jurisdictionSummarySchema,
  approval_rate_by_use_class: z.record(z.string(), probability.nullable()),
  decisions: z.number().int().nonnegative(),
  instruments: z.array(instrumentRowSchema),
  bodies: z.array(bodyRowSchema),
  next_elections: z.array(electionRowSchema),
});

export type Score = z.infer<typeof scoreSchema>;
export type Determination = z.infer<typeof determinationSchema>;
export type Driver = z.infer<typeof driverSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Precedent = z.infer<typeof precedentSchema>;
export type Accuracy = z.infer<typeof accuracySchema>;
export type JurisdictionSummary = z.infer<typeof jurisdictionSummarySchema>;
export type JurisdictionProfile = z.infer<typeof jurisdictionProfileSchema>;

/* ---------------------------------------------------------------------------
   Portfolio. Section 5.4 product 2.
   --------------------------------------------------------------------------- */

export const portfolioRowSchema = z
  .object({
    label: z.string().nullable(),
    jurisdiction: z.string(),
    approval_probability: probability.nullable(),
    credible_interval_80: z.tuple([probability, probability]).nullable(),
    abstained: z.boolean(),
    months_p50: z.number().nonnegative().nullable(),
    rule_change_probability: probability.nullable(),
    data_depth: z.number().int().nonnegative(),
    stale: z.boolean(),
    public_id: z.string(),
  })
  // The same rule the score object enforces server side, enforced again here. An abstention carrying a
  // number is the one malformation that would be invisible on screen: the row would look like a low
  // score, and refusing to answer would become indistinguishable from answering pessimistically.
  .refine((row) => !row.abstained || row.approval_probability === null, {
    message: "an abstention cannot carry a probability",
    path: ["approval_probability"],
  })
  .refine((row) => row.approval_probability === null || row.credible_interval_80 !== null, {
    message: "a probability cannot be shown without its interval",
    path: ["credible_interval_80"],
  });

export const portfolioResponseSchema = z
  .object({
    ranked: z.array(portfolioRowSchema),
    submitted: z.number().int().nonnegative(),
    scored: z.number().int().nonnegative(),
    abstained: z.number().int().nonnegative(),
    note: z.string(),
  })
  // Checked again on the way in. The API asserts this too, and a summary that does not add up is worth
  // refusing twice: a header reading "3 scored, 3 not scored" out of 3 sites destroys confidence in
  // every number under it, and this is the layer that decides whether it gets drawn.
  .refine((value) => value.scored + value.abstained === value.submitted, {
    message: "the counts do not add up to the number of sites submitted",
    path: ["scored"],
  })
  .refine((value) => value.ranked.length === value.submitted, {
    message: "every submitted site gets a row, including the ones we would not score",
    path: ["ranked"],
  });

export const siteInputSchema = z.object({
  label: z.string().max(120).nullable(),
  jurisdiction: z.string().min(1),
  use_class: z.string().min(1),
  relief_sought: z.array(z.string()).min(1).max(8),
  acres: z.number().positive().max(1_000_000).nullable(),
  capacity_mw: z.number().positive().max(100_000).nullable(),
});

export type PortfolioRow = z.infer<typeof portfolioRowSchema>;
export type PortfolioResponse = z.infer<typeof portfolioResponseSchema>;
export type SiteInput = z.infer<typeof siteInputSchema>;

export class ApiUnavailable extends Error {
  constructor(
    readonly path: string,
    readonly cause_: unknown,
  ) {
    super(`The API did not answer for ${path}.`);
    this.name = "ApiUnavailable";
  }
}

/**
 * Fetch and validate. Returns null when the API is unreachable, so a page can say so plainly instead
 * of rendering a skeleton that never fills in.
 */
export async function get<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T | null> {
  const headers = new Headers(init?.headers);
  headers.set("accept", "application/json");

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers,
      // The accuracy record and the profiles are public and change slowly. Sixty seconds keeps the
      // page fast without ever showing a number that is more than a minute behind the ledger.
      next: { revalidate: 60 },
    });
  } catch {
    return null;
  }

  if (!response.ok) return null;

  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    // Loud in development, silent to the visitor. A malformed response is our bug, not theirs, and
    // the page falls back to saying the data is unavailable rather than drawing something wrong.
    if (process.env.NODE_ENV !== "production") {
      console.error(`response failed validation for ${path}`, parsed.error.issues);
    }
    return null;
  }
  return parsed.data;
}

/**
 * Post and validate. Distinguishes the three outcomes a caller has to tell apart: a valid answer, a
 * request the API rejected, and an API that did not answer at all.
 *
 * `get` collapses every failure to null, which is right for a public page whose only recourse is to say
 * the data is unavailable. A form needs more. "The API is down" and "you asked for a jurisdiction we do
 * not cover" call for different words on screen, and showing the same message for both would send
 * someone looking for a network problem that does not exist.
 */
export type PostResult<T> =
  | { ok: true; data: T }
  | { ok: false; kind: "rejected"; status: number; detail: string }
  | { ok: false; kind: "unreachable" }
  | { ok: false; kind: "malformed" };

export async function post<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<PostResult<T>> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return { ok: false, kind: "unreachable" };
  }

  if (!response.ok) {
    return { ok: false, kind: "rejected", status: response.status, detail: await detailOf(response) };
  }

  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    if (process.env.NODE_ENV !== "production") {
      console.error(`response failed validation for ${path}`, parsed.error.issues);
    }
    return { ok: false, kind: "malformed" };
  }
  return { ok: true, data: parsed.data };
}

/** Read the most specific message the API offered, falling back to the status line. */
async function detailOf(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (payload === null || typeof payload !== "object" || !("detail" in payload)) {
      return `The API returned ${response.status}.`;
    }
    const raw = (payload as { detail: unknown }).detail;
    if (typeof raw === "string") return raw;
    // FastAPI validation errors arrive as an array of per field objects. Naming the field beats a
    // generic message that leaves someone guessing which of fourteen sites is wrong.
    if (Array.isArray(raw) && raw.length > 0) {
      const first = raw[0] as { loc?: unknown[]; msg?: unknown };
      const where = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      const message = typeof first.msg === "string" ? first.msg : "is not valid";
      return where === "" ? message : `${where}: ${message}`;
    }
    return `The API returned ${response.status}.`;
  } catch {
    // A body that is not JSON is not worth guessing at.
    return `The API returned ${response.status}.`;
  }
}

export const api = {
  accuracy: () => get("/v1/public/accuracy", accuracySchema),
  jurisdictions: () => get("/v1/public/jurisdictions", z.array(jurisdictionSummarySchema)),
  jurisdiction: (slug: string) =>
    get(`/v1/public/jurisdictions/${slug}`, jurisdictionProfileSchema),
  methodology: () => get("/v1/public/methodology", z.record(z.string(), z.unknown())),
  portfolio: (sites: SiteInput[]) => post("/v1/portfolio", { sites }, portfolioResponseSchema),
};
