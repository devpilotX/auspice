import { notFound } from "next/navigation";

import { Caption, Label, Panel, Rule, StatusDot, Unavailable } from "@/components/primitives";
import { api } from "@/lib/api";

/*
  The public jurisdiction profile. Section 10.4: "[County] data centre approval rate" is exactly what a
  developer searches, and a free indexed profile captures that intent.

  These pages are static where possible and revalidate on the same sixty second window as the rest of the
  public surface.
*/

export async function generateStaticParams() {
  const jurisdictions = await api.jurisdictions();
  return (jurisdictions ?? []).map((j) => ({ slug: j.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const profile = await api.jurisdiction(slug);
  if (profile === null) return { title: "Jurisdiction" };
  return {
    title: `${profile.summary.name} permission risk`,
    description:
      `Decision record, rules in force, board composition and election calendar for ` +
      `${profile.summary.name}${profile.summary.region === null ? "" : `, ${profile.summary.region}`}.`,
  };
}

function orAbsent(value: string | number | null): string {
  return value === null ? "not recorded" : String(value);
}

export default async function JurisdictionProfilePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const profile = await api.jurisdiction(slug);

  if (profile === null) {
    const list = await api.jurisdictions();
    if (list === null) {
      return <Unavailable what="We cannot reach our own API." />;
    }
    notFound();
  }

  const { summary } = profile;
  const rates = Object.entries(profile.approval_rate_by_use_class);

  return (
    <div className="space-y-14">
      <section>
        <Label>{summary.region ?? "jurisdiction"}</Label>
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
          {summary.name}
        </h1>
        <div className="mt-6 max-w-2xl">
          <Caption
            entries={[
              {
                term: "legal framework",
                value:
                  summary.legal_framework === "dillons_rule"
                    ? "Dillon's Rule"
                    : summary.legal_framework === "home_rule"
                      ? "home rule"
                      : (summary.legal_framework ?? "not recorded"),
              },
              { term: "decision bodies", value: summary.bodies, numeric: true },
              {
                term: "decisions we hold",
                value: summary.data_depth,
                numeric: true,
              },
              {
                term: "discretion index",
                value: summary.discretion_index === null ? "not computable" : summary.discretion_index.toFixed(2),
                numeric: true,
              },
              {
                term: "election dates known",
                value: summary.elections_known,
                numeric: true,
              },
              {
                term: "boundary geometry",
                value: summary.has_boundary ? "loaded from the Census" : "not loaded",
              },
            ]}
          />
        </div>
        <div className="mt-4">
          <StatusDot
            state={summary.freshness === "never" ? "broken" : summary.freshness}
            label={
              summary.hours_since_refresh === null
                ? "no source has been fetched yet"
                : `freshest source is ${String(Math.round(summary.hours_since_refresh))} hours old`
            }
          />
        </div>
      </section>

      <Rule strong />

      <section>
        <Label>approval rate on our record</Label>
        {rates.length === 0 ? (
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
          >
            We hold no decisions for this county whose outcome is backed by a verified quote, so there is
            no approval rate to report. Anything we published here would be a rate for a different county
            wearing this one&rsquo;s name.
          </p>
        ) : (
          <div className="mt-4 max-w-xl">
            <Caption
              entries={rates.map(([useClass, rate]) => ({
                term: useClass.replaceAll("_", " "),
                value: rate === null ? "no decided cases" : `${String(Math.round(rate * 100))}%`,
                numeric: rate !== null,
              }))}
            />
          </div>
        )}
      </section>

      <section>
        <Label>who decides</Label>
        <div className="mt-4 space-y-4">
          {profile.bodies.length === 0 ? (
            <p style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}>
              No decision body is recorded, which is a gap in our registry rather than a fact about the
              county.
            </p>
          ) : (
            profile.bodies.map((body) => (
              <Panel key={body.name} className="p-5">
                <div style={{ fontSize: "var(--text-heading-2)", color: "var(--text-primary)" }}>
                  {body.name}
                </div>
                <div className="mt-3 max-w-lg">
                  <Caption
                    entries={[
                      { term: "seats", value: orAbsent(body.seats), numeric: true },
                      { term: "quorum", value: orAbsent(body.quorum), numeric: true },
                      {
                        term: "threshold",
                        value: orAbsent(body.vote_threshold).replaceAll("_", " "),
                      },
                      {
                        term: "role",
                        value:
                          body.recommendation_is_binding === true
                            ? "recommends to the body above it"
                            : "decides",
                      },
                    ]}
                  />
                </div>
              </Panel>
            ))
          )}
        </div>
      </section>

      <section>
        <Label>rules in force, and when they changed</Label>
        {profile.instruments.length === 0 ? (
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
          >
            We have not read this county&rsquo;s ordinance history yet. That is not the same as the rules
            never having changed, and any score here treats the rule change features as unknown rather
            than as safe.
          </p>
        ) : (
          <table className="mt-4 w-full border-collapse">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
                {["kind", "citation", "adopted", "expires", "restrictions"].map((heading) => (
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
              {profile.instruments.map((instrument) => (
                <tr
                  key={`${instrument.kind}-${instrument.adopted_on ?? "undated"}-${instrument.citation ?? "uncited"}`}
                  style={{
                    borderBottom: "1px solid var(--line-hairline)",
                    height: "var(--row-height)",
                  }}
                >
                  <td className="py-3 pr-4" style={{ fontSize: "var(--text-small)" }}>
                    {instrument.kind.replaceAll("_", " ")}
                  </td>
                  <td
                    className="py-3 pr-4 font-mono"
                    style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
                  >
                    {orAbsent(instrument.citation)}
                  </td>
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {orAbsent(instrument.adopted_on)}
                  </td>
                  <td
                    data-numeric
                    className="py-3 pr-4 font-mono"
                    style={{ fontSize: "var(--text-small)" }}
                  >
                    {instrument.expires_on ?? "no expiry"}
                  </td>
                  <td
                    className="py-3 font-mono"
                    style={{ fontSize: "var(--text-tiny)", color: "var(--text-secondary)" }}
                  >
                    {JSON.stringify(instrument.restrictions)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <Label>next elections</Label>
        {profile.next_elections.length === 0 ? (
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
          >
            No upcoming election is recorded for this county&rsquo;s bodies.
          </p>
        ) : (
          <div className="mt-4 max-w-xl">
            <Caption
              entries={profile.next_elections.map((election) => ({
                term: election.body,
                value: `${election.election_date}, ${orAbsent(election.seats_contested)} seats`,
                numeric: true,
              }))}
            />
          </div>
        )}
        <p
          className="mt-4 max-w-2xl"
          style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
        >
          Election dates are derived from each body&rsquo;s term length and cycle rather than copied from a
          list, so they cannot silently go stale. Approvals of contested uses fall near elections, which is
          why this section is on the page at all.
        </p>
      </section>
    </div>
  );
}
