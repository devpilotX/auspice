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

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

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

export const api = {
  accuracy: () => get("/v1/public/accuracy", accuracySchema),
  jurisdictions: () => get("/v1/public/jurisdictions", z.array(jurisdictionSummarySchema)),
  jurisdiction: (slug: string) =>
    get(`/v1/public/jurisdictions/${slug}`, jurisdictionProfileSchema),
  methodology: () => get("/v1/public/methodology", z.record(z.string(), z.unknown())),
};
