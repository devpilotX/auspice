/**
 * Types generated from the API's OpenAPI document. One source of truth.
 *
 * `src/generated/api.ts` is written by `openapi-typescript` and is not edited by hand. This file exists
 * to give the web application short names for the handful of schemas it actually uses, because
 * `components["schemas"]["Score"]` at every call site is noise, and because a rename in the API should
 * break the build in one place rather than in thirty.
 *
 * To regenerate:
 *
 *     uv run python tools/export_openapi.py
 *     npm run generate --workspace packages/shared-types
 *
 * The document is exported from the application object rather than fetched over HTTP, so this works
 * without a running server. `npm run check:types-current` fails if the committed output is stale.
 */

import type { components, paths } from "./generated/api.js";

export type { components, paths };

type Schemas = components["schemas"];

// -- the score object, section 5.6 ------------------------------------------
export type Score = Schemas["Score"];
export type Determination = Schemas["Determination"];
export type Driver = Schemas["Driver"];
export type Precedent = Schemas["Precedent"];
export type Mitigation = Schemas["Mitigation"];
export type Alternative = Schemas["Alternative"];
export type Evidence = Schemas["Evidence"];
export type Provenance = Schemas["Provenance"];
export type Site = Schemas["Site"];
export type TimeToDecision = Schemas["TimeToDecision"];
export type ScoreRequest = Schemas["ScoreRequest"];

// -- portfolio, section 5.4 product 2 ---------------------------------------
export type PortfolioRequest = Schemas["PortfolioRequest"];
export type PortfolioResponse = Schemas["PortfolioResponse"];
export type PortfolioRow = Schemas["PortfolioRow"];

// -- the published record ---------------------------------------------------
export type AccuracyResponse = Schemas["AccuracyResponse"];
export type FreshnessRow = Schemas["FreshnessRow"];
export type JurisdictionSummary = Schemas["JurisdictionSummary"];
export type JurisdictionProfile = Schemas["JurisdictionProfile"];
export type JurisdictionLink = Schemas["JurisdictionLink"];
export type HealthResponse = Schemas["HealthResponse"];

// -- vocabularies -----------------------------------------------------------
// Unions of string literals, generated from the same Python enums that generate the database check
// constraints. A value the API cannot return is a value this type will not accept.
export type Outcome = Schemas["Outcome"];
export type UseClass = Schemas["UseClass"];
export type Relief = Schemas["Relief"];
export type ObjectionGround = Schemas["ObjectionGround"];
export type Confidence = Schemas["Confidence"];
export type AbstentionReason = Schemas["AbstentionReason"];
export type JurisdictionRole = Schemas["JurisdictionRole"];

/**
 * Narrow a score to the case where it carries a number.
 *
 * The score object holds `approval_probability` and `credible_interval_80` as nullable, because an
 * abstention has neither. A guard is better than a non-null assertion at each of the several places the
 * interface renders a probability: it makes the abstention branch impossible to forget, which is the
 * whole point of `abstained` being a first class field rather than a convention.
 */
export function hasNumber(
  determination: Determination,
): determination is Determination & {
  approval_probability: number;
  credible_interval_80: [number, number];
} {
  return (
    !determination.abstained &&
    determination.approval_probability !== null &&
    determination.approval_probability !== undefined &&
    determination.credible_interval_80 !== null &&
    determination.credible_interval_80 !== undefined
  );
}
