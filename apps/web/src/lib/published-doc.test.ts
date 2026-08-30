import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { UnreadableMarkdown, documentTitle, parseDocument, parseInline } from "@/lib/published-doc";

/*
  The published document reader renders docs/*.md at build time and throws on any construct it does not
  understand. That is a deliberate choice: a parser that silently drops a line it cannot read would
  quietly delete a sentence from a published methodology and the page would still look finished.

  The cost of that choice is that adding a blockquote to docs/METHODOLOGY.md breaks the production build
  with no earlier warning. The last describe block in this file is the earlier warning.
*/

const WEB_ROOT = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "..", "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..", "..");

describe("parseInline", () => {
  it("returns a single text node for plain prose", () => {
    expect(parseInline("plain words")).toEqual([{ kind: "text", value: "plain words" }]);
  });

  it("reads bold runs", () => {
    expect(parseInline("a **bold** b")).toEqual([
      { kind: "text", value: "a " },
      { kind: "strong", value: "bold" },
      { kind: "text", value: " b" },
    ]);
  });

  it("reads inline code runs", () => {
    expect(parseInline("run `npm test` now")).toEqual([
      { kind: "text", value: "run " },
      { kind: "code", value: "npm test" },
      { kind: "text", value: " now" },
    ]);
  });

  it("reads several runs in one line", () => {
    const nodes = parseInline("**one** and `two` and **three**");
    expect(nodes.filter((node) => node.kind === "strong")).toHaveLength(2);
    expect(nodes.filter((node) => node.kind === "code")).toHaveLength(1);
  });

  it("never returns an empty array, so a caller always has something to render", () => {
    expect(parseInline("")).toEqual([{ kind: "text", value: "" }]);
  });
});

describe("parseDocument, constructs it supports", () => {
  it.each([
    [1, "# One"],
    [2, "## Two"],
    [3, "### Three"],
  ])("reads a level %i heading", (level, source) => {
    const blocks = parseDocument(source);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "heading", level });
  });

  it("reads a paragraph and joins its wrapped lines", () => {
    const blocks = parseDocument("first line\nsecond line\n\nnext paragraph");
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ kind: "paragraph" });
    const first = blocks[0];
    if (first?.kind !== "paragraph") throw new Error("expected a paragraph");
    expect(first.text[0]?.value).toBe("first line second line");
  });

  it("reads an unordered list", () => {
    const blocks = parseDocument("- one\n- two\n- three");
    const list = blocks[0];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.ordered).toBe(false);
    expect(list.items).toHaveLength(3);
  });

  it("reads an unordered list written with asterisks", () => {
    const blocks = parseDocument("* one\n* two");
    const list = blocks[0];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.items).toHaveLength(2);
  });

  it("reads an ordered list", () => {
    const blocks = parseDocument("1. one\n2. two");
    const list = blocks[0];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.ordered).toBe(true);
    expect(list.items).toHaveLength(2);
  });

  it("reads one level of nesting under a bullet", () => {
    const blocks = parseDocument("- parent\n  - child one\n  - child two");
    const list = blocks[0];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.items).toHaveLength(1);
    expect(list.items[0]?.children).toHaveLength(2);
  });

  it("continues an item's sentence across an indented non bullet line", () => {
    const blocks = parseDocument("- the item begins\n  and continues here");
    const list = blocks[0];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.items).toHaveLength(1);
    const joined = list.items[0]?.text.map((node) => node.value).join("");
    expect(joined).toContain("and continues here");
  });

  it("reads a table with its header row", () => {
    const blocks = parseDocument("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |");
    const table = blocks[0];
    if (table?.kind !== "table") throw new Error("expected a table");
    expect(table.head).toHaveLength(2);
    expect(table.rows).toHaveLength(2);
  });

  it("reads a table separator that carries alignment colons", () => {
    const blocks = parseDocument("| a | b |\n|:--|--:|\n| 1 | 2 |");
    expect(blocks[0]?.kind).toBe("table");
  });

  it("reads inline formatting inside a table cell", () => {
    const blocks = parseDocument("| a |\n|---|\n| **bold** |");
    const table = blocks[0];
    if (table?.kind !== "table") throw new Error("expected a table");
    expect(table.rows[0]?.[0]?.[0]).toMatchObject({ kind: "strong", value: "bold" });
  });
});

describe("parseDocument, constructs it refuses", () => {
  it.each([
    ["a blockquote", "> quoted"],
    ["a fenced code block", "```js\ncode\n```"],
    ["raw HTML", "<div>markup</div>"],
    ["a heading deeper than three levels", "#### Four"],
  ])("throws UnreadableMarkdown on %s", (_label, source) => {
    expect(() => parseDocument(source)).toThrow(UnreadableMarkdown);
  });

  it("throws on a table whose separator row is missing", () => {
    expect(() => parseDocument("| a | b |\n| 1 | 2 |")).toThrow(UnreadableMarkdown);
  });

  it("names the line number and the offending content in the error", () => {
    try {
      parseDocument("# fine\n\n> not fine");
      throw new Error("expected parseDocument to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(UnreadableMarkdown);
      const unreadable = error as UnreadableMarkdown;
      expect(unreadable.line).toBe(3);
      expect(unreadable.content).toBe("> not fine");
      expect(unreadable.message).toContain("Add support for it");
    }
  });
});

describe("documentTitle", () => {
  it("returns the single h1", () => {
    expect(documentTitle(parseDocument("# The Title\n\nbody"))).toBe("The Title");
  });

  it("flattens inline runs in the title", () => {
    expect(documentTitle(parseDocument("# A **bold** title"))).toBe("A bold title");
  });

  it("throws when there is no h1, rather than rendering an untitled page", () => {
    expect(() => documentTitle(parseDocument("## only a subheading"))).toThrow(
      /needs exactly one h1/,
    );
  });
});

describe("every document the site renders actually parses", () => {
  /*
    The list is derived from DOCUMENTS in components/published-page.tsx by reading that file as text,
    rather than by importing it, because importing it would pull React and Next into a node test. Reading
    it means adding a document to the site without adding it here cannot pass silently: the count check
    below fails.
  */
  const source = readFileSync(path.join(WEB_ROOT, "src", "components", "published-page.tsx"), "utf8");
  const files = [...source.matchAll(/file:\s*"([A-Z_]+\.md)"/g)].map((match) => match[1] ?? "");

  it("found the document list in published-page.tsx", () => {
    expect(files.length).toBeGreaterThanOrEqual(5);
  });

  it.each(files)("docs/%s parses and has exactly one h1", (file) => {
    const markdown = readFileSync(path.join(REPO_ROOT, "docs", file), "utf8");
    const blocks = parseDocument(markdown);
    expect(blocks.length).toBeGreaterThan(0);
    expect(documentTitle(blocks)).toBeTruthy();
  });
});
