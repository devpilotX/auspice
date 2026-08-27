/**
 * The determination block, and the axis beside it.
 *
 * This is the most important component in the product. Section 5.6: the probability at 76 pixels in
 * mono, the 80 percent interval below it in 12 pixel mono, a confidence tag, and to the right an axis
 * showing the interval as a filled band against a dashed brass marker for the local base rate.
 *
 * That single comparison, our interval against the county's own history, is the most informative thing
 * on the page. It answers the question a partner actually has, which is not "what is the number" but
 * "is this site better or worse than this county usually is".
 *
 * The probability renders in ink. There is no code path that colours it. A green 82 percent reads as
 * approve it, which turns a neutral rating into advice, and section 8.6 says neutrality is the asset.
 * What carries visual weight here is the width of the band, not the value of the number.
 */

import type { Determination } from "@/lib/api";
import { Label, Numeric, Tag } from "@/components/primitives";

const AXIS_WIDTH = 320;
const AXIS_HEIGHT = 64;
const TRACK_Y = 30;
const TRACK_HEIGHT = 10;

function percent(value: number): string {
  return `${Math.round(value * 100)}`;
}

/**
 * The interval axis. Hand written SVG, about forty lines, because a charting library would make it
 * worse and would add a dependency to draw two rectangles and a dashed line.
 */
export function IntervalAxis({
  low,
  high,
  point,
  baseRate,
}: {
  low: number;
  high: number;
  point: number;
  baseRate: number | null;
}) {
  const x = (value: number) => 8 + value * (AXIS_WIDTH - 16);
  const bandStart = x(low);
  const bandEnd = x(high);

  return (
    <svg
      width={AXIS_WIDTH}
      height={AXIS_HEIGHT}
      viewBox={`0 0 ${AXIS_WIDTH} ${AXIS_HEIGHT}`}
      role="img"
      aria-label={
        `The 80 percent interval runs from ${percent(low)} to ${percent(high)} percent, ` +
        `with a point estimate of ${percent(point)} percent` +
        (baseRate === null
          ? ". This county has no recorded base rate for this use class."
          : `. This county's own historical rate is ${percent(baseRate)} percent.`)
      }
    >
      {/* The track. A hairline, not a filled bar, so the band is what the eye lands on. */}
      <line
        x1={8}
        x2={AXIS_WIDTH - 8}
        y1={TRACK_Y + TRACK_HEIGHT / 2}
        y2={TRACK_Y + TRACK_HEIGHT / 2}
        stroke="var(--line-hairline)"
        strokeWidth={1}
      />

      {/* The interval, as a filled band in ink. Width is the message. */}
      <rect
        x={bandStart}
        y={TRACK_Y}
        width={Math.max(bandEnd - bandStart, 2)}
        height={TRACK_HEIGHT}
        fill="var(--text-primary)"
        opacity={0.16}
      />
      <line
        x1={bandStart}
        x2={bandStart}
        y1={TRACK_Y - 3}
        y2={TRACK_Y + TRACK_HEIGHT + 3}
        stroke="var(--text-primary)"
        strokeWidth={1}
      />
      <line
        x1={bandEnd}
        x2={bandEnd}
        y1={TRACK_Y - 3}
        y2={TRACK_Y + TRACK_HEIGHT + 3}
        stroke="var(--text-primary)"
        strokeWidth={1}
      />

      {/* The point estimate. A solid mark, not a dot, so it reads as a position rather than an object. */}
      <line
        x1={x(point)}
        x2={x(point)}
        y1={TRACK_Y - 7}
        y2={TRACK_Y + TRACK_HEIGHT + 7}
        stroke="var(--text-primary)"
        strokeWidth={2}
      />

      {/* The local base rate, dashed, in brass. The only chromatic mark on the page. */}
      {baseRate === null ? null : (
        <>
          <line
            x1={x(baseRate)}
            x2={x(baseRate)}
            y1={TRACK_Y - 11}
            y2={TRACK_Y + TRACK_HEIGHT + 11}
            stroke="var(--color-brass)"
            strokeWidth={1.5}
            strokeDasharray="3 3"
          />
          <text
            x={x(baseRate)}
            y={TRACK_Y + TRACK_HEIGHT + 24}
            textAnchor="middle"
            fill="var(--text-accent)"
            fontFamily="var(--font-mono)"
            fontSize={10.5}
            letterSpacing="0.06em"
          >
            {percent(baseRate)}
          </text>
        </>
      )}

      {/* Scale ends only. Intermediate ticks add ink without adding information. */}
      <text x={8} y={16} fill="var(--text-tertiary)" fontFamily="var(--font-mono)" fontSize={10.5}>
        0
      </text>
      <text
        x={AXIS_WIDTH - 8}
        y={16}
        textAnchor="end"
        fill="var(--text-tertiary)"
        fontFamily="var(--font-mono)"
        fontSize={10.5}
      >
        100
      </text>
    </svg>
  );
}

