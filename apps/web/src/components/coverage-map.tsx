"use client";

/**
 * The coverage map. Section 7.3 point 2.
 *
 * MapLibre against vector tiles served from PostGIS by `/v1/tiles/jurisdictions`. No tile vendor, no per
 * view billing, and no second copy of the boundaries to keep in step with the registry.
 *
 * There is no basemap, and that is the design rather than a gap. A road and satellite basemap under these
 * boundaries would say nothing about permission risk while implying a level of local detail this product
 * does not have. What the map is for is the shape of coverage: which counties are in, and how much decision
 * history each one carries. Everything else is noise on that.
 *
 * Fill opacity is the one place a quantity is drawn rather than written, and it encodes data depth, never
 * probability. Probability is never coloured anywhere, and a shaded county would be exactly that with an
 * extra step of deniability.
 */

import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { Label, Panel } from "@/components/primitives";
import { apiBaseUrl } from "@/lib/api-origin";

/**
 * Point MapLibre at its own worker.
 *
 * Required, not optional. Under any bundler, v6 cannot resolve its worker from `import.meta.url`, so each
 * consumer has to call this once. The v5 to v6 migration guide is the only place that says so.
 *
 * The path is a literal rather than `new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url)`,
 * which looks like the right answer and is not: webpack recognises that form and emits the worker as a
 * hashed asset, but the worker is 18 kB of glue that imports 478 kB from `./maplibre-gl-shared.mjs` beside
 * it, and webpack neither follows nor emits that sibling. `scripts/copy-maplibre-worker.mjs` puts both files
 * in `public/maplibre/` so the relative import resolves.
 *
 * Getting this wrong fails in the worst available way: the map constructs, the canvas appears, WebGL
 * initialises, the source and all four layers are present, the centre and zoom are correct, no error is
 * raised on any channel, and `isStyleLoaded()` returns false forever so not one tile is requested.
 */
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

/**
 * The design tokens the map needs, read from the document.
 *
 * MapLibre paints on a canvas, so it cannot use a CSS variable and needs a resolved colour string. Reading
 * them here keeps the map on the same tokens as everything else, and returning null when one is missing is
 * deliberate: a missing token means the map would draw a colour nobody chose, and the honest response is to
 * say the map could not be styled rather than to fall back to a hex literal that is correct only by
 * coincidence. `no-restricted-syntax` forbids hex literals in this codebase for exactly that reason.
 */
const TOKENS = ["--color-brass", "--bg-page", "--text-primary"] as const;

type MapPalette = Record<(typeof TOKENS)[number], string>;

function readPalette(): MapPalette | null {
  if (typeof window === "undefined") return null;
  const computed = getComputedStyle(document.documentElement);
  const palette: Partial<MapPalette> = {};
  for (const name of TOKENS) {
    const value = computed.getPropertyValue(name).trim();
    if (value === "") return null;
    palette[name] = value;
  }
  return palette as MapPalette;
}

export interface MapFeature {
  slug: string;
  name: string;
  region: string | null;
  data_depth: number;
}

