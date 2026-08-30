/**
 * The published document reader.
 *
 * These pages carry the claims this product makes about its own accuracy and independence, so the thing
 * worth testing hardest is not that the parser renders headings. It is that the parser cannot silently drop
 * a line. A reader that skips what it does not understand would delete a sentence from a published
 * methodology and leave a page that still looks finished.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  documentTitle,
  parseDocument,
  parseInline,
  UnreadableMarkdown,
  type Block,
} from "../../src/lib/published-doc";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const PUBLISHED = ["METHODOLOGY.md", "NEUTRALITY.md", "DATA_SOURCES.md", "TERMS.md", "PRIVACY.md"];

function read(name: string): string {
  return readFileSync(path.join(REPO_ROOT, "docs", name), "utf8");
}

/** Every word of text the parser produced, so nothing can be compared away. */
function harvest(blocks: Block[]): string {
  const parts: string[] = [];
  const inlines = (nodes: { value: string }[]) => {
    for (const node of nodes) parts.push(node.value);
  };
  for (const block of blocks) {
    if (block.kind === "heading" || block.kind === "paragraph") inlines(block.text);
    else if (block.kind === "list") {
      for (const item of block.items) {
        inlines(item.text);
        for (const child of item.children) inlines(child);
      }
    } else {
      for (const cell of block.head) inlines(cell);
      for (const row of block.rows) for (const cell of row) inlines(cell);
    }
  }
  return parts.join(" ");
}

