"use client";

/**
 * Loads the coverage map on demand.
 *
 * MapLibre is around 250 kB of JavaScript, which is what a map engine costs and is not a problem in itself.
 * It is a problem in the initial bundle: someone opening the coverage page to read the table would download
 * a rendering engine before the first row appeared, and the documented budget for this project is 26 kB of
 * route specific JavaScript.
 *
 * So the map arrives after the page does. `ssr: false` because it needs a DOM to measure and would render
 * nothing on the server anyway, and the placeholder holds the same height so the table below does not jump
 * when the map lands.
 *
 * The table is the same information and does not depend on this. If the chunk never loads, the page is still
 * complete, which is the reason the map is allowed to be optional at all.
 */

import dynamic from "next/dynamic";

import { Label, Panel } from "@/components/primitives";
import type { MapFeature } from "@/components/coverage-map";

const MAP_HEIGHT = 460;

const CoverageMap = dynamic(
  () => import("@/components/coverage-map").then((module) => module.CoverageMap),
  {
    ssr: false,
    loading: () => (
      <section>
        <Label>coverage map</Label>
        <Panel className="mt-3">
          <div
            style={{ height: MAP_HEIGHT }}
            className="flex items-center justify-center"
            aria-hidden
          >
            <span style={{ fontSize: "var(--text-small)", color: "var(--text-tertiary)" }}>
              loading the map
            </span>
          </div>
        </Panel>
      </section>
    ),
  },
);

export function CoverageMapPanel({ jurisdictions }: { jurisdictions: MapFeature[] }) {
  return <CoverageMap jurisdictions={jurisdictions} />;
}
