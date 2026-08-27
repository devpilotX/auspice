"use client";

/**
 * Portfolio triage. Section 5.4 product 2.
 *
 * The question this screen answers is not "what is the probability for this site" but "of the fourteen
 * sites on my list, which three are worth spending diligence money on". That is the wedge, because it is
 * the decision people currently make by asking whoever has been in the market longest.
 *
 * One rule governs the whole layout. An abstention must never look like a low score. The API sorts
 * abstentions last and sends them with a null probability, and the table keeps them in a separate group
 * under their own heading rather than at the bottom of the ranked list, because a reader scanning a single
 * ranked column will read the last row as the worst site whatever the cell says. Sorting is not enough.
 * Separation is.
 *
 * The table is deliberately not a TanStack table. Sorting is fixed, because the ranking is the product's
 * opinion and a user re-sorting by data depth would be reading a different claim than the one being made.
 */

import { useMemo, useState } from "react";

import { Label, Numeric, Panel, Rule, StatusDot, Tag } from "@/components/primitives";
import {
  api,
  type PortfolioResponse,
  type PortfolioRow,
  type SiteInput,
} from "@/lib/api";
import { parseSiteList, type RowProblem } from "@/lib/site-list";

const ABSENT = "\u00b7";

/** The covered counties. Typing a slug that is not here is the single most likely input mistake. */
const JURISDICTIONS = [
  { slug: "us-va-loudoun", name: "Loudoun County, Virginia" },
  { slug: "us-va-prince-william", name: "Prince William County, Virginia" },
  { slug: "us-va-henrico", name: "Henrico County, Virginia" },
  { slug: "us-in-boone", name: "Boone County, Indiana" },
  { slug: "us-ia-linn", name: "Linn County, Iowa" },
  { slug: "us-fl-sarasota", name: "Sarasota County, Florida" },
  { slug: "us-ga-newton", name: "Newton County, Georgia" },
  { slug: "us-wy-laramie", name: "Laramie County, Wyoming" },
  { slug: "us-oh-licking", name: "Licking County, Ohio" },
  { slug: "us-az-maricopa", name: "Maricopa County, Arizona" },
  { slug: "us-or-morrow", name: "Morrow County, Oregon" },
  { slug: "us-tx-tarrant", name: "Tarrant County, Texas" },
] as const;

const USE_CLASSES = [
  "data_center_hyperscale",
  "data_center_colo",
  "solar_utility",
  "wind_onshore",
  "battery_storage",
  "warehouse_logistics",
  "manufacturing_advanced",
  "housing_multifamily",
] as const;

const RELIEFS = [
  "rezoning",
  "special_use_permit",
  "conditional_use_permit",
  "variance",
  "site_plan",
  "comprehensive_plan_amendment",
] as const;

interface Draft {
  id: number;
  label: string;
  jurisdiction: string;
  useClass: string;
  relief: string[];
  acres: string;
  capacityMw: string;
}

let nextId = 1;

function blankDraft(): Draft {
  return {
    id: nextId++,
    label: "",
    jurisdiction: JURISDICTIONS[0].slug,
    useClass: "data_center_hyperscale",
    relief: ["rezoning"],
    acres: "",
    capacityMw: "",
  };
}

/** Parse a numeric field. Empty means not stated, which is different from zero. */
function optionalNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function toSiteInput(draft: Draft, index: number): SiteInput {
  return {
    label: draft.label.trim() || `Site ${index + 1}`,
    jurisdiction: draft.jurisdiction,
    use_class: draft.useClass,
    relief_sought: draft.relief,
    acres: optionalNumber(draft.acres),
    capacity_mw: optionalNumber(draft.capacityMw),
  };
}