test.describe("published document reader", () => {
  test("every published document parses", () => {
    for (const name of PUBLISHED) {
      const blocks = parseDocument(read(name));
      expect(blocks.length, `${name} produced no blocks`).toBeGreaterThan(10);
      expect(documentTitle(blocks).length, `${name} has no title`).toBeGreaterThan(2);
    }
  });

  test("no sentence is dropped", () => {
    // Compares the words in the file against the words the parser kept. Markup is stripped from both
    // sides; anything else missing means the reader ate content.
    for (const name of PUBLISHED) {
      const source = read(name);
      const parsed = harvest(parseDocument(source));

      const words = (text: string) =>
        text
          // Ordered list markers are markup like the others. The number comes from the <ol>, not from the
          // text, so it is correctly absent from the parsed output.
          .replace(/^\d+\. /gm, " ")
          .replace(/[|#*`>-]/g, " ")
          .split(/\s+/)
          .filter((word) => /[a-z0-9]/i.test(word));

      const missing = words(source).filter((word) => !parsed.includes(word));
      expect(
        missing,
        `${name} lost ${missing.length} words, first few: ${missing.slice(0, 8).join(", ")}`,
      ).toHaveLength(0);
    }
  });

  test("an unreadable construct throws instead of vanishing", () => {
    // The whole point. Each of these is something the documents do not contain today, so support for it
    // has to be a decision rather than a silent omission the day someone writes one.
    for (const bad of ["```python\nprint(1)\n```", "> a pull quote", "<div>raw html</div>"]) {
      expect(() => parseDocument(`# Title\n\n${bad}\n`), bad).toThrow(UnreadableMarkdown);
    }
  });

  test("a table without a separator row throws", () => {
    expect(() => parseDocument("# T\n\n| a | b |\n| 1 | 2 |\n")).toThrow(UnreadableMarkdown);
  });

  test("headings, bold and inline code survive", () => {
    const blocks = parseDocument("# Title\n\n## Section\n\nA **bold** word and `some_code`.\n");
    expect(blocks[0]).toMatchObject({ kind: "heading", level: 1 });
    expect(blocks[1]).toMatchObject({ kind: "heading", level: 2 });
    const paragraph = blocks[2];
    expect(paragraph?.kind).toBe("paragraph");
    if (paragraph?.kind === "paragraph") {
      expect(paragraph.text.map((node) => node.kind)).toEqual([
        "text",
        "strong",
        "text",
        "code",
        "text",
      ]);
    }
  });

  test("a nested bullet stays under its parent", () => {
    const blocks = parseDocument("# T\n\n- parent\n  - child\n- sibling\n");
    const list = blocks[1];
    expect(list?.kind).toBe("list");
    if (list?.kind === "list") {
      expect(list.items).toHaveLength(2);
      expect(list.items[0]?.children).toHaveLength(1);
      expect(list.items[1]?.children).toHaveLength(0);
    }
  });

  test("a table keeps its shape", () => {
    const blocks = parseDocument("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n");
    const table = blocks[1];
    expect(table?.kind).toBe("table");
    if (table?.kind === "table") {
      expect(table.head).toHaveLength(2);
      expect(table.rows).toHaveLength(2);
      expect(table.rows[1]?.[1]?.[0]?.value).toBe("4");
    }
  });

  test("parseInline is not fooled by an unclosed marker", () => {
    // Returned as literal text, which is visible and wrong rather than invisible and wrong.
    expect(parseInline("an **unclosed marker")).toEqual([
      { kind: "text", value: "an **unclosed marker" },
    ]);
  });
});


test.describe("published document reader, constructs and refusals not previously covered", () => {
  test("an asterisk bullet is a bullet", () => {
    const blocks = parseDocument("# T\n\n* one\n* two\n");
    const list = blocks[1];
    expect(list?.kind).toBe("list");
    if (list?.kind === "list") {
      expect(list.ordered).toBe(false);
      expect(list.items).toHaveLength(2);
    }
  });

  test("an ordered list is ordered", () => {
    const blocks = parseDocument("# T\n\n1. one\n2. two\n3. three\n");
    const list = blocks[1];
    expect(list?.kind).toBe("list");
    if (list?.kind === "list") {
      expect(list.ordered).toBe(true);
      expect(list.items).toHaveLength(3);
    }
  });

  test("a table separator carrying alignment colons is still a separator", () => {
    // docs/ uses plain dashes today. A future document written with alignment would otherwise throw.
    const blocks = parseDocument("# T\n\n| a | b |\n|:--|--:|\n| 1 | 2 |\n");
    expect(blocks[1]?.kind).toBe("table");
  });

  test("an indented line under a bullet continues that item rather than starting a block", () => {
    const blocks = parseDocument("# T\n\n- the item begins\n  and continues here\n");
    const list = blocks[1];
    expect(list?.kind).toBe("list");
    if (list?.kind === "list") {
      expect(list.items).toHaveLength(1);
      expect(list.items[0]?.text.map((node) => node.value).join("")).toContain("continues here");
    }
  });

  test("a heading deeper than three levels throws rather than rendering as a paragraph", () => {
    // The reader supports three levels. A fourth would otherwise fall through to the paragraph branch and
    // render the hashes as literal text, which looks like a typo rather than an unsupported construct.
    expect(() => parseDocument("# T\n\n#### Four\n")).toThrow(UnreadableMarkdown);
  });

  test("the error names the line number and the offending content", () => {
    // A build failure that does not say which line is a build failure someone bisects by hand.
    try {
      parseDocument("# T\n\n> not supported\n");
      throw new Error("expected parseDocument to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(UnreadableMarkdown);
      const unreadable = error as UnreadableMarkdown;
      expect(unreadable.line).toBe(3);
      expect(unreadable.content).toBe("> not supported");
    }
  });

  test("a document with no h1 is refused rather than rendered untitled", () => {
    expect(() => documentTitle(parseDocument("## only a subheading\n"))).toThrow(
      /needs exactly one h1/,
    );
  });

  test("the PUBLISHED list covers every document the site actually renders", () => {
    // PUBLISHED above is hand written, so a page added to the site would not be covered by the tests in
    // this file and nobody would notice. DOCUMENTS in published-page.tsx is the authority, and it is read
    // as text rather than imported because importing it would pull React into a runner that has no DOM.
    const source = readFileSync(
      path.join(__dirname, "..", "..", "src", "components", "published-page.tsx"),
      "utf8",
    );
    const rendered = [...source.matchAll(/file:\s*"([A-Z_]+\.md)"/g)].map((match) => match[1]);
    expect(rendered.length).toBeGreaterThan(0);
    const uncovered = rendered.filter((name) => name !== undefined && !PUBLISHED.includes(name));
    expect(
      uncovered,
      `these documents are rendered by the site but not covered by PUBLISHED in this file: ${uncovered.join(", ")}`,
    ).toHaveLength(0);
  });
});
