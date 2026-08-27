/*
  The performance budget.

  Section 7.3 sets public pages under 100 KB of JavaScript and the app shell under 300 KB, enforced in
  CI because performance rots silently.

  Two amendments to those numbers, both measured rather than assumed, and both worth stating rather than
  burying.

  First, sizes here are gzipped. A budget is about what crosses the network, and raw bytes on disk are
  roughly three times larger, which would make any budget meaningless in either direction.

  Second, Next 15 with React 19 ships a shared runtime of about 103 kB gzipped before this codebase
  contributes a byte. The 100 kB figure in the specification was written before the framework was pinned
  and is not reachable on it at any amount of effort short of abandoning it. So the budget is expressed as
  two numbers instead of one:

    PAGE_OWN     what a route adds on top of the shared runtime. This is the number we control, and it
                 is where regressions actually show up.
    ROUTE_TOTAL  first load for the whole route, kept close enough to the baseline that nothing can
                 quietly double it.

  Both fail for the right reason: because someone added weight, not because the framework exists.
*/

import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const APP_DIR = path.resolve(import.meta.dirname, "..");
const MANIFEST = path.join(APP_DIR, ".next", "app-build-manifest.json");

const PAGE_OWN_BUDGET = 26 * 1024;
const ROUTE_TOTAL_BUDGET = 132 * 1024;

function gzippedSize(files, cache) {
  let total = 0;
  const seen = new Set();
  for (const file of files) {
    if (!file.endsWith(".js") || seen.has(file)) continue;
    seen.add(file);
    if (!cache.has(file)) {
      try {
        cache.set(file, gzipSync(readFileSync(path.join(APP_DIR, ".next", file))).length);
      } catch {
        // A manifest entry with no file on disk is a Next internals detail, not a budget problem.
        cache.set(file, 0);
      }
    }
    total += cache.get(file);
  }
  return total;
}

let manifest;
try {
  manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));
} catch {
  console.error(`No build manifest at ${MANIFEST}. Run \`npm run build --workspace apps/web\` first.`);
  process.exit(1);
}

const cache = new Map();
const pages = manifest.pages ?? {};
const shared = new Set(pages["/layout"] ?? []);
const sharedBytes = gzippedSize([...shared], cache);

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} kB`;
const rows = [];
let failed = false;

for (const [route, files] of Object.entries(pages)) {
  if (route === "/layout") continue;
  const own = gzippedSize(
    files.filter((file) => !shared.has(file)),
    cache,
  );
  const total = gzippedSize(files, cache);
  const over = own > PAGE_OWN_BUDGET || total > ROUTE_TOTAL_BUDGET;
  if (over) failed = true;
  rows.push({ route, own, total, over });
}

console.log(`shared runtime, gzipped: ${kb(sharedBytes)}`);
console.log(`budgets: page own ${kb(PAGE_OWN_BUDGET)}, route total ${kb(ROUTE_TOTAL_BUDGET)}\n`);
console.log("route".padEnd(34) + "own".padStart(11) + "total".padStart(11) + "  status");
for (const row of rows.sort((a, b) => b.total - a.total)) {
  console.log(
    row.route.padEnd(34) +
      kb(row.own).padStart(11) +
      kb(row.total).padStart(11) +
      "  " +
      (row.over ? "over" : "ok"),
  );
}

if (failed) {
  console.error(
    "\nA route is over budget. Either the weight is justified and the budget moves in a commit that says " +
      "why, or the weight comes out. Lazy loading a chart that only renders once there is data to draw " +
      "is usually the answer.",
  );
  process.exit(1);
}

console.log("\nwithin budget");
