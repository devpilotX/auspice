/**
 * Reading a pasted site list.
 *
 * The assertion that matters most is that an unrecognised county is refused rather than matched to
 * something nearby. Scoring the wrong county silently would be worse than any other failure this product
 * can have, because the entire claim is that it knows which body decides.
 */

import { expect, test } from "@playwright/test";

import { parseSiteList } from "../../src/lib/site-list";

const VOCABULARY = {
  jurisdictions: [
    { slug: "us-va-loudoun", name: "Loudoun County, Virginia" },
    { slug: "us-va-prince-william", name: "Prince William County, Virginia" },
    { slug: "us-ia-linn", name: "Linn County, Iowa" },
  ],
  useClasses: ["data_center_hyperscale", "solar_utility", "warehouse_logistics"],
  reliefs: ["rezoning", "special_use_permit", "conditional_use_permit"],
} as const;

const parse = (text: string) => parseSiteList(text, VOCABULARY);

test.describe("pasted site list", () => {
  test("reads a comma separated list with a header", () => {
    const { sites, problems } = parse(
      [
        "Site,County,Use class,Acres,MW",
        "Pageland Road,us-va-loudoun,data_center_hyperscale,412,300",
        "Manassas South,Prince William County, Virginia,data_center_hyperscale,180,150",
      ].join("\n"),
    );
    expect(problems).toHaveLength(0);
    expect(sites).toHaveLength(2);
    expect(sites[0]).toMatchObject({
      label: "Pageland Road",
      jurisdiction: "us-va-loudoun",
      acres: "412",
      capacityMw: "300",
    });
  });

  test("reads a tab separated paste out of a spreadsheet", () => {
    const { sites, problems } = parse(
      ["Cedar Rapids West\tus-ia-linn\tsolar_utility\t900\t", ""].join("\n"),
    );
    expect(problems).toHaveLength(0);
    expect(sites[0]).toMatchObject({ jurisdiction: "us-ia-linn", useClass: "solar_utility" });
    // Blank means not stated, which is not the same as zero.
    expect(sites[0]?.capacityMw).toBe("");
  });

  test("reads a list with no header in the documented column order", () => {
    const { sites, problems } = parse("A,us-va-loudoun,solar_utility,50,10");
    expect(problems).toHaveLength(0);
    expect(sites[0]).toMatchObject({ label: "A", useClass: "solar_utility", acres: "50" });
  });

  test("accepts a county name with or without the word county", () => {
    const { sites, problems } = parse(
      ["A,Loudoun,data_center_hyperscale", "B,Linn County, Iowa,solar_utility"].join("\n"),
    );
    expect(problems).toHaveLength(0);
    expect(sites.map((site) => site.jurisdiction)).toEqual(["us-va-loudoun", "us-ia-linn"]);
  });

  test("refuses a county we do not cover instead of guessing", () => {
    // "Loudon" is one letter from "Loudoun" and is a different real county in Tennessee. A fuzzy match here
    // would score the wrong jurisdiction and look completely normal doing it.
    const { sites, problems } = parse("A,Loudon,data_center_hyperscale");
    expect(sites).toHaveLength(0);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.reason).toContain("we do not cover Loudon");
    expect(problems[0]?.reason).toContain("us-va-loudoun");
  });

  test("reports every bad row rather than stopping at the first", () => {
    const { sites, problems } = parse(
      [
        "Good,us-va-loudoun,data_center_hyperscale,100,50",
        "Bad county,atlantis,data_center_hyperscale",
        "Bad use,us-ia-linn,casino",
        "Bad acres,us-va-loudoun,solar_utility,minus twelve",
      ].join("\n"),
    );
    expect(sites).toHaveLength(1);
    expect(problems).toHaveLength(3);
    expect(problems.map((problem) => problem.line)).toEqual([2, 3, 4]);
  });

  test("names the line number so a fix is findable", () => {
    const { problems } = parse(["", "# a comment", "Bad,nowhere,solar_utility"].join("\n"));
    expect(problems[0]?.line).toBe(3);
    expect(problems[0]?.content).toContain("Bad");
  });

  test("strips units and thousands separators from numbers", () => {
    const { sites, problems } = parse('A,us-va-loudoun,data_center_hyperscale,"1,240 acres",300MW');
    expect(problems).toHaveLength(0);
    expect(sites[0]).toMatchObject({ acres: "1240", capacityMw: "300" });
  });

  test("keeps a comma inside a quoted label", () => {
    const { sites } = parse('"Smith, Jones LLC site",us-va-loudoun,data_center_hyperscale');
    expect(sites[0]?.label).toBe("Smith, Jones LLC site");
  });

  test("reads several relief kinds from one cell", () => {
    const { sites, problems } = parse(
      "Site,County,Use class,Relief\nA,us-va-loudoun,data_center_hyperscale,rezoning + special use permit",
    );
    expect(problems).toHaveLength(0);
    expect(sites[0]?.relief).toEqual(["rezoning", "special_use_permit"]);
  });

  test("refuses relief it does not recognise", () => {
    const { problems } = parse("A,us-va-loudoun,data_center_hyperscale,,,demolition_permit");
    expect(problems[0]?.reason).toContain("demolition_permit");
  });

  test("says so when there is nothing to read", () => {
    const { sites, problems } = parse("   \n\n");
    expect(sites).toHaveLength(0);
    expect(problems[0]?.reason).toContain("nothing to read");
  });

  test("a zero acreage is a problem, not a value", () => {
    // Zero acres is not a small site, it is a typo or a missing figure, and the model treats absent and
    // zero as different things everywhere else.
    const { problems } = parse("A,us-va-loudoun,data_center_hyperscale,0");
    expect(problems[0]?.reason).toContain("not a usable acreage");
  });
});