export default function PortfolioPage() {
  const [drafts, setDrafts] = useState<Draft[]>(() => [
    blankDraft(),
    blankDraft(),
    blankDraft(),
  ]);
  const [result, setResult] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [problems, setProblems] = useState<RowProblem[]>([]);

  /**
   * Replace the rows with a pasted list.
   *
   * Replace rather than append, because someone pasting fourteen sites into a form showing three blanks
   * means those fourteen, and appending would leave three empty rows for them to delete.
   */
  function ingest(text: string) {
    const parsed = parseSiteList(text, {
      jurisdictions: JURISDICTIONS,
      useClasses: USE_CLASSES,
      reliefs: RELIEFS,
    });
    setProblems(parsed.problems);
    if (parsed.sites.length > 0) {
      setDrafts(
        parsed.sites.map((site) => ({
          id: nextId++,
          label: site.label,
          jurisdiction: site.jurisdiction,
          useClass: site.useClass,
          relief: site.relief,
          acres: site.acres,
          capacityMw: site.capacityMw,
        })),
      );
      setResult(null);
      setError(null);
    }
  }

  const usable = useMemo(
    () =>
      drafts.filter(
        (draft) => draft.jurisdiction !== "" && draft.relief.length > 0,
      ),
    [drafts],
  );

  function update(id: number, patch: Partial<Draft>) {
    setDrafts((current) =>
      current.map((draft) =>
        draft.id === id ? { ...draft, ...patch } : draft,
      ),
    );
  }

  async function submit() {
    setPending(true);
    setError(null);
    const response = await api.portfolio(usable.map(toSiteInput));
    setPending(false);

    if (response.ok) {
      setResult(response.data);
      return;
    }
    setResult(null);
    setError(
      response.kind === "unreachable"
        ? "The API did not answer. Nothing was scored."
        : response.kind === "malformed"
          ? "The API answered with something this page could not read. Nothing is shown rather than something wrong."
          : response.detail,
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header>
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "var(--text-display-3)",
            color: "var(--text-primary)",
          }}
        >
          Portfolio triage
        </h1>
        <p
          className="mt-3 max-w-2xl"
          style={{
            fontSize: "var(--text-body)",
            color: "var(--text-secondary)",
          }}
        >
          Enter the sites under consideration. The list comes back ranked by
          approval probability, with the sites we cannot score separated out
          rather than sorted to the bottom. A site we will not put a number on
          is not the same as a site with a low number.
        </p>
      </header>

      <Rule className="my-8" strong />

      <SiteListInput onIngest={ingest} problems={problems} />

      <Rule className="my-8" />

      <SiteEditor
        drafts={drafts}
        onUpdate={update}
        onAdd={() => {
          setDrafts((current) => [...current, blankDraft()]);
        }}
        onRemove={(id) => {
          setDrafts((current) =>
            current.length > 1
              ? current.filter((draft) => draft.id !== id)
              : current,
          );
        }}
      />

      <div className="mt-6 flex items-center gap-4">
        <button
          type="button"
          onClick={() => {
            void submit();
          }}
          disabled={pending || usable.length === 0}
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
          {pending
            ? "scoring"
            : `score ${usable.length} site${usable.length === 1 ? "" : "s"}`}
        </button>
        <span
          style={{
            fontSize: "var(--text-tiny)",
            color: "var(--text-tertiary)",
          }}
        >
          Up to 500 sites per request.
        </span>
      </div>

      {error !== null && (
        <Panel className="mt-6 p-4">
          <p
            style={{
              fontSize: "var(--text-small)",
              color: "var(--text-primary)",
            }}
          >
            {error}
          </p>
        </Panel>
      )}

      {result !== null && <Results result={result} />}
    </main>
  );
}

/* ---------------------------------------------------------------------------
   Input
   --------------------------------------------------------------------------- */

/**
 * Paste or upload a list.
 *
 * The row editor below is for adjusting a few sites. This is for the case the feature exists to serve: a
 * list of fourteen already sitting in a spreadsheet. Typing them in one at a time is the reason someone
 * would stay in the spreadsheet instead.
 *
 * Problems are shown in full and next to the line that caused them. A parser that reported only the first
 * bad row in a list of fourteen would turn three typos into three round trips.
 */
