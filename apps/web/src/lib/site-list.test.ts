import { describe, expect, it } from "vitest";

import { parseSiteList } from "@/lib/site-list";

/*
  The site list parser is the front door to the portfolio screen, which is the wedge feature. Everything
  it gets wrong is a site scored in the wrong county or a row silently dropped, and both are worse than a
  refusal. These tests exist because the file had no direct coverage at all.

  The vocabulary is passed in rather than imported, so these tests supply a small fixed one. That is the
  same shape the page supplies from the API.
*/

const vocabulary = {
  jurisdictions: [
    { slug: "us-va-loudoun", name: "Loudoun County, Virginia" },
    { slug: "us-va-prince-william", name: "Prince William County, Virginia" },
    { slug: "us-ia-linn", name: "Linn County, Iowa" },
  ],
  useClasses: ["data_center_hyperscale", "data_center_colocation", "solar_utility"],
  reliefs: ["rezoning", "special_exception", "comprehensive_plan_amendment"],
} as const;

describe("parseSiteList, recognising the shape of the input", () => {
  it("reads a header row in any column order", () => {
    const { sites, problems } = parseSiteList(
      ["county,project,use class,mw", "us-va-loudoun,North Campus,data_center_hyperscale,300"].join(
        "\n",
      ),
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites).toHaveLength(1);
    expect(sites[0]).toMatchObject({
      label: "North Campus",
      jurisdiction: "us-va-loudoun",
      useClass: "data_center_hyperscale",
      capacityMw: "300",
    });
  });

  it("falls back to positional order when there is no header", () => {
    const { sites, problems } = parseSiteList(
      "North Campus,us-va-loudoun,data_center_hyperscale,412,300",
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites[0]).toMatchObject({
      label: "North Campus",
      jurisdiction: "us-va-loudoun",
      useClass: "data_center_hyperscale",
      acres: "412",
      capacityMw: "300",
    });
  });

  it("prefers tab splitting so a label may contain a comma", () => {
    const { sites, problems } = parseSiteList(
      "Smith, Jones LLC\tus-va-loudoun\tdata_center_hyperscale",
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites[0]?.label).toBe("Smith, Jones LLC");
  });

  it("honours quoted CSV fields", () => {
    const { sites, problems } = parseSiteList(
      '"Smith, Jones LLC",us-va-loudoun,data_center_hyperscale',
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites[0]?.label).toBe("Smith, Jones LLC");
  });

  it("skips blank lines and comment lines", () => {
    const { sites, problems } = parseSiteList(
      ["# my portfolio", "", "A,us-va-loudoun,solar_utility", "   ", "B,us-ia-linn,solar_utility"].join(
        "\n",
      ),
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites).toHaveLength(2);
  });

  it("accepts CRLF input, because a pasted spreadsheet on Windows carries it", () => {
    const { sites, problems } = parseSiteList(
      "A,us-va-loudoun,solar_utility\r\nB,us-ia-linn,solar_utility\r\n",
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites).toHaveLength(2);
  });
});

describe("parseSiteList, resolving a county without ever guessing", () => {
  it.each([
    ["a registry slug", "us-va-loudoun"],
    ["the full published name", "Loudoun County, Virginia"],
    ["the name without the state", "Loudoun County"],
    ["the bare county name", "Loudoun"],
  ])("resolves %s", (_label, spelling) => {
    const { sites, problems } = parseSiteList(`A,${spelling},solar_utility`, vocabulary);
    expect(problems).toEqual([]);
    expect(sites[0]?.jurisdiction).toBe("us-va-loudoun");
  });

  it("consumes a stray state cell when the joined form resolves", () => {
    // "Linn County, Iowa" splits into two cells and would otherwise shift every later column.
    const { sites, problems } = parseSiteList("A,Linn County, Iowa,solar_utility", vocabulary);
    expect(problems).toEqual([]);
    expect(sites[0]?.jurisdiction).toBe("us-ia-linn");
    expect(sites[0]?.useClass).toBe("solar_utility");
  });

  it("refuses a near miss rather than fuzzy matching it", () => {
    // "Loudon" is one letter from "Loudoun" and is a different real county. Scoring the wrong county
    // silently is the failure this product exists to avoid.
    const { sites, problems } = parseSiteList("A,Loudon,solar_utility", vocabulary);
    expect(sites).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.reason).toContain("we do not cover Loudon");
    expect(problems[0]?.reason).toContain("us-va-loudoun");
  });

  it("names the line number and the offending content", () => {
    const { problems } = parseSiteList(
      ["A,us-va-loudoun,solar_utility", "B,Nowhere County,solar_utility"].join("\n"),
      vocabulary,
    );
    expect(problems[0]?.line).toBe(2);
    expect(problems[0]?.content).toBe("B,Nowhere County,solar_utility");
  });
});