test.describe("pasted site list, cases not previously covered", () => {
  test("accepts CRLF, because a spreadsheet paste on Windows carries it", () => {
    // The parser normalises CRLF. Without this test a regression there would strip nothing visible and
    // instead leave a trailing carriage return inside the last cell of every row.
    const { sites, problems } = parse(
      "A,us-va-loudoun,data_center_hyperscale\r\nB,us-ia-linn,solar_utility\r\n",
    );
    expect(problems).toHaveLength(0);
    expect(sites).toHaveLength(2);
    expect(sites[1]?.useClass).toBe("solar_utility");
  });

  test("normalises a use class written with spaces or hyphens", () => {
    const { sites, problems } = parse("A,us-va-loudoun,Data Center Hyperscale");
    expect(problems).toHaveLength(0);
    expect(sites[0]?.useClass).toBe("data_center_hyperscale");
  });

  test("a row with no county at all says so", () => {
    // Distinct from an unrecognised county. The advice differs, so the message has to.
    const { sites, problems } = parse("Site,Use class\nA,data_center_hyperscale");
    expect(sites).toHaveLength(0);
    expect(problems[0]?.reason).toContain("no county");
  });

  test("an unlabelled row is given a positional name rather than an empty one", () => {
    const { sites } = parse("Site,County,Use class\n,us-va-loudoun,solar_utility");
    expect(sites[0]?.label).toBe("Site 1");
  });

  test("a negative acreage is refused", () => {
    const { problems } = parse("A,us-va-loudoun,data_center_hyperscale,-5");
    expect(problems[0]?.reason).toContain("not a usable acreage");
  });

  test("five hundred rows are read without dropping any", () => {
    // The portfolio endpoint accepts up to 500 sites per request, so 500 is the real upper bound this
    // parser has to survive rather than an arbitrary large number.
    const lines = Array.from(
      { length: 500 },
      (_value, index) => `Site ${index},us-va-loudoun,solar_utility`,
    );
    const { sites, problems } = parse(lines.join("\n"));
    expect(problems).toHaveLength(0);
    expect(sites).toHaveLength(500);
    expect(sites[499]?.label).toBe("Site 499");
  });
});
