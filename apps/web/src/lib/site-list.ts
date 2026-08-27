/**
 * Reading a pasted or uploaded site list. Section 12 day 22, "portfolio upload".
 *
 * Someone with fourteen sites has them in a spreadsheet, not in their head. Typing them into a row editor
 * is the reason they would use a spreadsheet instead of this product. So this accepts what comes out of a
 * spreadsheet: comma or tab separated rows, with or without a header, in any column order it can recognise.
 *
 * Two decisions worth stating.
 *
 * It reports every bad row rather than stopping at the first. A list of fourteen sites with three typos
 * should come back naming all three, because otherwise the fix is three round trips.
 *
 * It never guesses a jurisdiction. An unrecognised county is an error naming the value and listing what is
 * covered, not a fuzzy match to the nearest slug. Scoring the wrong county silently is worse than refusing,
 * and this product's whole claim is that it knows which body decides.
 */

export interface ParsedSite {
  label: string;
  jurisdiction: string;
  useClass: string;
  relief: string[];
  acres: string;
  capacityMw: string;
}

export interface RowProblem {
  line: number;
  content: string;
  reason: string;
}

export interface ParsedList {
  sites: ParsedSite[];
  problems: RowProblem[];
}

/** Header spellings this accepts, mapped to the field they fill. */
const HEADERS: Record<string, keyof ParsedSite> = {
  label: "label",
  name: "label",
  site: "label",
  "site name": "label",
  project: "label",
  jurisdiction: "jurisdiction",
  county: "jurisdiction",
  slug: "jurisdiction",
  "use class": "useClass",
  use: "useClass",
  useclass: "useClass",
  type: "useClass",
  relief: "relief",
  "relief sought": "relief",
  acres: "acres",
  acreage: "acres",
  area: "acres",
  mw: "capacityMw",
  megawatts: "capacityMw",
  capacity: "capacityMw",
  "capacity mw": "capacityMw",
};

/** Column order assumed when there is no header row. */
const POSITIONAL: (keyof ParsedSite)[] = [
  "label",
  "jurisdiction",
  "useClass",
  "acres",
  "capacityMw",
  "relief",
];

