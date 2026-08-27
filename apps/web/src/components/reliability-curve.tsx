"use client";

/**
 * The reliability curve.
 *
 * This is the most important chart in the company, and the reason Recharts was rejected: it cannot draw
 * an honest calibration plot. What is needed is a reference diagonal, binned observations positioned at
 * their mean predicted value rather than at their bin centre, and confidence bands that are actually
 * correct. visx gives D3 level control inside React, which is what that takes.
 *
 * Three details matter and are easy to get wrong.
 *
 * Bins are plotted at their mean predicted probability, not at the midpoint of the bin. Plotting at the
 * midpoint smooths the curve toward the diagonal and flatters the model.
 *
 * The intervals are Wilson score intervals, so a bin holding four observations visibly does not claim
 * the authority of a bin holding four hundred. A normal approximation would produce symmetric intervals
 * running past zero and one at exactly the ends where the reader is looking hardest.
 *
 * Bin size is shown as the radius of the mark. A curve that looks wobbly because three bins hold two
 * points each is a different thing from a curve that is wobbly with three hundred, and the reader has to
 * be able to tell which they are looking at.
 */

import { AxisBottom, AxisLeft } from "@visx/axis";
import { Group } from "@visx/group";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";

export interface ReliabilityBin {
  lower: number;
  upper: number;
  count: number;
  mean_predicted: number;
  observed_frequency: number;
  interval: [number, number];
}

const WIDTH = 460;
const HEIGHT = 460;
const MARGIN = { top: 16, right: 20, bottom: 48, left: 52 };

export function ReliabilityCurve({
  bins,
  totalObservations,
}: {
  bins: ReliabilityBin[];
  totalObservations: number;
}) {
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const x = scaleLinear({ domain: [0, 1], range: [0, innerWidth] });
  const y = scaleLinear({ domain: [0, 1], range: [innerHeight, 0] });

  const populated = bins.filter((bin) => bin.count > 0);
  const maxCount = Math.max(...populated.map((bin) => bin.count), 1);
  const radius = (count: number) => 3 + Math.sqrt(count / maxCount) * 6;

  return (
    <figure className="m-0">
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={
          `A reliability curve over ${totalObservations} resolved predictions. ` +
          populated
            .map(
              (bin) =>
                `Predicted ${Math.round(bin.mean_predicted * 100)} percent, observed ${Math.round(
                  bin.observed_frequency * 100,
                )} percent, on ${bin.count} cases.`,
            )
            .join(" ")
        }
      >
        <Group left={MARGIN.left} top={MARGIN.top}>
          {/* The reference diagonal. Perfect calibration. Dashed so it never competes with the data. */}
          <LinePath
            data={[
              { x: 0, y: 0 },
              { x: 1, y: 1 },
            ]}
            x={(d) => x(d.x)}
            y={(d) => y(d.y)}
            stroke="var(--line-strong)"
            strokeWidth={1}
            strokeDasharray="4 4"
          />

          {/* Confidence intervals, drawn under the marks. */}
          {populated.map((bin) => (
            <line
              key={`interval-${String(bin.lower)}`}
              x1={x(bin.mean_predicted)}
              x2={x(bin.mean_predicted)}
              y1={y(bin.interval[0])}
              y2={y(bin.interval[1])}
              stroke="var(--text-primary)"
              strokeWidth={1}
              opacity={0.35}
            />
          ))}

          {/* The observed curve. */}
          <LinePath
            data={populated}
            x={(bin) => x(bin.mean_predicted)}
            y={(bin) => y(bin.observed_frequency)}
            stroke="var(--text-primary)"
            strokeWidth={1.5}
          />

          {/* The bins. Radius carries the sample size. */}
          {populated.map((bin) => (
            <circle
              key={`mark-${String(bin.lower)}`}
              cx={x(bin.mean_predicted)}
              cy={y(bin.observed_frequency)}
              r={radius(bin.count)}
              fill="var(--bg-raised)"
              stroke="var(--text-primary)"
              strokeWidth={1.5}
            />
          ))}

          <AxisBottom
            top={innerHeight}
            scale={x}
            numTicks={6}
            tickFormat={(value) => String(Math.round(Number(value) * 100))}
            stroke="var(--line-strong)"
            tickStroke="var(--line-strong)"
            tickLabelProps={() => ({
              fill: "var(--text-tertiary)",
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              textAnchor: "middle",
              dy: "0.25em",
            })}
            label="what we predicted"
            labelProps={{
              fill: "var(--text-secondary)",
              fontFamily: "var(--font-sans)",
              fontSize: 12.5,
              textAnchor: "middle",
            }}
            labelOffset={18}
          />
          <AxisLeft
            scale={y}
            numTicks={6}
            tickFormat={(value) => String(Math.round(Number(value) * 100))}
            stroke="var(--line-strong)"
            tickStroke="var(--line-strong)"
            tickLabelProps={() => ({
              fill: "var(--text-tertiary)",
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              textAnchor: "end",
              dx: "-0.25em",
              dy: "0.25em",
            })}
            label="what happened"
            labelProps={{
              fill: "var(--text-secondary)",
              fontFamily: "var(--font-sans)",
              fontSize: 12.5,
              textAnchor: "middle",
            }}
            labelOffset={32}
          />
        </Group>
      </svg>
      <figcaption
        className="mt-2 max-w-md"
        style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
      >
        Each mark is a bin of predictions, placed at the mean probability we gave and the frequency that
        actually occurred. The mark grows with the number of cases in the bin. The vertical line is a
        Wilson interval, so a bin resting on four cases does not look as certain as one resting on four
        hundred. Perfect calibration is the dashed diagonal.
      </figcaption>
    </figure>
  );
}
