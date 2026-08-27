/**
 * The abstention notice.
 *
 * Bordered, plain, unapologetic. It states the three conditions and says we would rather show nothing
 * than a number we cannot stand behind.
 *
 * Two things it does not do. It does not show a greyed out number, because a greyed number is still a
 * number and it gets read. And it does not apologise, because refusing to answer is the product working
 * rather than the product failing.
 */

import type { Score } from "@/lib/api";
import { Label, Panel, Rule } from "@/components/primitives";

const REASON_TEXT: Record<string, string> = {
  thin_local_record: "Fewer than three comparable decisions on record in this jurisdiction.",
  dominated_by_pooling:
    "More than 80 percent of any estimate would be borrowed from other jurisdictions.",
  interval_too_wide: "The 80 percent interval would be wider than 0.35, which carries no information.",
  stale_jurisdiction_data:
    "Our data for this jurisdiction is more than 90 days old, so the rules a score assumed may no longer exist.",
  unresolved_jurisdiction_chain:
    "We cannot establish which body decides for this parcel, so there is nothing to score.",
};

export function AbstentionNotice({ score }: { score: Score }) {
  const { determination, provenance, site } = score;
  const head = site.jurisdiction_chain[0];

  return (
    <Panel className="p-8">
      <Label>determination</Label>

      <h2
        className="mt-3"
        style={{
          fontFamily: "var(--font-serif)",
          fontSize: "var(--text-display-3)",
          lineHeight: 1.2,
          color: "var(--text-primary)",
        }}
      >
        We do not know.
      </h2>

      <p
        className="mt-4 max-w-2xl"
        style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
      >
        We are not going to give you a probability for this site. The evidence is too thin to support
        one, and a number produced from evidence this thin would look exactly like a number produced
        from good evidence. We would rather show you nothing than a number we cannot stand behind.
      </p>

      <div className="mt-6">
        <Rule />
      </div>

      <div className="mt-6">
        <Label>why</Label>
        <ul className="mt-3 space-y-2">
          {determination.abstention_reasons.map((reason) => (
            <li
              key={reason}
              className="flex gap-3"
              style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}
            >
              <span aria-hidden style={{ color: "var(--text-accent)" }}>
                &bull;
              </span>
              <span>{REASON_TEXT[reason] ?? reason}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-8">
        <Label>what we do know</Label>
        <p
          className="mt-3 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          {head === undefined
            ? "Nothing, because the jurisdiction did not resolve."
            : `${head.name} holds ${String(head.data_depth)} comparable decisions in our record. ` +
              `${provenance.jurisdiction_data_depth}. ` +
              (provenance.staleness_days === null
                ? "No source for this jurisdiction has been fetched yet."
                : `The freshest source is ${String(provenance.staleness_days)} days old.`)}
        </p>
        <p
          className="mt-3 max-w-2xl"
          style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
        >
          The rules in force, the composition of the deciding body and the recent decision history are
          all below, and they are worth reading. They are facts. What we will not do is turn them into a
          probability that implies more than they support.
        </p>
      </div>

      {determination.time_to_decision_months === null ? null : (
        <div className="mt-8">
          <Label>timing, which we can speak to</Label>
          <p
            className="mt-3 max-w-2xl"
            style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}
          >
            Half of comparable applications reach a decision within{" "}
            <span data-numeric className="font-mono">
              {Math.round(determination.time_to_decision_months.p50)}
            </span>{" "}
            months, and nine in ten within{" "}
            <span data-numeric className="font-mono">
              {Math.round(determination.time_to_decision_months.p90)}
            </span>
            . Duration is better identified than outcome here, because a pending application still tells
            us how long it has been waiting.
          </p>
        </div>
      )}
    </Panel>
  );
}