function splitLine(line: string): string[] {
  // Tab wins when present, because a paste out of a spreadsheet is tab separated and a label may contain a
  // comma. Quoted CSV fields are handled so that "Smith, Jones LLC" survives.
  if (line.includes("\t")) return line.split("\t").map((cell) => cell.trim());

  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (const character of line) {
    if (character === '"') {
      quoted = !quoted;
      continue;
    }
    if (character === "," && !quoted) {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += character;
  }
  cells.push(current.trim());
  return cells;
}

function looksLikeHeader(cells: string[]): boolean {
  const recognised = cells.filter((cell) => Object.hasOwn(HEADERS, cell.toLowerCase())).length;
  return recognised >= 2;
}

function normaliseKey(value: string): string {
  return value.trim().toLowerCase().replaceAll("_", " ").replaceAll("-", " ");
}

/**
 * Parse a pasted list.
 *
 * `jurisdictions`, `useClasses` and `reliefs` are the vocabularies the API accepts, passed in rather than
 * imported so this stays a pure function and the caller uses the same lists the form offers.
 */
export function parseSiteList(
  text: string,
  vocabulary: {
    jurisdictions: readonly { slug: string; name: string }[];
    useClasses: readonly string[];
    reliefs: readonly string[];
  },
): ParsedList {
  const sites: ParsedSite[] = [];
  const problems: RowProblem[] = [];

  const bySlug = new Map(vocabulary.jurisdictions.map((entry) => [entry.slug.toLowerCase(), entry.slug]));

  // Several exact spellings of the same county, because "us-ia-linn", "Linn County, Iowa", "Linn County" and
  // "Linn" are all things a person writes and all unambiguous here. Exact lookups on a small set of known
  // forms, never a fuzzy match: "Loudon" is one letter from "Loudoun" and is a different real county.
  const byName = new Map<string, string>();
  for (const entry of vocabulary.jurisdictions) {
    const full = entry.name.toLowerCase();
    const withoutState = full.replace(/,[^,]*$/, "").trim();
    const bare = withoutState.replace(/ (county|parish|borough|city)$/, "").trim();
    for (const form of [full, withoutState, bare]) {
      if (form !== "") byName.set(form, entry.slug);
    }
  }

  const resolve = (value: string): string | undefined => {
    const key = value.trim().toLowerCase();
    return bySlug.get(key) ?? byName.get(key);
  };

  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let order: (keyof ParsedSite)[] | null = null;

  lines.forEach((raw, index) => {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) return;

    const cells = splitLine(line);

    if (order === null && looksLikeHeader(cells)) {
      order = cells.map((cell) => HEADERS[normaliseKey(cell)] ?? "label");
      return;
    }

    const columns = order ?? POSITIONAL;

    // A hand typed list often contains "Linn County, Iowa" in a comma separated line, which splits into two
    // cells and shifts every column after it. Try the jurisdiction cell joined with the one after it and
    // prefer that when it resolves, because a longer exact match consumes the stray cell as well as naming
    // the county. "Prince William County" resolves on its own, so testing the single cell first would leave
    // ", Virginia" sitting in the use class column.
    //
    // This is never a guess. The joined form either resolves exactly or it does not, and a spreadsheet would
    // have quoted the field anyway, which splitLine already handles.
    const jurisdictionColumn = columns.indexOf("jurisdiction");
    const atColumn = cells[jurisdictionColumn];
    const nextColumn = cells[jurisdictionColumn + 1];
    if (jurisdictionColumn >= 0 && atColumn !== undefined && nextColumn !== undefined) {
      const joined = `${atColumn}, ${nextColumn}`;
      if (resolve(joined) !== undefined) {
        cells.splice(jurisdictionColumn, 2, joined);
      }
    }

    const fields: Partial<Record<keyof ParsedSite, string>> = {};
    cells.forEach((cell, position) => {
      const field = columns[position];
      if (field !== undefined && cell !== "") fields[field] = cell;
    });

    const problem = (reason: string) => {
      problems.push({ line: index + 1, content: line, reason });
    };

    const jurisdictionRaw = fields.jurisdiction;
    if (jurisdictionRaw === undefined) {
      problem("no county. Give a registry slug such as us-va-loudoun, or a county name.");
      return;
    }
    const jurisdiction = resolve(jurisdictionRaw);
    if (jurisdiction === undefined) {
      problem(
        `we do not cover ${jurisdictionRaw}. Covered: ${vocabulary.jurisdictions
          .map((entry) => entry.slug)
          .join(", ")}`,
      );
      return;
    }

    const useClassRaw = fields.useClass ?? vocabulary.useClasses[0] ?? "";
    const useClass = useClassRaw.trim().toLowerCase().replaceAll(" ", "_").replaceAll("-", "_");
    if (!vocabulary.useClasses.includes(useClass)) {
      problem(`${useClassRaw} is not a use class we model. One of: ${vocabulary.useClasses.join(", ")}`);
      return;
    }

    const reliefRaw = fields.relief ?? "rezoning";
    const relief = reliefRaw
      .split(/[;+|]/)
      .map((value) => value.trim().toLowerCase().replaceAll(" ", "_").replaceAll("-", "_"))
      .filter((value) => value !== "");
    const unknownRelief = relief.filter((value) => !vocabulary.reliefs.includes(value));
    if (unknownRelief.length > 0) {
      problem(
        `${unknownRelief.join(", ")} is not relief we recognise. One of: ${vocabulary.reliefs.join(", ")}`,
      );
      return;
    }
    if (relief.length === 0) {
      problem("no relief sought. A site with nothing to apply for has nothing to score.");
      return;
    }

    const numeric = (value: string | undefined, field: string): string | null => {
      if (value === undefined) return "";
      const cleaned = value.replace(/[,\s]/g, "").replace(/(acres?|mw|megawatts?)$/i, "");
      if (cleaned === "") return "";
      const parsed = Number(cleaned);
      if (!Number.isFinite(parsed) || parsed <= 0) {
        problem(`${value} is not a usable ${field}. Leave it blank if you do not know it.`);
        return null;
      }
      return String(parsed);
    };

    const acres = numeric(fields.acres, "acreage");
    if (acres === null) return;
    const capacityMw = numeric(fields.capacityMw, "megawatt figure");
    if (capacityMw === null) return;

    sites.push({
      label: fields.label ?? `Site ${sites.length + 1}`,
      jurisdiction,
      useClass,
      relief,
      acres,
      capacityMw,
    });
  });

  if (sites.length === 0 && problems.length === 0) {
    problems.push({ line: 0, content: "", reason: "nothing to read. Paste one site per line." });
  }

  return { sites, problems };
}
