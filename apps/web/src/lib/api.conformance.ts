/**
 * Compile time proof that the hand written validation schemas agree with the API.
 *
 * `src/lib/api.ts` validates every response with Zod rather than trusting generated types, because a
 * generated type describes what the server promises while the schema describes what this interface
 * refuses to render without. That is the right call and it leaves one gap: nothing connects the two, so
 * a field renamed in the API would pass the build and fail at runtime in front of a user.
 *
 * This file closes the gap without weakening the schemas. It asserts assignability in the direction that
 * matters, generated to inferred, which catches a removed or renamed field while still allowing the Zod
 * schema to be stricter about ranges, nullability and enum membership. Nothing is exported and nothing
 * runs; `tsc --noEmit` is the whole test.
 *
 * If this file fails to compile, the API changed. Run `npm run types:generate`, read the diff in
 * `packages/shared-types/openapi.json`, then decide whether the interface should accept the new shape.
 * Do not widen a schema to silence it without that decision.
 */

import type {
  AccuracyResponse as GeneratedAccuracy,
  Determination as GeneratedDetermination,
  Driver as GeneratedDriver,
  Evidence as GeneratedEvidence,
  JurisdictionProfile as GeneratedJurisdictionProfile,
  JurisdictionSummary as GeneratedJurisdictionSummary,
  Precedent as GeneratedPrecedent,
  Score as GeneratedScore,
} from "@auspice/shared-types";

import type {
  Accuracy,
  Determination,
  Driver,
  Evidence,
  JurisdictionProfile,
  JurisdictionSummary,
  Precedent,
  Score,
} from "./api";

/** The keys the interface reads whose type is not compatible with what the API serves. */
type DisagreeingFields<Generated, Inferred> = {
  [K in keyof Inferred & keyof Generated]: Generated[K] extends Inferred[K] | null | undefined
    ? never
    : K;
}[keyof Inferred & keyof Generated];

/** Every field the interface reads must exist in the generated type at all. */
type NoUnknownFields<Generated, Inferred> = Exclude<keyof Inferred, keyof Generated> extends never
  ? true
  : ["fields absent from the API", Exclude<keyof Inferred, keyof Generated>];

/**
 * No field may disagree in type unless the narrowing is named in `Narrowed`.
 *
 * The interface is allowed to be stricter than the API, and in a risk product it should be. What it is
 * not allowed to be is accidentally stricter, because that renders as an error in front of a user for a
 * response the server considers valid. Naming each narrowing is the difference between a decision and a
 * mistake, and it means a new unexplained one still fails the build.
 */
type FieldsAgree<Generated, Inferred, Narrowed extends keyof Inferred = never> = Exclude<
  DisagreeingFields<Generated, Inferred>,
  Narrowed
> extends never
  ? true
  : ["fields disagree with the API", Exclude<DisagreeingFields<Generated, Inferred>, Narrowed>];

// -- assertions -------------------------------------------------------------
// Each line fails to compile if the interface reads a field the API does not serve.
type _Score = NoUnknownFields<GeneratedScore, Score>;
type _Determination = NoUnknownFields<GeneratedDetermination, Determination>;
type _Driver = NoUnknownFields<GeneratedDriver, Driver>;
type _Precedent = NoUnknownFields<GeneratedPrecedent, Precedent>;
type _Evidence = NoUnknownFields<GeneratedEvidence, Evidence>;
type _JurisdictionSummary = NoUnknownFields<GeneratedJurisdictionSummary, JurisdictionSummary>;
type _JurisdictionProfile = NoUnknownFields<GeneratedJurisdictionProfile, JurisdictionProfile>;
type _Accuracy = NoUnknownFields<GeneratedAccuracy, Accuracy>;

const present: [
  _Score,
  _Determination,
  _Driver,
  _Precedent,
  _Evidence,
  _JurisdictionSummary,
  _JurisdictionProfile,
  _Accuracy,
] = [true, true, true, true, true, true, true, true];

// Checked on the objects carrying a number or a citation, where a mismatch is most costly.
//
// `Evidence.verified` is the one named narrowing. The API types it `boolean`; the schema types it
// `z.literal(true)`, so a response containing an unverified quote fails validation instead of drawing a
// citation nobody checked. The API does not send one today, and this is the layer that does not depend on
// that staying true.
const compatible: [
  FieldsAgree<GeneratedDriver, Driver>,
  FieldsAgree<GeneratedPrecedent, Precedent>,
  FieldsAgree<GeneratedEvidence, Evidence, "verified">,
] = [true, true, true];

void present;
void compatible;
