import Link from "next/link";
import { notFound } from "next/navigation";

import { AbstentionNotice } from "@/components/abstention";
import { DeterminationBlock, MonthsStrip } from "@/components/determination";
import { DriversTable } from "@/components/drivers";
import { Caption, Label, Panel, Rule, StatusDot, Unavailable } from "@/components/primitives";
import { scoreSchema, type Score } from "@/lib/api";

/*
  The report screen. Section 5.7 puts this second among the screens and calls it the product, and the
  ordering on the page follows what a partner actually reads.

  The determination first, because that is what they came for. The caption second, set like a legal caption,
  because that is what tells them the number is about their site and not a similar one. Drivers next, each
  with the quote behind it one click away, followed by the precedents. Last comes the section that says what
  the model does not know, which is the part that makes the rest defensible.

  An abstention replaces the determination entirely rather than appearing beside a greyed out number. There
  is no code path here that renders both.

  The score arrives through a POST, so this route reads it from a server action rather than a query string.
  A probability in a URL is a probability that gets shared without its interval.
*/

async function fetchScore(publicId: string): Promise<Score | null> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
  const key = process.env.AUSPICE_API_KEY ?? "";

  let response: Response;
  try {
    response = await fetch(`${base}/v1/score/${publicId}`, {
      headers: { accept: "application/json", ...(key ? { "X-API-Key": key } : {}) },
      cache: "no-store",
    });
  } catch {
    return null;
  }
  if (!response.ok) return null;

  const parsed = scoreSchema.safeParse(await response.json());
  return parsed.success ? parsed.data : null;
}

export const metadata = {
  title: "Report",
  robots: { index: false, follow: false },
};

