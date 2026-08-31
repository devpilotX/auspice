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

/** Locate the openapi-typescript CLI wherever npm actually installed it.
 *
 * Two candidate roots, because npm hoists to the workspace root when it can and nests under the
 * workspace that depends on the package when it cannot, and which one happens depends on the rest of the
 * tree rather than on anything declared here. This previously joined ROOT with node_modules and worked
 * only while the package happened to be hoisted; adding an `overrides` entry to package.json regenerated
 * the lock, npm nested it under packages/shared-types, and the script began failing with "Cannot find
 * module". Caught by the Gate 6 fresh clone run and not by any local run, because the local tree still
 * had the old layout.
 *
 * The path comes from the package's own `bin` field rather than from Node's subpath resolver, which
 * refuses `openapi-typescript/bin/cli.js`: the package declares an `exports` map that does not include
 * the bin directory, so a resolve call reports a file that does not exist while the real one sits next to
 * it. Reading the manifest asks the package where its entry point is instead of guessing.
 */
function resolveCli() {
  const candidates = [
    join(ROOT, "node_modules", "openapi-typescript"),
    join(ROOT, "packages", "shared-types", "node_modules", "openapi-typescript"),
  ];
  const tried = [];
  for (const directory of candidates) {
    const manifest = read(join(directory, "package.json"));
    if (manifest === null) {
      tried.push(`${directory}: not installed here`);
      continue;
    }
    const declared = JSON.parse(manifest).bin;
    const entry = typeof declared === "string" ? declared : declared?.["openapi-typescript"];
    if (!entry) {
      tried.push(`${directory}: installed and declares no bin`);
      continue;
    }
    const cli = join(directory, entry);
    if (read(cli) === null) {
      tried.push(`${directory}: declares bin ${entry} and the file is absent`);
      continue;
    }
    return cli;
  }
  fail(
    "could not locate the openapi-typescript CLI. Tried:\n  " + tried.join("\n  "),
  );
}

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
  //
  // Resolved rather than constructed. This previously joined ROOT with node_modules and worked only
  // while npm happened to hoist openapi-typescript to the workspace root. Adding an `overrides` entry to
  // package.json regenerated the lock, npm nested the package under packages/shared-types instead, and
  // this script started failing with "Cannot find module". Caught by the Gate 6 fresh clone run and not
  // by any local run, because the local tree still had the old hoisted layout.
  //
  // createRequire resolves the package the way an import would, from wherever it actually is.
  const cli = resolveCli();
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
