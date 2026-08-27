/**
 * The primitives. Every visual decision in the design system lives in one of these, so a screen is
 * assembled rather than styled.
 *
 * Nothing here takes a colour prop. If a component needs a different colour, the answer is a token,
 * not a prop.
 */

import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/* ---------------------------------------------------------------------------
   Structure
   --------------------------------------------------------------------------- */

/** A hairline. The only separation device in the product. */
export function Rule({ className, strong = false }: { className?: string; strong?: boolean }) {
  return (
    <div
      role="separator"
      className={cn("h-px w-full", className)}
      style={{ backgroundColor: strong ? "var(--line-strong)" : "var(--line-hairline)" }}
    />
  );
}

/** A framed region. Outer frame in the stronger rule, no shadow, 2px radius. */
export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "aside";
}) {
  return (
    <Tag
      className={cn("rounded-sm", className)}
      style={{
        backgroundColor: "var(--bg-raised)",
        border: "1px solid var(--line-strong)",
      }}
    >
      {children}
    </Tag>
  );
}

/** A section label. Mono, uppercase, 0.12em tracking, tertiary ink. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn("font-mono uppercase", className)}
      style={{
        fontSize: "var(--text-micro)",
        letterSpacing: "0.12em",
        color: "var(--text-tertiary)",
      }}
    >
      {children}
    </div>
  );
}

/** A number. Mono, tabular figures, so columns align when printed. */
export function Numeric({
  children,
  className,
  size = "body",
}: {
  children: ReactNode;
  className?: string;
  size?: "body" | "small" | "tiny" | "determination";
}) {
  const sizes = {
    body: "var(--text-body)",
    small: "var(--text-small)",
    tiny: "var(--text-tiny)",
    determination: "var(--text-determination)",
  } as const;
  return (
    <span
      data-numeric
      className={cn("font-mono", className)}
      style={{
        fontSize: sizes[size],
        // Probability is never coloured, so a number always inherits primary ink. There is no prop
        // to change that, which is the point.
        color: "var(--text-primary)",
        letterSpacing: size === "determination" ? "-0.03em" : undefined,
        lineHeight: size === "determination" ? 1 : undefined,
      }}
    >
      {children}
    </span>
  );
}

/** A quotation from a source. Newsreader, with a brass left rule. Used nowhere else. */
export function Quotation({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <blockquote
      className={cn("pl-4", className)}
      style={{
        borderLeft: "2px solid var(--color-brass)",
        fontFamily: "var(--font-serif)",
        fontSize: "0.9375rem",
        lineHeight: 1.55,
        color: "var(--text-primary)",
      }}
    >
      {children}
    </blockquote>
  );
}

/** A brass tag. Low emphasis, used for a confidence level or a status word. */
export function Tag({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono uppercase"
      style={{
        fontSize: "var(--text-micro)",
        letterSpacing: "0.12em",
        backgroundColor: "var(--bg-tag)",
        color: "var(--text-accent)",
        border: "1px solid var(--line-hairline)",
      }}
    >
      {children}
    </span>
  );
}

/**
 * A 7px status dot. The only place a status colour appears, and it never carries judgement about an
 * outcome, only about the state of our own data.
 */
export function StatusDot({
  state,
  label,
}: {
  state: "fresh" | "stale" | "broken";
  label: string;
}) {
  const colours = {
    fresh: "var(--color-state-fresh)",
    stale: "var(--color-state-stale)",
    broken: "var(--color-state-broken)",
  } as const;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className="inline-block rounded-full"
        style={{ width: 7, height: 7, backgroundColor: colours[state] }}
      />
      <span style={{ fontSize: "var(--text-tiny)", color: "var(--text-secondary)" }}>{label}</span>
      <span className="sr-only">{state}</span>
    </span>
  );
}

/* ---------------------------------------------------------------------------
   The caption block. Section 5.6 rendered as a legal caption: a two column
   definition list, mono values right aligned.
   --------------------------------------------------------------------------- */
export function Caption({
  entries,
}: {
  entries: { term: string; value: ReactNode; numeric?: boolean }[];
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-8 sm:grid-cols-2">
      {entries.map((entry) => (
        <div
          key={entry.term}
          className="flex items-baseline justify-between gap-4 py-2"
          style={{ borderBottom: "1px solid var(--line-hairline)" }}
        >
          <dt style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
            {entry.term}
          </dt>
          <dd
            {...(entry.numeric ? { "data-numeric": true } : {})}
            className={entry.numeric ? "font-mono" : undefined}
            style={{
              fontSize: "var(--text-small)",
              color: "var(--text-primary)",
              textAlign: "right",
            }}
          >
            {entry.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/* ---------------------------------------------------------------------------
   Empty and unavailable states. Both say what is true rather than showing a
   spinner that never resolves.
   --------------------------------------------------------------------------- */
export function Unavailable({ what, hint }: { what: string; hint?: string }) {
  return (
    <Panel className="p-6">
      <Label>unavailable</Label>
      <p className="mt-2" style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}>
        {what}
      </p>
      {hint ? (
        <p className="mt-2" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
          {hint}
        </p>
      ) : null}
    </Panel>
  );
}