function SiteListInput({
  onIngest,
  problems,
}: {
  onIngest: (text: string) => void;
  problems: RowProblem[];
}) {
  const [text, setText] = useState("");

  return (
    <section>
      <Label>paste a list</Label>
      <p
        className="mt-2 mb-3 max-w-2xl"
        style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
      >
        One site per line, from a spreadsheet or typed. Commas or tabs, with or without a header row. The
        column order without a header is site, county, use class, acres, megawatts, relief. A county we do
        not cover is reported rather than matched to the nearest one.
      </p>

      <textarea
        aria-label="Paste a list of sites"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
        rows={4}
        spellCheck={false}
        placeholder={"Pageland Road, Loudoun County, data_center_hyperscale, 412, 300"}
        className="w-full rounded-sm px-3 py-2 font-mono"
        style={{
          fontSize: "var(--text-tiny)",
          border: "1px solid var(--line-hairline)",
          backgroundColor: "var(--bg-page)",
          color: "var(--text-primary)",
          resize: "vertical",
        }}
      />

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={() => {
            onIngest(text);
          }}
          disabled={text.trim() === ""}
          className="rounded-sm px-4 font-mono uppercase disabled:opacity-40"
          style={{
            height: 40,
            fontSize: "var(--text-micro)",
            letterSpacing: "0.12em",
            border: "1px solid var(--line-hairline)",
            backgroundColor: "var(--bg-raised)",
            color: "var(--text-primary)",
          }}
        >
          read the list
        </button>

        <label
          className="cursor-pointer font-mono uppercase"
          style={{
            fontSize: "var(--text-micro)",
            letterSpacing: "0.12em",
            color: "var(--text-accent)",
          }}
        >
          or upload a csv
          <input
            type="file"
            accept=".csv,.tsv,.txt,text/csv,text/plain,text/tab-separated-values"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file === undefined) return;
              // Read in the browser. A site list is commercially sensitive and there is no reason for it to
              // touch a server before the scoring request that needs it.
              void file.text().then((contents) => {
                setText(contents);
                onIngest(contents);
              });
            }}
          />
        </label>
      </div>

      {problems.length > 0 && (
        <Panel className="mt-4 p-4">
          <Label>
            {problems.length} row{problems.length === 1 ? "" : "s"} we could not read
          </Label>
          <ul className="mt-3">
            {problems.map((problem) => (
              <li
                key={`${problem.line}-${problem.reason}`}
                className="py-1.5"
                style={{ borderTop: "1px solid var(--line-hairline)" }}
              >
                <span
                  className="font-mono"
                  style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
                >
                  line {problem.line}
                </span>
                <span
                  className="ml-3"
                  style={{ fontSize: "var(--text-small)", color: "var(--text-primary)" }}
                >
                  {problem.reason}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </section>
  );
}

const FIELD_STYLE = {
  height: 40,
  fontSize: "var(--text-small)",
  border: "1px solid var(--line-hairline)",
  backgroundColor: "var(--bg-page)",
  color: "var(--text-primary)",
} as const;

function SiteEditor({
  drafts,
  onUpdate,
  onAdd,
  onRemove,
}: {
  drafts: Draft[];
  onUpdate: (id: number, patch: Partial<Draft>) => void;
  onAdd: () => void;
  onRemove: (id: number) => void;
}) {
  return (
    <Panel>
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Sites to score</caption>
        <thead>
          <tr>
            {[
              "Label",
              "Jurisdiction",
              "Use class",
              "Relief",
              "Acres",
              "MW",
              "",
            ].map((heading) => (
              <th
                key={heading}
                scope="col"
                className="px-3 py-2 font-mono uppercase"
                style={{
                  fontSize: "var(--text-micro)",
                  letterSpacing: "0.12em",
                  color: "var(--text-tertiary)",
                  borderBottom: "1px solid var(--line-strong)",
                  fontWeight: 400,
                }}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {drafts.map((draft, index) => (
            <tr
              key={draft.id}
              style={{ borderBottom: "1px solid var(--line-hairline)" }}
            >
              <td className="px-3" style={{ height: 40 }}>
                <input
                  aria-label={`Label for site ${index + 1}`}
                  value={draft.label}
                  onChange={(event) => {
                    onUpdate(draft.id, { label: event.target.value });
                  }}
                  placeholder={`Site ${index + 1}`}
                  maxLength={120}
                  className="w-full rounded-sm px-2"
                  style={FIELD_STYLE}
                />
              </td>
              <td className="px-3">
                <select
                  aria-label={`Jurisdiction for site ${index + 1}`}
                  value={draft.jurisdiction}
                  onChange={(event) => {
                    onUpdate(draft.id, { jurisdiction: event.target.value });
                  }}
                  className="w-full rounded-sm px-2"
                  style={FIELD_STYLE}
                >
                  {JURISDICTIONS.map((jurisdiction) => (
                    <option key={jurisdiction.slug} value={jurisdiction.slug}>
                      {jurisdiction.name}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-3">
                <select
                  aria-label={`Use class for site ${index + 1}`}
                  value={draft.useClass}
                  onChange={(event) => {
                    onUpdate(draft.id, { useClass: event.target.value });
                  }}
                  className="w-full rounded-sm px-2"
                  style={FIELD_STYLE}
                >
                  {USE_CLASSES.map((useClass) => (
                    <option key={useClass} value={useClass}>
                      {useClass.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-3">
                <select
                  aria-label={`Relief sought for site ${index + 1}`}
                  multiple
                  value={draft.relief}
                  onChange={(event) => {
                    onUpdate(draft.id, {
                      relief: Array.from(
                        event.target.selectedOptions,
                        (option) => option.value,
                      ),
                    });
                  }}
                  className="w-full rounded-sm px-2 py-1"
                  style={{ ...FIELD_STYLE, height: 40 }}
                >
                  {RELIEFS.map((relief) => (
                    <option key={relief} value={relief}>
                      {relief.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-3">
                <input
                  aria-label={`Acres for site ${index + 1}`}
                  value={draft.acres}
                  onChange={(event) => {
                    onUpdate(draft.id, { acres: event.target.value });
                  }}
                  inputMode="decimal"
                  placeholder={ABSENT}
                  className="w-20 rounded-sm px-2 font-mono"
                  style={FIELD_STYLE}
                />
              </td>
              <td className="px-3">
                <input
                  aria-label={`Megawatts for site ${index + 1}`}
                  value={draft.capacityMw}
                  onChange={(event) => {
                    onUpdate(draft.id, { capacityMw: event.target.value });
                  }}
                  inputMode="decimal"
                  placeholder={ABSENT}
                  className="w-20 rounded-sm px-2 font-mono"
                  style={FIELD_STYLE}
                />
              </td>
              <td className="px-3 text-right">
                <button
                  type="button"
                  onClick={() => {
                    onRemove(draft.id);
                  }}
                  disabled={drafts.length === 1}
                  aria-label={`Remove site ${index + 1}`}
                  className="font-mono disabled:opacity-30"
                  style={{
                    fontSize: "var(--text-small)",
                    color: "var(--text-tertiary)",
                  }}
                >
                  remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 py-2">
        <button
          type="button"
          onClick={onAdd}
          className="font-mono uppercase"
          style={{
            fontSize: "var(--text-micro)",
            letterSpacing: "0.12em",
            color: "var(--text-accent)",
          }}
        >
          add a site
        </button>
      </div>
    </Panel>
  );
}

/* ---------------------------------------------------------------------------
   Output
   --------------------------------------------------------------------------- */

function Results({ result }: { result: PortfolioResponse }) {
  // The API already sorts abstentions last. Splitting them is what keeps a reader from treating the
  // bottom of one list as the worst site, which sorting alone does not prevent.
  const scored = result.ranked.filter((row) => !row.abstained);
  const abstained = result.ranked.filter((row) => row.abstained);

  return (
    <section className="mt-12">
      <Rule strong />
      <div className="flex flex-wrap items-baseline justify-between gap-4 py-4">
        <h2
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "var(--text-heading-1)",
            color: "var(--text-primary)",
          }}
        >
          Ranked
        </h2>
        <p
          style={{
            fontSize: "var(--text-tiny)",
            color: "var(--text-tertiary)",
          }}
        >
          <Numeric size="tiny">{result.scored}</Numeric> of{" "}
          <Numeric size="tiny">{result.submitted}</Numeric> scored
        </p>
      </div>

      {scored.length > 0 ? (
        <RankedTable rows={scored} />
      ) : (
        <Panel className="p-6">
          <p
            style={{
              fontSize: "var(--text-body)",
              color: "var(--text-primary)",
            }}
          >
            We did not put a number on any of these sites.
          </p>
          <p
            className="mt-2"
            style={{
              fontSize: "var(--text-small)",
              color: "var(--text-secondary)",
            }}
          >
            That is the honest answer for this corpus rather than a fault in the
            request. Each site below says which condition stopped it.
          </p>
        </Panel>
      )}

      {abstained.length > 0 && <NotScored rows={abstained} />}

      <p
        className="mt-8 max-w-3xl"
        style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
      >
        {result.note}
      </p>
    </section>
  );
}

const HEADINGS = [
  { key: "rank", label: "", numeric: true },
  { key: "label", label: "Site", numeric: false },
  { key: "jurisdiction", label: "Jurisdiction", numeric: false },
  { key: "probability", label: "Approval", numeric: true },
  { key: "interval", label: "80% interval", numeric: true },
  { key: "months", label: "Months (p50)", numeric: true },
  { key: "rule", label: "Rules change", numeric: true },
  { key: "depth", label: "Comparables", numeric: true },
  { key: "state", label: "Data", numeric: false },
] as const;

function HeaderRow() {
  return (
    <thead>
      <tr>
        {HEADINGS.map((heading) => (
          <th
            key={heading.key}
            scope="col"
            className="px-3 py-2 font-mono uppercase"
            style={{
              fontSize: "var(--text-micro)",
              letterSpacing: "0.12em",
              color: "var(--text-tertiary)",
              borderBottom: "1px solid var(--line-strong)",
              textAlign: heading.numeric ? "right" : "left",
              fontWeight: 400,
            }}
          >
            {heading.label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function Cell({
  children,
  numeric = false,
}: {
  children: React.ReactNode;
  numeric?: boolean;
}) {
  return (
    <td
      className="px-3"
      style={{
        height: 40,
        fontSize: "var(--text-small)",
        color: "var(--text-primary)",
        textAlign: numeric ? "right" : "left",
      }}
    >
      {children}
    </td>
  );
}

function RankedTable({ rows }: { rows: PortfolioRow[] }) {
  return (
    <Panel>
      <table className="w-full border-collapse">
        <caption className="sr-only">
          Ranked by approval probability. Every site in this table carries a
          number. Sites without one appear in a separate table below and take no
          position in this order.
        </caption>
        <HeaderRow />
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row.public_id}
              style={{ borderBottom: "1px solid var(--line-hairline)" }}
            >
              <Cell numeric>
                <Numeric size="small">{index + 1}</Numeric>
              </Cell>
              <Cell>
                <a
                  href={`/report/${row.public_id}`}
                  style={{
                    color: "var(--text-primary)",
                    textDecoration: "none",
                  }}
                >
                  {row.label ?? ABSENT}
                </a>
              </Cell>
              <Cell>{row.jurisdiction}</Cell>
              <Cell numeric>
                {/* Never coloured. A green 82 percent reads as advice. */}
                <Numeric size="small">
                  {row.approval_probability === null
                    ? ABSENT
                    : `${Math.round(row.approval_probability * 100)}%`}
                </Numeric>
              </Cell>
              <Cell numeric>
                <Numeric size="small">
                  {row.credible_interval_80 === null
                    ? ABSENT
                    : `${Math.round(row.credible_interval_80[0] * 100)} to ${Math.round(
                        row.credible_interval_80[1] * 100,
                      )}`}
                </Numeric>
              </Cell>
              <Cell numeric>
                <Numeric size="small">
                  {row.months_p50 === null
                    ? ABSENT
                    : Math.round(row.months_p50)}
                </Numeric>
              </Cell>
              <Cell numeric>
                <Numeric size="small">
                  {row.rule_change_probability === null
                    ? ABSENT
                    : `${Math.round(row.rule_change_probability * 100)}%`}
                </Numeric>
              </Cell>
              <Cell numeric>
                <Numeric size="small">{row.data_depth}</Numeric>
              </Cell>
              <Cell>
                <StatusDot
                  state={row.stale ? "stale" : "fresh"}
                  label={row.stale ? "stale" : "current"}
                />
              </Cell>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/**
 * The sites we would not score.
 *
 * Under its own heading with no probability column at all. Not a greyed out row in the ranked table and
 * not a dash where a number would go, because both of those read as a number we chose to withhold. There
 * is no number to withhold.
 */
function NotScored({ rows }: { rows: PortfolioRow[] }) {
  return (
    <div className="mt-10">
      <Rule strong />
      <div className="flex flex-wrap items-baseline justify-between gap-4 py-4">
        <h3
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "var(--text-heading-1)",
            color: "var(--text-primary)",
          }}
        >
          We do not know
        </h3>
        <Tag>not ranked</Tag>
      </div>
      <p
        className="mb-4 max-w-2xl"
        style={{
          fontSize: "var(--text-small)",
          color: "var(--text-secondary)",
        }}
      >
        These sites are not at the bottom of the list above. They are not on it.
        We hold too little on each to put a number against it, and a low number
        would misrepresent that as a finding.
      </p>
      <Panel>
        <table className="w-full border-collapse">
          <caption className="sr-only">
            Sites we would not score. These carry no probability, and there is
            no probability column, because a blank cell reads as a number
            withheld.
          </caption>
          <thead>
            <tr>
              {["Site", "Jurisdiction", "Comparables", "Data"].map(
                (heading, index) => (
                  <th
                    key={heading}
                    scope="col"
                    className="px-3 py-2 font-mono uppercase"
                    style={{
                      fontSize: "var(--text-micro)",
                      letterSpacing: "0.12em",
                      color: "var(--text-tertiary)",
                      borderBottom: "1px solid var(--line-strong)",
                      textAlign: index === 2 ? "right" : "left",
                      fontWeight: 400,
                    }}
                  >
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.public_id}
                style={{ borderBottom: "1px solid var(--line-hairline)" }}
              >
                <Cell>
                  <a
                    href={`/report/${row.public_id}`}
                    style={{
                      color: "var(--text-primary)",
                      textDecoration: "none",
                    }}
                  >
                    {row.label ?? ABSENT}
                  </a>
                </Cell>
                <Cell>{row.jurisdiction}</Cell>
                <Cell numeric>
                  <Numeric size="small">{row.data_depth}</Numeric>
                </Cell>
                <Cell>
                  <StatusDot
                    state={row.stale ? "stale" : "fresh"}
                    label={row.stale ? "stale" : "current"}
                  />
                </Cell>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
