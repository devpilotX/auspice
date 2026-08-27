import dynamic from "next/dynamic";

import { Caption, Label, Panel, Rule, StatusDot, Unavailable } from "@/components/primitives";
import { api } from "@/lib/api";

/*
  visx is loaded on demand rather than in the initial bundle.

  The reliability curve only renders once twenty predictions have resolved, which is not yet. Shipping a
  charting library to every visitor so that it can sit unused is the exact kind of quiet weight that
  makes a performance budget rot. Section 7.3 puts public pages under 100 KB of JavaScript, and this is
  the difference between meeting that and not.
*/
const ReliabilityCurve = dynamic(
  () => import("@/components/reliability-curve").then((m) => m.ReliabilityCurve),
  {
    loading: () => (
      <p style={{ fontSize: "var(--text-small)", color: "var(--text-tertiary)" }}>
        Drawing the curve.
      </p>
    ),
  },
);

export const metadata = {
  title: "Accuracy",
  description:
    "Every prediction we have published, every one that has resolved, and every one we got wrong.",
};

/*
  The public accuracy page. Section 5.7 builds this first among the screens despite generating zero
  revenue, because it is the only screen a competitor cannot replicate.

  The hardest thing about this page is what it says before there is anything to say. A bureau with no
  resolved predictions has no accuracy, and the temptation is to show a number from back testing instead.
  This page refuses to. Back testing is on the method page, clearly labelled as back testing. What
  appears here is the prospective record and nothing else, because that is the only thing that proves
  forecasting skill.
*/

