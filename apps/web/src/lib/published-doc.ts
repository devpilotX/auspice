/**
 * A markdown reader for the published documents, and only for those.
 *
 * `docs/METHODOLOGY.md`, `docs/NEUTRALITY.md` and `docs/DATA_SOURCES.md` are the source of truth for what
 * this product claims about itself. They are version controlled, reviewed as prose, and served on the
 * website. Rendering them means parsing markdown, and there were three ways to do it.
 *
 * A markdown library would pull in a dependency and hand back an HTML string, which then needs
 * `dangerouslySetInnerHTML` and a stylesheet that overrides the design system. Writing the pages as React
 * and copying the prose across would give two versions of a legal claim that drift. Parsing the subset the
 * documents actually use gives structured nodes that render through the existing primitives, and that is
 * what this does.
 *
 * The subset is measured, not guessed: headings to three levels, bullets with one level of nesting, ordered
 * lists, tables, bold, inline code, and paragraphs. The documents contain no code fences, no blockquotes,
 * no links, no italics, no horizontal rules and no raw HTML.
 *
 * The important property is the last one. `parseDocument` throws on a construct it does not understand
 * rather than skipping it. A parser that silently drops a line it cannot read would quietly delete a
 * sentence from a published methodology, and nobody would notice, because the page would still look
 * finished. Failing means a new construct surfaces as a build error on the day it is written.
 */

export type Inline =
  | { kind: "text"; value: string }
  | { kind: "strong"; value: string }
  | { kind: "code"; value: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: Inline[] }
  | { kind: "paragraph"; text: Inline[] }
  | { kind: "list"; ordered: boolean; items: { text: Inline[]; children: Inline[][] }[] }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][] };

export class UnreadableMarkdown extends Error {
  constructor(
    readonly line: number,
    readonly content: string,
  ) {
    super(
      `line ${line} is not a construct the published document reader understands: ${JSON.stringify(
        content.slice(0, 80),
      )}. Add support for it rather than letting the page drop the line.`,
    );
    this.name = "UnreadableMarkdown";
  }
}

/**
 * Split a line into text, bold and inline code runs.
 *
 * Deliberately not recursive. Bold inside code or code inside bold does not appear in these documents, and
 * supporting it would mean a real parser. If it ever appears, this returns it as literal text, which is
 * visible and wrong rather than invisible and wrong.
 */
export function parseInline(source: string): Inline[] {
  const nodes: Inline[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let cursor = 0;

  for (let match = pattern.exec(source); match !== null; match = pattern.exec(source)) {
    if (match.index > cursor) {
      nodes.push({ kind: "text", value: source.slice(cursor, match.index) });
    }
    if (match[1] !== undefined) nodes.push({ kind: "strong", value: match[1] });
    else if (match[2] !== undefined) nodes.push({ kind: "code", value: match[2] });
    cursor = match.index + match[0].length;
  }

  if (cursor < source.length) nodes.push({ kind: "text", value: source.slice(cursor) });
  return nodes.length > 0 ? nodes : [{ kind: "text", value: "" }];
}

function splitRow(line: string): Inline[][] {
  return line
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => parseInline(cell.trim()));
}

const HEADING = /^(#{1,3}) +(.*)$/;
const BULLET = /^([-*]) +(.*)$/;
const NESTED_BULLET = /^ {1,4}[-*] +(.*)$/;
const ORDERED = /^\d+\. +(.*)$/;
const TABLE_SEPARATOR = /^\|[\s:|-]+\|$/;

export function parseDocument(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading !== null) {
      const hashes = heading[1] ?? "";
      blocks.push({
        kind: "heading",
        level: hashes.length as 1 | 2 | 3,
        text: parseInline(heading[2] ?? ""),
      });
      index += 1;
      continue;
    }

    if (line.startsWith("|")) {
      const head = splitRow(line);
      const separator = lines[index + 1] ?? "";
      if (!TABLE_SEPARATOR.test(separator.trim())) {
        throw new UnreadableMarkdown(index + 2, separator);
      }
      index += 2;
      const rows: Inline[][][] = [];
      while (index < lines.length && (lines[index] ?? "").startsWith("|")) {
        rows.push(splitRow(lines[index] ?? ""));
        index += 1;
      }
      blocks.push({ kind: "table", head, rows });
      continue;
    }

    const bullet = BULLET.exec(line);
    const ordered = ORDERED.exec(line);
    if (bullet !== null || ordered !== null) {
      const isOrdered = ordered !== null;
      const items: { text: Inline[]; children: Inline[][] }[] = [];

      while (index < lines.length) {
        const current = lines[index] ?? "";
        const nextBullet = isOrdered ? ORDERED.exec(current) : BULLET.exec(current);
        if (nextBullet !== null) {
          const text = isOrdered ? (nextBullet[1] ?? "") : (nextBullet[2] ?? "");
          items.push({ text: parseInline(text), children: [] });
          index += 1;
          continue;
        }
        const nested = NESTED_BULLET.exec(current);
        if (nested !== null && items.length > 0) {
          items[items.length - 1]?.children.push(parseInline(nested[1] ?? ""));
          index += 1;
          continue;
        }
        // A line indented under a bullet that is not itself a bullet continues the item's sentence.
        if (/^ {2,}\S/.test(current) && items.length > 0) {
          const last = items[items.length - 1];
          if (last !== undefined) {
            last.text = [...last.text, { kind: "text", value: ` ${current.trim()}` }];
          }
          index += 1;
          continue;
        }
        break;
      }
      blocks.push({ kind: "list", ordered: isOrdered, items });
      continue;
    }

    if (line.startsWith("#") || line.startsWith(">") || line.startsWith("```") || line.startsWith("<")) {
      throw new UnreadableMarkdown(index + 1, line);
    }

    // A paragraph runs until a blank line or the start of another construct.
    const paragraph: string[] = [];
    while (index < lines.length) {
      const current = lines[index] ?? "";
      if (
        current.trim() === "" ||
        current.startsWith("|") ||
        current.startsWith("#") ||
        BULLET.test(current) ||
        ORDERED.test(current)
      ) {
        break;
      }
      paragraph.push(current.trim());
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: parseInline(paragraph.join(" ")) });
  }

  return blocks;
}

/** The title is the single h1, which every published document has exactly one of. */
export function documentTitle(blocks: Block[]): string {
  const h1 = blocks.find((block) => block.kind === "heading" && block.level === 1);
  if (h1 === undefined || h1.kind !== "heading") {
    throw new Error("a published document needs exactly one h1 to use as its title");
  }
  return h1.text.map((node) => node.value).join("");
}
