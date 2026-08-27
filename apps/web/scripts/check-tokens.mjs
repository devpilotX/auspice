/**
 * Fail if any `var(--token)` reference names a token that does not exist.
 *
 * Three did. `--bg-base`, `--text-title` and `--text-heading` were all invented while writing new screens,
 * and CSS resolves an undefined custom property to nothing without complaint: the form fields lost their
 * background and two headings lost their size, and the pages still rendered and still passed every test.
 *
 * The map is what exposed it, because a canvas cannot use a CSS variable. It reads the tokens through
 * `getComputedStyle`, got an empty string, and refused to draw rather than picking a colour nobody chose.
 * That refusal was the only signal, and it was luck that the map needed one of the three.
 *
 * This is the general form of that check. Every token referenced anywhere under `src/` has to be defined in
 * `tokens.css`, or the build fails naming the file and the token.
 */

import { readFileSync } from "node:fs";
import { globSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");
const TOKENS = path.join(ROOT, "src", "styles", "tokens.css");

/** Definitions look like `--name:` at the start of a declaration. */
function definedTokens() {
  const source = readFileSync(TOKENS, "utf8");
  const names = new Set();
  for (const match of source.matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
    names.add(match[1]);
  }
  return names;
}

/**
 * Tokens Tailwind generates rather than tokens we write.
 *
 * Tailwind v4 turns a `--text-body` entry in `@theme` into utility classes and also emits the paired
 * `--text-body--line-height` and `--text-body--letter-spacing` when they are declared. Those pairs are
 * declared here, so they are found by the definition scan and need no exception. Nothing else is exempt,
 * which is the point: an exception list is where this check goes to die.
 */
const EXEMPT = new Set();

const defined = definedTokens();
if (defined.size < 20) {
  process.stderr.write(`only ${defined.size} tokens found in tokens.css, which cannot be right\n`);
  process.exit(1);
}

const problems = [];
const files = globSync("src/**/*.{ts,tsx,css}", { cwd: ROOT });

for (const relative of files) {
  if (relative.replaceAll("\\", "/").endsWith("styles/tokens.css")) continue;
  const source = readFileSync(path.join(ROOT, relative), "utf8");
  const lines = source.split("\n");

  lines.forEach((line, index) => {
    for (const match of line.matchAll(/var\(\s*(--[a-z0-9-]+)/gi)) {
      const token = match[1];
      if (!defined.has(token) && !EXEMPT.has(token)) {
        problems.push({ file: relative, line: index + 1, token });
      }
    }
  });
}

if (problems.length > 0) {
  process.stderr.write(
    `${problems.length} reference${problems.length === 1 ? "" : "s"} to a token that does not exist ` +
      `in src/styles/tokens.css.\n\n` +
      `CSS resolves an undefined custom property to nothing, so this renders as a missing colour or a\n` +
      `default font size and passes every other check.\n\n`,
  );
  for (const problem of problems) {
    process.stderr.write(`  ${problem.file}:${problem.line}  ${problem.token}\n`);
  }
  process.stderr.write("\nAdd the token to tokens.css, or use the one that exists.\n");
  process.exit(1);
}

process.stdout.write(
  `every token reference resolves: ${defined.size} defined, ${files.length} files checked\n`,
);