export default async function AccuracyPage() {
  const accuracy = await api.accuracy();

  if (accuracy === null) {
    return (
      <Unavailable
        what="We cannot reach our own API, so we are not going to show you numbers from a cache."
        hint="If you are running this locally, start the service with: uv run uvicorn app.main:app --app-dir apps/api"
      />
    );
  }

  const chainState = accuracy.chain.ok ? "fresh" : "broken";

  return (
    <div className="space-y-16">
      <section>
        <Label>the record</Label>
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
          Every call we have made, including the ones we got wrong.
        </h1>
        <p
          className="mt-5 max-w-2xl"
          style={{ fontSize: "1.0625rem", lineHeight: 1.6, color: "var(--text-secondary)" }}
        >
          {accuracy.statement}
        </p>
        <p
          className="mt-4 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          Every prediction is hashed and chained to the one before it before any outcome exists, so
          nothing here can be quietly revised or removed. You do not have to take our word for that
          either: the whole ledger is downloadable and each line can be verified independently.
        </p>
      </section>

      <Rule strong />

      <section>
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "published", value: accuracy.published },
            { label: "resolved", value: accuracy.resolved },
            { label: "still pending", value: accuracy.pending },
            { label: "abstained", value: accuracy.abstained },
          ].map((item) => (
            <div key={item.label}>
              <Label>{item.label}</Label>
              <div
                data-numeric
                className="mt-2 font-mono"
                style={{
                  fontSize: "var(--text-display-2)",
                  color: "var(--text-primary)",
                  letterSpacing: "-0.02em",
                }}
              >
                {item.value}
              </div>
            </div>
          ))}
        </div>
      </section>

      <Panel className="p-8">
        <Label>brier score</Label>
        {accuracy.brier_score === null ? (
          <>
            <p
              className="mt-3 max-w-2xl"
              style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
            >
              There is no Brier score yet. It appears here the day the first prediction resolves, and not
              a day before.
            </p>
            <p
              className="mt-3 max-w-2xl"
              style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
            >
              We could put a back tested figure in this space. Plenty of companies would. A back test
              measures how well a model fits history it was built on, which is a different claim from how
              well it predicts what has not happened, and only the second one is worth anything to you.
              The back test is on the method page and it is labelled as one.
            </p>
          </>
        ) : (
          <div className="mt-3 flex items-baseline gap-4">
            <span
              data-numeric
              className="font-mono"
              style={{
                fontSize: "var(--text-display-1)",
                color: "var(--text-primary)",
                letterSpacing: "-0.03em",
              }}
            >
              {accuracy.brier_score.toFixed(4)}
            </span>
            <span style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
              over {accuracy.answered} resolved predictions. Lower is better. Zero is perfect.
            </span>
          </div>
        )}
      </Panel>

      <section>
        <Label>reliability curve</Label>
        <p
          className="mt-3 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          The claim is simple: when we say 70 percent, it should happen about 70 percent of the time. This
          is where you check that.
        </p>
        <div className="mt-6">
          {accuracy.answered < 20 ? (
            <Panel className="p-8">
              <p style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}>
                {accuracy.answered === 0
                  ? "Nothing has resolved, so there is no curve to draw."
                  : `Only ${String(accuracy.answered)} predictions have resolved. A reliability curve on that many points would be noise wearing a shape, so it is not drawn.`}
              </p>
              <p
                className="mt-3"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                The curve appears at twenty resolved predictions, which is the point where the bins start
                carrying more signal than sampling noise.
              </p>
            </Panel>
          ) : (
            <ReliabilityCurve bins={[]} totalObservations={accuracy.answered} />
          )}
        </div>
      </section>

      <Rule />

      <section>
        <Label>the ledger</Label>
        <div className="mt-4 max-w-xl">
          <Caption
            entries={[
              { term: "entries", value: accuracy.chain.entries, numeric: true },
              {
                term: "chain verifies",
                value: <StatusDot state={chainState} label={accuracy.chain.ok ? "intact" : "broken"} />,
              },
              {
                term: "head",
                value: accuracy.chain.head === null ? "empty" : `${accuracy.chain.head.slice(0, 16)}...`,
                numeric: true,
              },
            ]}
          />
        </div>
        {accuracy.chain.ok ? null : (
          <p
            className="mt-4 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
          >
            The chain does not verify at sequence {accuracy.chain.broken_at}. That means an entry was
            edited or removed, and until it is explained you should not trust anything on this page.
            {accuracy.chain.reason === null ? "" : ` ${accuracy.chain.reason}.`}
          </p>
        )}
        <a
          href="/api/ledger"
          className="mt-6 inline-block rounded-sm underline decoration-1 underline-offset-2"
          style={{ fontSize: "var(--text-small)", color: "var(--text-accent)" }}
        >
          Download the full ledger
        </a>
      </section>

      <Rule />

      <section>
        <Label>misses</Label>
        <p
          className="mt-3 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          Wrong calls are published with a written explanation of what the model missed. Nobody who is
          hiding results volunteers their failures, which is exactly why this section exists.
        </p>
        <div className="mt-6">
          {accuracy.misses.length === 0 ? (
            <p style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}>
              {accuracy.resolved === 0
                ? "No prediction has resolved yet, so there is nothing to report either way."
                : "No call has gone the wrong way yet. On this sample size that is not evidence of anything, and this line will change."}
            </p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
                  {["seq", "jurisdiction", "we said", "what happened", "what we missed"].map((heading) => (
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
                {accuracy.misses.map((miss) => (
                  <tr
                    key={miss.seq}
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
                      {miss.seq}
                    </td>
                    <td className="py-3 pr-4 align-top" style={{ fontSize: "var(--text-small)" }}>
                      {miss.jurisdiction ?? "not recorded"}
                    </td>
                    <td
                      data-numeric
                      className="py-3 pr-4 font-mono align-top"
                      style={{ fontSize: "var(--text-small)" }}
                    >
                      {miss.predicted === null ? "abstained" : `${String(Math.round(miss.predicted * 100))}%`}
                    </td>
                    <td className="py-3 pr-4 align-top" style={{ fontSize: "var(--text-small)" }}>
                      {miss.outcome ?? "unresolved"}
                    </td>
                    <td
                      className="py-3 align-top"
                      style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
                    >
                      {miss.note ?? "No note written yet. One is owed."}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