describe("parseSiteList, vocabularies", () => {
  it("normalises a use class written with spaces or hyphens", () => {
    const { sites, problems } = parseSiteList("A,us-va-loudoun,Data Center Hyperscale", vocabulary);
    expect(problems).toEqual([]);
    expect(sites[0]?.useClass).toBe("data_center_hyperscale");
  });

  it("refuses an unmodelled use class and lists what is accepted", () => {
    const { sites, problems } = parseSiteList("A,us-va-loudoun,casino", vocabulary);
    expect(sites).toEqual([]);
    expect(problems[0]?.reason).toContain("is not a use class we model");
    expect(problems[0]?.reason).toContain("solar_utility");
  });

  it("splits multiple relief on semicolon, plus or pipe", () => {
    const { sites, problems } = parseSiteList(
      "label,county,use,relief\nA,us-va-loudoun,solar_utility,rezoning; special exception",
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites[0]?.relief).toEqual(["rezoning", "special_exception"]);
  });

  it("defaults relief to rezoning when the column is absent", () => {
    const { sites } = parseSiteList("A,us-va-loudoun,solar_utility", vocabulary);
    expect(sites[0]?.relief).toEqual(["rezoning"]);
  });

  it("refuses unrecognised relief", () => {
    const { sites, problems } = parseSiteList(
      "label,county,use,relief\nA,us-va-loudoun,solar_utility,variance",
      vocabulary,
    );
    expect(sites).toEqual([]);
    expect(problems[0]?.reason).toContain("is not relief we recognise");
  });
});

describe("parseSiteList, numbers", () => {
  it("strips thousands separators and unit suffixes", () => {
    const { sites, problems } = parseSiteList(
      "label,county,use,acres,mw\nA,us-va-loudoun,solar_utility,\"1,200 acres\",300MW",
      vocabulary,
    );
    expect(problems).toEqual([]);
    expect(sites[0]?.acres).toBe("1200");
    expect(sites[0]?.capacityMw).toBe("300");
  });

  it.each([
    ["a non number", "banana"],
    ["zero", "0"],
    ["a negative", "-5"],
  ])("refuses %s as an acreage and says it may be left blank", (_label, value) => {
    const { sites, problems } = parseSiteList(
      `label,county,use,acres\nA,us-va-loudoun,solar_utility,${value}`,
      vocabulary,
    );
    expect(sites).toEqual([]);
    expect(problems[0]?.reason).toContain("Leave it blank if you do not know it");
  });

  it("treats an absent number as absent rather than as zero", () => {
    const { sites } = parseSiteList("A,us-va-loudoun,solar_utility", vocabulary);
    expect(sites[0]?.acres).toBe("");
    expect(sites[0]?.capacityMw).toBe("");
  });
});

describe("parseSiteList, reporting", () => {
  it("reports every bad row rather than stopping at the first", () => {
    const { sites, problems } = parseSiteList(
      [
        "A,us-va-loudoun,solar_utility",
        "B,Nowhere County,solar_utility",
        "C,us-ia-linn,casino",
        "D,Elsewhere,solar_utility",
      ].join("\n"),
      vocabulary,
    );
    expect(sites).toHaveLength(1);
    expect(problems).toHaveLength(3);
    expect(problems.map((problem) => problem.line)).toEqual([2, 3, 4]);
  });

  it("says there is nothing to read when the input is empty", () => {
    const { sites, problems } = parseSiteList("   \n\n# only a comment\n", vocabulary);
    expect(sites).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.reason).toContain("nothing to read");
  });

  it("names a row that carries no county at all", () => {
    const { problems } = parseSiteList("label,use\nA,solar_utility", vocabulary);
    expect(problems[0]?.reason).toContain("no county");
  });

  it("gives an unlabelled row a positional name", () => {
    const { sites } = parseSiteList("label,county,use\n,us-va-loudoun,solar_utility", vocabulary);
    expect(sites[0]?.label).toBe("Site 1");
  });

  it("handles a large list without dropping rows", () => {
    const lines = Array.from({ length: 500 }, (_v, index) => `Site ${index},us-va-loudoun,solar_utility`);
    const { sites, problems } = parseSiteList(lines.join("\n"), vocabulary);
    expect(problems).toEqual([]);
    expect(sites).toHaveLength(500);
  });
});
