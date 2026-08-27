/**
 * Copy MapLibre's worker and its shared chunk into `public/maplibre/`.
 *
 * MapLibre v6 needs `setWorkerUrl()` under any bundler, and the obvious way to satisfy it,
 * `new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url)`, does not work. Webpack recognises
 * that form and emits the worker as a hashed asset, but the worker is 18 kB of glue that imports 478 kB from
 * `./maplibre-gl-shared.mjs` beside it, and webpack does not follow that import or emit the sibling. The
 * worker then starts, requests a file that is not there, and stops.
 *
 * That failure is silent in every channel worth watching. No console error, no page error, no rejected
 * promise. The map constructs, the canvas appears, WebGL initialises, the source and all four layers are
 * present, the zoom and centre are correct, and `isStyleLoaded()` simply returns false forever, so not one
 * tile is requested. It was found by listening for failed requests and seeing a 404 for a file nothing in
 * the application had asked for.
 *
 * Copying both files to a fixed path fixes it properly: the worker's relative import resolves to its sibling
 * because they sit in the same directory, and the URL is stable rather than content hashed, so
 * `setWorkerUrl` can name it as a literal.
 *
 * The copies are generated, so they are gitignored and rebuilt by `prebuild`. If the version in
 * package.json changes and this does not run, the check below fails rather than shipping a stale worker
 * against a new library.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");
const REPO_ROOT = path.resolve(ROOT, "..", "..");
const SOURCE = path.join(REPO_ROOT, "node_modules", "maplibre-gl", "dist");
const DESTINATION = path.join(ROOT, "public", "maplibre");

/** Both files, because the first one alone is useless. */
const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

if (!existsSync(SOURCE)) {
  fail(`maplibre-gl is not installed at ${SOURCE}. Run npm install.`);
}

mkdirSync(DESTINATION, { recursive: true });

let copied = 0;
for (const name of FILES) {
  const from = path.join(SOURCE, name);
  if (!existsSync(from)) {
    fail(
      `${name} is not in maplibre-gl/dist. The package layout changed, which means the worker setup in ` +
        `src/components/coverage-map.tsx needs revisiting rather than patching around.`,
    );
  }
  const to = path.join(DESTINATION, name);
  const stale =
    !existsSync(to) || statSync(from).size !== statSync(to).size;
  if (stale) {
    copyFileSync(from, to);
    copied += 1;
  }
}

// The worker is only useful if its relative import can resolve beside it. Assert the specifier rather than
// assume it, so a future version that inlines or renames the shared chunk fails here.
const worker = readFileSync(path.join(DESTINATION, "maplibre-gl-worker.mjs"), "utf8");
if (!worker.includes("./maplibre-gl-shared.mjs")) {
  fail(
    "the worker no longer imports ./maplibre-gl-shared.mjs. Check what it needs now before trusting the " +
      "copy in public/maplibre.",
  );
}

const version = JSON.parse(
  readFileSync(path.join(REPO_ROOT, "node_modules", "maplibre-gl", "package.json"), "utf8"),
).version;

process.stdout.write(
  `maplibre worker ready: ${FILES.length} files at public/maplibre, ${copied} refreshed, v${version}\n`,
);