export function CoverageMap({ jurisdictions }: { jurisdictions: MapFeature[] }) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (container.current === null || map.current !== null) return;

    const palette = readPalette();
    if (palette === null) {
      setFailed("the design tokens the map needs are not loaded");
      return;
    }
    const brass = palette["--color-brass"];
    const base = palette["--bg-page"];
    const ink = palette["--text-primary"];

    let instance: MapLibreMap;
    try {
      instance = new MapLibreMap({
        container: container.current,
        style: {
          version: 8,
          // An empty glyph and sprite set. Labels are drawn in HTML beside the map rather than in the
          // canvas, because a canvas label cannot use the product's typefaces and cannot be selected.
          sources: {
            jurisdictions: {
              type: "vector",
              tiles: [`${apiBaseUrl()}/v1/tiles/jurisdictions/{z}/{x}/{y}.mvt`],
              minzoom: 3,
              maxzoom: 12,
            },
          },
          layers: [
            { id: "background", type: "background", paint: { "background-color": base } },
            {
              id: "counties-fill",
              type: "fill",
              source: "jurisdictions",
              "source-layer": "jurisdictions",
              paint: {
                "fill-color": brass,
                // Depth, not probability. The floor is low but not invisible: a county we hold nothing for
                // should read as present and empty rather than as absent, and at six percent on this
                // background it read as absent.
                "fill-opacity": [
                  "interpolate",
                  ["linear"],
                  ["coalesce", ["get", "data_depth"], 0],
                  0,
                  0.12,
                  5,
                  0.24,
                  25,
                  0.36,
                  100,
                  0.48,
                ],
              },
            },
            {
              id: "counties-line",
              type: "line",
              source: "jurisdictions",
              "source-layer": "jurisdictions",
              paint: { "line-color": ink, "line-width": 0.75, "line-opacity": 0.55 },
            },
            {
              id: "counties-hover",
              type: "line",
              source: "jurisdictions",
              "source-layer": "jurisdictions",
              paint: { "line-color": brass, "line-width": 2 },
              filter: ["==", ["get", "slug"], ""],
            },
          ],
        },
        // The lower forty eight, which is where all twelve counties are.
        bounds: [
          [-125, 24],
          [-66, 50],
        ],
        fitBoundsOptions: { padding: 24 },
        attributionControl: false,
        // Motion lives in exactly two places in this product and neither is here.
        fadeDuration: 0,
      });
    } catch (error) {
      setFailed(error instanceof Error ? error.message : "the map could not start");
      return;
    }

    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.on("error", (event) => {
      // A tile that fails to load is worth saying out loud rather than leaving as an empty map.
      setFailed(event.error.message === "" ? "a tile did not load" : event.error.message);
    });

    /**
     * Read the slug off a feature under the pointer.
     *
     * `properties` is typed as an index signature of unknown, so the value has to be narrowed rather than
     * asserted. A tile whose properties changed shape would otherwise put whatever it carries into a URL.
     */
    const slugAt = (features: { properties: Record<string, unknown> }[] | undefined): string | null => {
      const value = features?.[0]?.properties.slug;
      return typeof value === "string" && value !== "" ? value : null;
    };

    instance.on("mousemove", "counties-fill", (event) => {
      setHovered(slugAt(event.features));
      instance.getCanvas().style.cursor = "pointer";
    });
    instance.on("mouseleave", "counties-fill", () => {
      setHovered(null);
      instance.getCanvas().style.cursor = "";
    });
    instance.on("click", "counties-fill", (event) => {
      const slug = slugAt(event.features);
      if (slug !== null) window.location.href = `/jurisdictions/${slug}`;
    });

    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance?.isStyleLoaded()) return;
    instance.setFilter("counties-hover", ["==", ["get", "slug"], hovered ?? ""]);
  }, [hovered]);

  const hoveredEntry = jurisdictions.find((entry) => entry.slug === hovered) ?? null;

  return (
    <section>
      <Label>coverage map</Label>
      <p
        className="mt-2 mb-3 max-w-2xl"
        style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
      >
        Shading is decision depth, not probability. A county we have loaded but hold no decisions for is
        faint rather than absent, because that is what it is. There is no road or satellite layer
        underneath, since neither says anything about who can refuse a project and both would imply local
        detail we do not have.
      </p>

      <Panel className="relative overflow-hidden">
        <div
          ref={container}
          role="img"
          aria-label="Map of the twelve covered counties, shaded by how many decisions we hold for each"
          style={{ height: 460, width: "100%" }}
        />

        {hoveredEntry !== null && (
          <div
            className="pointer-events-none absolute left-3 bottom-3 rounded-sm px-3 py-2"
            style={{
              backgroundColor: "var(--bg-raised)",
              border: "1px solid var(--line-strong)",
            }}
          >
            <div style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}>
              {hoveredEntry.name}
            </div>
            <div
              className="font-mono"
              data-numeric
              style={{ fontSize: "var(--text-tiny)", color: "var(--text-secondary)" }}
            >
              {hoveredEntry.data_depth} decision{hoveredEntry.data_depth === 1 ? "" : "s"} on record
            </div>
          </div>
        )}
      </Panel>

      {failed !== null && (
        <p className="mt-3" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
          The map did not load: {failed}. The coverage table below is the same information and does not
          depend on it.
        </p>
      )}
    </section>
  );
}