export default async function ReportPage({
  params,
}: {
  params: Promise<{ publicId: string }>;
}) {
  const { publicId } = await params;
  const score = await fetchScore(publicId);

  if (score === null) {
    return (
      <Unavailable
        what="We cannot retrieve that score."
        hint={
          "A score is retrievable for as long as its prediction is in the ledger. If this is a fresh " +
          "request, the API may not be running, or the key in AUSPICE_API_KEY may not cover it."
        }
      />
    );
  }

  const head = score.site.jurisdiction_chain[0];
  if (head === undefined) notFound();

  const determination = score.determination;

  return (
    <article className="space-y-14">
      {/* Caption header, set like a legal caption. */}
      <header>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <Label>permission risk report</Label>
            <h1
              className="mt-3"
              style={{
                fontFamily: "var(--font-serif)",
                fontSize: "var(--text-display-2)",
                lineHeight: 1.15,
                letterSpacing: "-0.02em",
                color: "var(--text-primary)",
              }}
            >
              {score.site.label ?? head.name}
            </h1>
            <p className="mt-2" style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}>
              {score.site.use_class.replaceAll("_", " ")} &middot;{" "}
              {score.site.requested_relief.map((r) => r.replaceAll("_", " ")).join(", ")}
            </p>
          </div>
          <div className="text-right">
            <div
              data-numeric
              className="font-mono"
              style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
            >
              {score.public_id}
            </div>
            <div
              data-numeric
              className="font-mono"
              style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
            >
              data as of {score.provenance.data_as_of}
            </div>
            {score.provenance.stale ? (
              <div className="mt-2">
                <StatusDot
                  state="stale"
                  label={`${String(score.provenance.staleness_days ?? 0)} days stale`}
                />
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <Rule strong />

      {/* The determination, or the abstention in its place. Never both. */}
      <section>
        {determination.abstained ? (
          <AbstentionNotice score={score} />
        ) : (
          <div className="space-y-10">
            <DeterminationBlock determination={determination} />
            {determination.time_to_decision_months === null ? null : (
              <MonthsStrip
                p10={determination.time_to_decision_months.p10}
                p50={determination.time_to_decision_months.p50}
                p90={determination.time_to_decision_months.p90}
                basis={determination.time_to_decision_months.basis}
              />
            )}
            {determination.probability_of_rule_change_before_decision === null ? null : (
              <div>
                <Label>chance the rules change before a decision</Label>
                <div className="mt-2 flex items-baseline gap-3">
                  <span
                    data-numeric
                    className="font-mono"
                    style={{ fontSize: "var(--text-heading-1)", color: "var(--text-primary)" }}
                  >
                    {Math.round(determination.probability_of_rule_change_before_decision * 100)}%
                  </span>
                  <span
                    className="max-w-lg"
                    style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
                  >
                    This is the retroactive kill: a moratorium or an overlay adopted while the application
                    is pending. It is modelled separately because it is the risk that gets priced least
                    often.
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <Rule />

      {/* Caption block. Two columns, mono values right aligned. */}
      <section>
        <Label>caption</Label>
        <div className="mt-4">
          <Caption
            entries={[
              { term: "jurisdiction", value: head.name },
              { term: "authority", value: head.role.replaceAll("_", " ") },
              {
                term: "by right",
                value:
                  score.site.by_right === null
                    ? "not established"
                    : score.site.by_right
                      ? "yes"
                      : "no",
              },
              {
                term: "site area",
                value: score.site.acres === null ? "not stated" : `${String(Math.round(score.site.acres))} acres`,
                numeric: score.site.acres !== null,
              },
              {
                term: "capacity",
                value:
                  score.site.capacity_mw === null
                    ? "not stated"
                    : `${String(Math.round(score.site.capacity_mw))} MW`,
                numeric: score.site.capacity_mw !== null,
              },
              {
                term: "discretion index",
                value: head.discretion_index === null ? "not computable" : head.discretion_index.toFixed(2),
                numeric: head.discretion_index !== null,
              },
              { term: "comparable decisions", value: head.data_depth, numeric: true },
              { term: "documents used", value: score.provenance.documents_used, numeric: true },
              { term: "model", value: `${score.provenance.model_kind} ${score.provenance.model_version}` },
              { term: "feature set", value: score.provenance.feature_set_version, numeric: true },
            ]}
          />
        </div>
      </section>

      {/* Drivers, with the evidence drawer one click from any row. */}
      {determination.abstained ? null : (
        <section>
          <Label>what moves the number</Label>
          <div className="mt-4">
            <DriversTable drivers={score.drivers} evidence={score.evidence} />
          </div>
        </section>
      )}

      {/* Precedents. The specific decisions the estimate rests on, so the reasoning can be audited. */}
      {score.precedents.length === 0 ? null : (
        <section>
          <Label>the decisions this rests on</Label>
          <table className="mt-4 w-full border-collapse">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
                {["case", "decided", "outcome", "vote", "months", "similarity"].map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="pb-2 text-left font-mono uppercase"
                    style={{
                      fontSize: "var(--text-micro)",
                      letterSpacing: "0.12em",
                      color: "var(--text-tertiary)",
                      fontWeight: 400,
                    }}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {score.precedents.map((precedent) => (
                <tr
                  key={precedent.application_id}
                  style={{
                    borderBottom: "1px solid var(--line-hairline)",
                    height: "var(--row-height)",
                  }}
                >
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono align-top"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {precedent.external_id ?? precedent.application_id}
                  </td>
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono align-top"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {precedent.decided_on ?? "not stated"}
                  </td>
                  <td className="py-3 pr-4 align-top" style={{ fontSize: "var(--text-small)" }}>
                    {precedent.outcome.replaceAll("_", " ")}
                  </td>
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono align-top"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {precedent.vote ?? "."}
                  </td>
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono align-top"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {precedent.months_to_decision === null
                      ? "."
                      : Math.round(precedent.months_to_decision)}
                  </td>
                  <td
                    data-numeric
                    className="py-3 font-mono align-top"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {precedent.similarity.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Alternatives. Where the customer saves the money, and the reason they renew. */}
      {score.alternatives.length === 0 ? null : (
        <section>
          <Label>where else this could go</Label>
          <div className="mt-4 space-y-3">
            {score.alternatives.map((alternative) => (
              <Panel key={alternative.jurisdiction_slug} className="flex items-baseline justify-between p-4">
                <div>
                  <Link
                    href={`/jurisdictions/${alternative.jurisdiction_slug}`}
                    className="rounded-sm"
                    style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
                  >
                    {alternative.jurisdiction}
                  </Link>
                  {alternative.note === null ? null : (
                    <div style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}>
                      {alternative.note}
                    </div>
                  )}
                </div>
                <div className="flex items-baseline gap-6">
                  <span
                    data-numeric
                    className="font-mono"
                    style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
                  >
                    {Math.round(alternative.distance_km)} km
                  </span>
                  <span
                    data-numeric
                    className="font-mono"
                    style={{ fontSize: "var(--text-heading-2)", color: "var(--text-primary)" }}
                  >
                    {alternative.abstained || alternative.approval_probability === null
                      ? "we do not know"
                      : `${String(Math.round(alternative.approval_probability * 100))}%`}
                  </span>
                </div>
              </Panel>
            ))}
          </div>
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
          >
            Ranked by probability less a relocation penalty of two points per hundred kilometres. That
            penalty is a placeholder, because only you know what moving actually costs. Substitute your own
            and the order may change.
          </p>
        </section>
      )}

      <Rule strong />

      {/* What the model does not know. Last, and the reason everything above is defensible. */}
      <section>
        <Label>what this does not know</Label>
        {score.provenance.pooling_note === null ? null : (
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
          >
            {score.provenance.pooling_note}
          </p>
        )}
        {score.provenance.features_missing.length === 0 ? (
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
          >
            Every feature the model uses could be computed for this site.
          </p>
        ) : (
          <>
            <p
              className="mt-3 max-w-2xl"
              style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
            >
              {score.provenance.features_missing.length} of the features we would like to have are not known
              for this site: {score.provenance.features_missing.join(", ").replaceAll("_", " ")}.
            </p>
            <p
              className="mt-3 max-w-2xl"
              style={{ fontSize: "var(--text-small)", color: "var(--text-tertiary)" }}
            >
              These are recorded as unknown rather than filled with a default. Where the model needed them,
              the uncertainty of not having them is carried into the interval, which is part of why the
              interval is as wide as it is.
            </p>
          </>
        )}
        <p
          className="mt-6 max-w-2xl"
          style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
        >
          {score.provenance.disclaimer}
        </p>
      </section>
    </article>
  );
}
