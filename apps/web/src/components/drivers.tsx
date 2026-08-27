"use client";

/**
 * The drivers table and the evidence drawer.
 *
 * Section 16.3 names the evidence drawer open rate as the best single proxy for trust, because
 * customers who check the evidence are the ones who renew. So opening it is one click from any row, and
 * the row is the trigger rather than a small icon at the end of it.
 *
 * The drawer is the only place in the product with an animation besides the determination number: it
 * slides at 180ms. Everything else is instant.
 *
 * Base UI provides the dialog primitive. Keyboard handling, focus trapping and the escape key come from
 * it rather than from anything written here, because those are exactly the things a hand rolled drawer
 * gets subtly wrong and an audit finds.
 */

import { Dialog } from "@base-ui-components/react/dialog";
import { useState } from "react";

import type { Driver, Evidence } from "@/lib/api";
import { Label, Quotation, Rule } from "@/components/primitives";

function DirectionBar({ direction, weight }: { direction: Driver["direction"]; weight: number }) {
  const width = Math.max(weight * 100, 2);
  return (
    <div className="flex items-center gap-2" style={{ width: 140 }}>
      {/* The bar grows from the centre: left for negative, right for positive. A single left anchored
          bar would make a strong negative driver look like a weak positive one at a glance. */}
      <div className="relative h-2 w-full" style={{ backgroundColor: "var(--bg-inset)" }}>
        <div
          className="absolute top-0 h-2"
          style={{
            backgroundColor: "var(--text-primary)",
            width: `${String(width / 2)}%`,
            left: direction === "negative" ? `${String(50 - width / 2)}%` : "50%",
          }}
        />
        <div
          aria-hidden
          className="absolute top-0 h-2"
          style={{ left: "50%", width: 1, backgroundColor: "var(--line-strong)" }}
        />
      </div>
      <span className="sr-only">
        {direction === "negative" ? "reduces" : "increases"} the probability
      </span>
    </div>
  );
}

export function DriversTable({
  drivers,
  evidence,
}: {
  drivers: Driver[];
  evidence: Evidence[];
}) {
  const [open, setOpen] = useState<Evidence | null>(null);
  const byId = new Map(evidence.map((item) => [item.evidence_id, item]));

  if (drivers.length === 0) {
    return (
      <p style={{ fontSize: "var(--text-body)", color: "var(--text-secondary)" }}>
        No driver carries enough weight to report. That happens when the estimate rests almost entirely
        on the jurisdiction&rsquo;s base rate rather than on anything specific to this site.
      </p>
    );
  }

  return (
    <>
      <table className="w-full border-collapse">
        <caption className="sr-only">
          Factors moving the probability, with their direction, weight and source.
        </caption>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--line-strong)" }}>
            {["factor", "direction", "weight", "evidence"].map((heading) => (
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
          {drivers.map((driver) => {
            const source = driver.evidence_id === null ? null : byId.get(driver.evidence_id) ?? null;
            return (
              <tr
                key={driver.factor}
                data-keep-together
                style={{
                  borderBottom: "1px solid var(--line-hairline)",
                  height: "var(--row-height)",
                }}
              >
                <td className="py-3 pr-4 align-top">
                  <div style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}>
                    {driver.plain_language}
                  </div>
                  <div
                    className="mt-1 font-mono"
                    style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
                  >
                    {driver.factor} &middot; {driver.group}
                  </div>
                </td>
                <td className="py-3 pr-4 align-top">
                  <DirectionBar direction={driver.direction} weight={driver.weight} />
                </td>
                <td className="py-3 pr-4 align-top">
                  <span
                    data-numeric
                    className="font-mono"
                    style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}
                  >
                    {driver.weight.toFixed(2)}
                  </span>
                </td>
                <td className="py-3 align-top">
                  {source === null ? (
                    <span style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}>
                      registry data, no quotable document
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(source);
                      }}
                      className="rounded-sm underline decoration-1 underline-offset-2"
                      style={{ fontSize: "var(--text-small)", color: "var(--text-accent)" }}
                    >
                      read the source
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <EvidenceDrawer
        evidence={open}
        onClose={() => {
          setOpen(null);
        }}
      />
    </>
  );
}

export function EvidenceDrawer({
  evidence,
  onClose,
}: {
  evidence: Evidence | null;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={evidence !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop
          className="fixed inset-0"
          style={{ backgroundColor: "var(--text-primary)", opacity: 0.12 }}
        />
        <Dialog.Popup
          className="fixed top-0 right-0 bottom-0 w-full max-w-lg overflow-y-auto p-8"
          style={{
            backgroundColor: "var(--bg-raised)",
            borderLeft: "1px solid var(--line-strong)",
            transitionProperty: "transform",
            transitionDuration: "var(--duration-drawer)",
            transitionTimingFunction: "var(--ease-drawer)",
          }}
        >
          {evidence === null ? null : (
            <>
              <div className="flex items-start justify-between gap-4">
                <Dialog.Title
                  style={{
                    fontFamily: "var(--font-serif)",
                    fontSize: "var(--text-heading-2)",
                    color: "var(--text-primary)",
                  }}
                >
                  The source
                </Dialog.Title>
                <Dialog.Close
                  className="rounded-sm px-2 py-1 font-mono uppercase"
                  style={{
                    fontSize: "var(--text-micro)",
                    letterSpacing: "0.12em",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--line-hairline)",
                  }}
                >
                  close
                </Dialog.Close>
              </div>

              <div className="mt-6">
                <Quotation>{evidence.quote}</Quotation>
              </div>

              <div className="mt-8">
                <Rule />
                <dl className="mt-4 space-y-3">
                  {[
                    { term: "document", value: evidence.document_title ?? evidence.source_url },
                    { term: "kind", value: evidence.document_kind ?? "not classified" },
                    { term: "page", value: evidence.page === null ? "not paginated" : String(evidence.page) },
                    { term: "retrieved", value: evidence.retrieved_on ?? "date not recorded" },
                    ...(evidence.speaker === null ? [] : [{ term: "speaker", value: evidence.speaker }]),
                    ...(evidence.timestamp === null
                      ? []
                      : [{ term: "position in hearing", value: evidence.timestamp }]),
                  ].map((entry) => (
                    <div key={entry.term} className="flex items-baseline justify-between gap-4">
                      <dt style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
                        {entry.term}
                      </dt>
                      <dd
                        className="text-right font-mono"
                        style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}
                      >
                        {entry.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>

              <div className="mt-8">
                <Label>verification</Label>
                <p
                  className="mt-2"
                  style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}
                >
                  This quote was found in the stored source document, character for character. Quotes
                  that do not match their source are discarded before they reach a score, so nothing on
                  this page is a paraphrase.
                </p>
                <a
                  href={evidence.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-4 inline-block rounded-sm underline decoration-1 underline-offset-2"
                  style={{ fontSize: "var(--text-small)", color: "var(--text-accent)" }}
                >
                  Open the original document
                </a>
              </div>
            </>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
