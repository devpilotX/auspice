"use client";

/**
 * Site search. Section 12 day 22.
 *
 * Answers the stage 0 question before anyone asks for a probability: who can say no here. Two kinds of
 * input, because there are two ways someone knows where their site is.
 *
 * A county name goes straight to that county's profile. A coordinate pair goes to the API's spatial join,
 * which reads the boundary index rather than guessing from the numbers.
 *
 * There is no address geocoding, and that is a decision rather than an omission. Geocoding needs a third
 * party service, which means a key, a rate limit, an external dependency in the request path, and a
 * confidence question on every result. A wrong geocode would resolve the wrong county and look completely
 * normal, which is the failure this product can least afford. Coordinates and county names are both exact.
 */

import { useMemo, useState } from "react";

import { Label, Numeric, Panel, Rule } from "@/components/primitives";
import { api, type LocateResult } from "@/lib/api";

/** "38.83, -77.56" and "38.83 -77.56" and "38.83N 77.56W" all mean the same place. */
export function parseCoordinates(input: string): { latitude: number; longitude: number } | null {
  const cleaned = input.trim().replace(/[()]/g, "");
  const match = /^(-?\d+(?:\.\d+)?)\s*([NnSs])?\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*([EeWw])?$/.exec(
    cleaned,
  );
  if (match === null) return null;

  let latitude = Number(match[1]);
  let longitude = Number(match[3]);
  if ((match[2] ?? "").toLowerCase() === "s") latitude = -Math.abs(latitude);
  if ((match[4] ?? "").toLowerCase() === "w") longitude = -Math.abs(longitude);

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return { latitude, longitude };
}

export interface Searchable {
  slug: string;
  name: string;
  region: string | null;
  data_depth: number;
}

/**
 * Match a county by any prefix of its name, slug or state.
 *
 * Substring matching on a list of twelve, not fuzzy matching. A near miss returns nothing rather than the
 * closest county, for the same reason the pasted list refuses one: "Loudon" and "Loudoun" are different
 * places and silently choosing between them would be the worst thing this interface could do.
 */
export function matchJurisdictions(query: string, all: Searchable[]): Searchable[] {
  const needle = query.trim().toLowerCase();
  if (needle.length < 2) return [];
  return all
    .filter((entry) =>
      [entry.slug, entry.name, entry.region ?? ""].some((field) =>
        field.toLowerCase().includes(needle),
      ),
    )
    .slice(0, 8);
}

export function SiteSearch({ jurisdictions }: { jurisdictions: Searchable[] }) {
  const [query, setQuery] = useState("");
  const [located, setLocated] = useState<LocateResult | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const coordinates = useMemo(() => parseCoordinates(query), [query]);
  const matches = useMemo(
    () => (coordinates === null ? matchJurisdictions(query, jurisdictions) : []),
    [query, coordinates, jurisdictions],
  );

  async function lookUp() {
    if (coordinates === null) return;
    setPending(true);
    setFailed(false);
    setLocated(null);
    const response = await api.locate(coordinates.longitude, coordinates.latitude);
    setPending(false);
    if (response === null) setFailed(true);
    else setLocated(response);
  }

  return (
    <section>
      <Label>find a site</Label>
      <p
        className="mt-2 mb-3 max-w-2xl"
        style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
      >
        A county name, or a latitude and longitude. Coordinates resolve against the boundary index and tell
        you which bodies can refuse a project there. We do not geocode street addresses, because a wrong
        geocode would name the wrong county and look entirely correct doing it.
      </p>

      <div className="flex flex-wrap gap-3">
        <input
          aria-label="Search for a county or a coordinate"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setLocated(null);
            setFailed(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && coordinates !== null) void lookUp();
          }}
          placeholder="Loudoun, or 38.9517, -77.4142"
          spellCheck={false}
          className="flex-1 rounded-sm px-3"
          style={{
            height: 40,
            minWidth: 260,
            fontSize: "var(--text-small)",
            border: "1px solid var(--line-hairline)",
            backgroundColor: "var(--bg-base)",
            color: "var(--text-primary)",
          }}
        />
        {coordinates !== null && (
          <button
            type="button"
            onClick={() => {
              void lookUp();
            }}
            disabled={pending}
            className="rounded-sm px-4 font-mono uppercase disabled:opacity-40"
            style={{
              height: 40,
              fontSize: "var(--text-micro)",
              letterSpacing: "0.12em",
              border: "1px solid var(--line-strong)",
              backgroundColor: "var(--bg-raised)",
              color: "var(--text-primary)",
            }}
          >
            {pending ? "looking" : "who decides here"}
          </button>
        )}
      </div>

      {matches.length > 0 && (
        <Panel className="mt-3">
          <ul>
            {matches.map((entry, index) => (
              <li key={entry.slug} style={index > 0 ? { borderTop: "1px solid var(--line-hairline)" } : {}}>
                <a
                  href={`/jurisdictions/${entry.slug}`}
                  className="flex items-baseline justify-between gap-4 px-3"
                  style={{ height: 40, textDecoration: "none" }}
                >
                  <span style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}>
                    {entry.name}
                  </span>
                  <span
                    className="font-mono"
                    style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
                  >
                    <Numeric size="tiny">{entry.data_depth}</Numeric> decisions on record
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {query.trim().length >= 2 && coordinates === null && matches.length === 0 && (
        <p className="mt-3" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
          Nothing matches {query.trim()}. We cover twelve counties, and we would rather say that than show
          you the closest name to what you typed.
        </p>
      )}

      {failed && (
        <p className="mt-3" style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}>
          The API did not answer, so we cannot say who decides there.
        </p>
      )}

      {located !== null && (
        <div className="mt-4">
          <Rule />
          {located.covered ? (
            <>
              <p
                className="mt-4 mb-2"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                {located.chain.length === 1
                  ? "One body decides here."
                  : `${located.chain.length} bodies can refuse a project here, most local first.`}
              </p>
              <Panel>
                <ul>
                  {located.chain.map((link, index) => (
                    <li
                      key={link.slug}
                      style={index > 0 ? { borderTop: "1px solid var(--line-hairline)" } : {}}
                    >
                      <a
                        href={`/jurisdictions/${link.slug}`}
                        className="flex items-baseline justify-between gap-4 px-3"
                        style={{ height: 40, textDecoration: "none" }}
                      >
                        <span style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}>
                          {link.name}
                        </span>
                        <span
                          className="font-mono uppercase"
                          style={{
                            fontSize: "var(--text-micro)",
                            letterSpacing: "0.12em",
                            color: "var(--text-tertiary)",
                          }}
                        >
                          {link.role.replaceAll("_", " ")}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </Panel>
            </>
          ) : (
            <p className="mt-4" style={{ fontSize: "var(--text-body)", color: "var(--text-primary)" }}>
              That point is outside the twelve counties we cover.
            </p>
          )}
          <p className="mt-3" style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}>
            {located.note}
          </p>
        </div>
      )}
    </section>
  );
}
