import Link from "next/link";

import { Label, Panel, Rule } from "@/components/primitives";
import { api } from "@/lib/api";

export const metadata = {
  title: "A rating bureau for the right to build",
};

export default async function Home() {
  const [accuracy, jurisdictions] = await Promise.all([api.accuracy(), api.jurisdictions()]);

  const covered = jurisdictions?.length ?? 0;
  const withDepth = jurisdictions?.filter((j) => j.data_depth > 0).length ?? 0;

  return (
    <div className="space-y-20">
      <section>
        <h1
          className="max-w-3xl"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "var(--text-display-1)",
            lineHeight: 1.15,
            letterSpacing: "-0.02em",
            color: "var(--text-primary)",
          }}
        >
          The odds that you will actually be allowed to build.
        </h1>

        <p
          className="mt-6 max-w-2xl"
          style={{ fontSize: "1.0625rem", lineHeight: 1.6, color: "var(--text-secondary)" }}
        >
          Capital markets price construction risk, technology risk and demand risk. They do not price
          permission risk, and permission is the largest single cause of project failure. We produce a
          calibrated probability and a time distribution for a specific project at a specific location,
          and we publish our own accuracy record so the number can be used by a credit committee.
        </p>

        <p
          className="mt-4 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          The industry has plenty of data vendors. It does not have a rating agency.
        </p>

        <div className="mt-8 flex flex-wrap gap-4">
          <Link
            href="/accuracy"
            className="rounded-sm px-4 py-2"
            style={{
              border: "1px solid var(--line-strong)",
              fontSize: "var(--text-small)",
              color: "var(--text-primary)",
            }}
          >
            Read our accuracy record
          </Link>
          <Link
            href="/jurisdictions"
            className="rounded-sm px-4 py-2"
            style={{ fontSize: "var(--text-small)", color: "var(--text-accent)" }}
          >
            See what we cover
          </Link>
        </div>
      </section>

      <Rule strong />

      <section>
        <Label>where we are</Label>
        <div className="mt-6 grid gap-8 sm:grid-cols-3">
          {[
            {
              figure: covered === 0 ? "not available" : String(covered),
              caption: "counties in the registry, hand built with sourced boundaries and election calendars",
            },
            {
              figure: withDepth === 0 ? "0" : String(withDepth),
              caption:
                "of those hold at least one decision whose outcome is backed by a quote we verified against its source",
            },
            {
              figure: accuracy === null ? "not available" : String(accuracy.published),
              caption:
                "predictions published to the hash committed ledger. Nothing is backdated, by us or by anyone",
            },
          ].map((item) => (
            <div key={item.caption}>
              <div
                data-numeric
                className="font-mono"
                style={{
                  fontSize: "var(--text-display-2)",
                  color: "var(--text-primary)",
                  letterSpacing: "-0.02em",
                }}
              >
                {item.figure}
              </div>
              <p
                className="mt-2"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                {item.caption}
              </p>
            </div>
          ))}
        </div>
      </section>

      <Panel className="p-8">
        <Label>how this is built</Label>
        <div className="mt-6 grid gap-8 md:grid-cols-2">
          {[
            {
              heading: "No language model produces the number",
              body: "Language models read documents and write sentences. The probability comes from a statistical model that can be back tested and calibrated. That distinction is the only reason an accuracy record can be published at all.",
            },
            {
              heading: "Every fact carries a quote we checked",
              body: "A quote that is not found verbatim in its source document is discarded, not flagged. Hallucinated citations are eliminated by mechanism rather than by trust, and an unverified row does not influence any number.",
            },
            {
              heading: "The system is allowed to refuse",
              body: "When the record is too thin, we say we do not know and show you what we do know. A system that always answers is trusted exactly once.",
            },
            {
              heading: "The uncertainty carries the weight",
              body: "Every probability comes with an interval, and the interval is what the page emphasises. Probability is never coloured here, because a green 82 percent reads as advice and this is not advice.",
            },
          ].map((item) => (
            <div key={item.heading}>
              <h2
                style={{
                  fontSize: "var(--text-heading-2)",
                  color: "var(--text-primary)",
                  fontWeight: 500,
                }}
              >
                {item.heading}
              </h2>
              <p
                className="mt-2"
                style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
              >
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
