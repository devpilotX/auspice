import Link from "next/link";

import { Label, Rule, StatusDot, Unavailable } from "@/components/primitives";
import { api } from "@/lib/api";

export const metadata = {
  title: "Coverage",
  description:
    "The twelve counties we cover, how deep our record is in each, and how stale our data is.",
};

const FRESHNESS_LABEL = {
  fresh: "within its refresh window",
  stale: "past its refresh window",
  broken: "well past its refresh window",
  never: "never fetched",
} as const;

function freshnessState(value: "fresh" | "stale" | "broken" | "never"): "fresh" | "stale" | "broken" {
  return value === "never" ? "broken" : value;
}

export default async function JurisdictionsPage() {
  const jurisdictions = await api.jurisdictions();

  if (jurisdictions === null) {
    return <Unavailable what="We cannot reach our own API, so this page has nothing honest to show." />;
  }

  return (
    <div className="space-y-12">
      <section>
        <Label>coverage</Label>
        <h1
          className="mt-3 max-w-3xl"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "var(--text-display-2)",
            lineHeight: 1.15,
            letterSpacing: "-0.02em",
            color: "var(--text-primary)",
          }}
        >
          Twelve counties, covered properly.
        </h1>
        <p
          className="mt-5 max-w-2xl"
          style={{ fontSize: "1.0625rem", lineHeight: 1.6, color: "var(--text-secondary)" }}
        >
          Anywhere outside this list, we abstain. A shallow answer for three thousand counties is a demo
          that dies in the first customer meeting, and the honest version of national coverage is telling
          you where we do not have it.
        </p>
        <p
          className="mt-4 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          The depth column is the number of decisions whose outcome is backed by a quote we found in the
          source document. It is not the number of documents we hold, and it is deliberately the harsher
          of the two figures.
        </p>
      </section>

      <Rule strong />

      <table className="w-full border-collapse">
        <caption className="sr-only">
          Counties covered, with legal framework, decision depth, and data freshness.
        </caption>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
            {["county", "state", "framework", "platform", "depth", "discretion", "freshness"].map(
              (heading) => (
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
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {jurisdictions.map((j) => (
            <tr
              key={j.slug}
              style={{ borderBottom: "1px solid var(--line-hairline)", height: "var(--row-height)" }}
            >
              <td className="py-3 pr-4">
                <Link
                  href={`/jurisdictions/${j.slug}`}
                  className="rounded-sm"
                  style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
                >
                  {j.name}
                </Link>
              </td>
              <td
                className="py-3 pr-4 font-mono"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                {j.region ?? "."}
              </td>
              <td className="py-3 pr-4" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
                {j.legal_framework === "dillons_rule"
                  ? "Dillon's Rule"
                  : j.legal_framework === "home_rule"
                    ? "home rule"
                    : (j.legal_framework ?? "not recorded")}
              </td>
              <td
                className="py-3 pr-4 font-mono"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                {j.civic_platform === "unknown" ? "not identified" : (j.civic_platform ?? ".")}
              </td>
              <td
                data-numeric
                className="py-3 pr-4 font-mono"
                style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}
              >
                {j.data_depth}
              </td>
              <td
                data-numeric
                className="py-3 pr-4 font-mono"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                {j.discretion_index === null ? "not computable" : j.discretion_index.toFixed(2)}
              </td>
              <td className="py-3">
                <StatusDot state={freshnessState(j.freshness)} label={FRESHNESS_LABEL[j.freshness]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="max-w-2xl" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
        A discretion index of &ldquo;not computable&rdquo; means we hold no decisions for that county yet, so
        we cannot say what share of its decisions turn on relief it may lawfully refuse. It does not mean
        zero. Zero would mean everything there is permitted as of right, which is a strong claim to make
        out of ignorance.
      </p>
    </div>
  );
}