export function DeterminationBlock({ determination }: { determination: Determination }) {
  if (determination.abstained) return null;

  const probability = determination.approval_probability;
  const interval = determination.credible_interval_80;
  if (probability === null || interval === null) return null;

  const [low, high] = interval;

  return (
    <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <Label>probability of approval</Label>
        <div className="mt-2 flex items-baseline gap-3">
          {/* Counts into place once on first load. One of exactly two animations in the product. */}
          <Numeric size="determination" className="tabular-nums">
            {percent(probability)}
          </Numeric>
          <span
            className="font-mono"
            style={{ fontSize: "1.25rem", color: "var(--text-tertiary)" }}
          >
            %
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span
            data-numeric
            className="font-mono"
            style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
          >
            80% interval {percent(low)} to {percent(high)}
          </span>
          {determination.confidence ? <Tag>{determination.confidence} confidence</Tag> : null}
          {determination.interval_kind === "bootstrap" ? (
            <span style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}>
              bootstrap interval, not a credible interval
            </span>
          ) : null}
        </div>
      </div>

      <div className="shrink-0">
        <Label>against this county&rsquo;s own record</Label>
        <div className="mt-1">
          <IntervalAxis low={low} high={high} point={probability} baseRate={determination.local_base_rate} />
        </div>
        <p
          className="mt-1 max-w-80"
          style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
        >
          {determination.local_base_rate === null
            ? "This county has no recorded decisions of this type, so there is no base rate to compare against."
            : "The dashed brass marker is this county's historical approval rate for this use class. The band is our 80 percent interval."}
        </p>
      </div>
    </div>
  );
}

/**
 * The time distribution. A hand drawn months strip, thirty lines, showing p10 to p90 with p50 marked.
 *
 * A duration is half the answer. Section 9.4: a two year yes is often worse than a fast no because of
 * carry cost, so the strip sits directly under the probability rather than in a secondary panel.
 */
export function MonthsStrip({
  p10,
  p50,
  p90,
  basis,
}: {
  p10: number;
  p50: number;
  p90: number;
  basis: "fitted" | "empirical";
}) {
  const width = 320;
  const max = Math.max(p90 * 1.15, 12);
  const x = (months: number) => 8 + (months / max) * (width - 16);

  return (
    <div>
      <Label>months to a decision</Label>
      <svg
        width={width}
        height={44}
        viewBox={`0 0 ${width} 44`}
        role="img"
        aria-label={`Ten percent chance of a decision within ${p10} months, fifty percent within ${p50}, ninety percent within ${p90}.`}
        className="mt-2"
      >
        <line x1={8} x2={width - 8} y1={18} y2={18} stroke="var(--line-hairline)" strokeWidth={1} />
        <rect
          x={x(p10)}
          y={13}
          width={Math.max(x(p90) - x(p10), 2)}
          height={10}
          fill="var(--text-primary)"
          opacity={0.16}
        />
        <line x1={x(p50)} x2={x(p50)} y1={8} y2={28} stroke="var(--text-primary)" strokeWidth={2} />
        {[p10, p50, p90].map((value, index) => (
          <text
            key={value}
            x={x(value)}
            y={41}
            textAnchor={index === 0 ? "start" : index === 2 ? "end" : "middle"}
            fill="var(--text-tertiary)"
            fontFamily="var(--font-mono)"
            fontSize={10.5}
          >
            {Math.round(value)}
          </text>
        ))}
      </svg>
      <p style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}>
        {basis === "fitted"
          ? "From a survival model that keeps pending applications as censored rather than discarding them."
          : "The empirical distribution of decided cases. Too few observed exits to fit a model, so this is what we have."}
      </p>
    </div>
  );
}
