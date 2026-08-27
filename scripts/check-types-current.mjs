/**
 * Fail if the committed OpenAPI document or the generated types are stale.
 *
 * The API is the source of truth and the TypeScript is derived from it, which is only true if the
 * derivation is checked. Without this, a route can change its response shape and the web application
 * keeps compiling against the old one, so the mismatch surfaces at runtime as an undefined field rather
 * than at build time as a type error.
 *
 * Regenerates into a temporary location and compares bytes. Exits non zero with the command to run.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import process from "node:process";

const ROOT = resolve(import.meta.dirname, "..");
const DOCUMENT = join(ROOT, "packages", "shared-types", "openapi.json");
const GENERATED = join(ROOT, "packages", "shared-types", "src", "generated", "api.ts");

const REGENERATE = [
  "uv run python tools/export_openapi.py",
  "npm run generate --workspace packages/shared-types",
].join(" && ");

function read(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function fail(message) {
  process.stderr.write(`${message}\n\nRun:\n  ${REGENERATE}\n`);
  process.exit(1);
}

const committedDocument = read(DOCUMENT);
if (committedDocument === null) {
  fail(`${DOCUMENT} does not exist, so the generated types describe nothing.`);
}

const committedTypes = read(GENERATED);
if (committedTypes === null) {
  fail(`${GENERATED} does not exist.`);
}

const scratch = mkdtempSync(join(tmpdir(), "auspice-openapi-"));
try {
  // Regenerate into scratch, never over the committed file. A check that repairs what it is checking
  // reports a failure against a working tree it has already changed, which makes the failure impossible
  // to reproduce and hides the drift from whoever reads the log.
  const scratchDocument = join(scratch, "openapi.json");
  execFileSync("uv", ["run", "python", "tools/export_openapi.py", "--out", scratchDocument], {
    cwd: ROOT,
    stdio: "pipe",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });

  if (read(scratchDocument) !== committedDocument) {
    fail("packages/shared-types/openapi.json is stale: the API describes itself differently now.");
  }

  const scratchTypes = join(scratch, "api.ts");
  // Run the CLI's JavaScript entry point with this Node binary. Two problems avoided: passing arguments
  // through a shell concatenates rather than escapes them, and Node refuses to spawn a .cmd shim without
  // one, so the .bin wrapper fails with EINVAL on Windows.
  const cli = join(ROOT, "node_modules", "openapi-typescript", "bin", "cli.js");
  execFileSync(process.execPath, [cli, DOCUMENT, "-o", scratchTypes], {
    cwd: ROOT,
    stdio: "pipe",
  });

  if (read(scratchTypes) !== committedTypes) {
    fail("packages/shared-types/src/generated/api.ts is stale relative to openapi.json.");
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

process.stdout.write("openapi document and generated types are current\n");
