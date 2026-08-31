/*
  Dependency audit gate.

  `npm audit` is run in CI and this script decides whether the result blocks the build. It exists
  because the two useful behaviours are not the same thing: fail on anything new, and do not fail
  forever on something already assessed.

  Every entry in ALLOWED carries the advisory, why it does not apply here, and a review date. An
  allowlist without a reason is a mute button, and an allowlist without an expiry is permanent.
*/

import { execFileSync } from "node:child_process";
import process from "node:process";

/** @type {{ package: string, reason: string, reviewBy: string }[]} */
const ALLOWED = [
  // Empty, and that is the goal state rather than an oversight.
  //
  // This list previously held postcss and next. The four postcss advisories, one of them high, were
  // assessed as build time only and allowed, because the only fix npm offered was `npm audit fix
  // --force` to Next 16, a major upgrade. That assessment was sound and the conclusion was avoidable:
  // an `overrides` entry in the root package.json forces the patched postcss under the existing
  // framework, and `npm audit` then reports zero advisories rather than two allowed ones.
  //
  // The entries were removed rather than left in place. An allowlist entry for a fixed advisory is a
  // mute button for a problem that no longer exists, and it would hide the regression if the override
  // were ever dropped and the vulnerable version came back.
  //
  // Getting the override to apply took a clean install. `npm install` with an existing lock and
  // node_modules reports "up to date" and does not re-resolve, so the override appears to be ignored.
  // Removing both and reinstalling applies it. Worth knowing before concluding an override does not
  // work.
];

const BLOCKING = new Set(["critical", "high", "moderate"]);

// npm is a batch script on Windows. Node 24 refuses to spawn a .cmd without a shell, so the audit
// runs through the platform's own npm-cli.js instead, which works identically everywhere.
function audit() {
  const args = ["audit", "--json"];
  try {
    return JSON.parse(execFileSync("npm", args, { encoding: "utf8", shell: true }));
  } catch (error) {
    // npm audit exits non-zero when it finds anything, and still prints the report.
    if (error.stdout) return JSON.parse(error.stdout);
    throw error;
  }
}

const report = audit();
const vulnerabilities = Object.values(report.vulnerabilities ?? {});
const allowed = new Map(ALLOWED.map((entry) => [entry.package, entry]));

const today = new Date().toISOString().slice(0, 10);
const unexpected = [];
const expired = [];

for (const item of vulnerabilities) {
  if (!BLOCKING.has(item.severity)) continue;
  const exception = allowed.get(item.name);
  if (!exception) {
    unexpected.push(item);
    continue;
  }
  if (exception.reviewBy < today) expired.push({ item, exception });
}

if (unexpected.length === 0 && expired.length === 0) {
  console.log(
    `audit clean: ${vulnerabilities.length} advisories, ${ALLOWED.length} assessed and allowed`
  );
  for (const entry of ALLOWED) {
    console.log(`  allowed  ${entry.package}  review by ${entry.reviewBy}`);
  }
  process.exit(0);
}

for (const item of unexpected) {
  console.error(`\nnew ${item.severity} advisory in ${item.name}`);
  for (const via of item.via) {
    if (typeof via !== "string") console.error(`  ${via.title}`);
  }
  console.error(
    `  Assess it, then either upgrade or add it to ALLOWED in scripts/check-audit.mjs with a reason.`
  );
}

for (const { item, exception } of expired) {
  console.error(
    `\nthe exception for ${item.name} expired on ${exception.reviewBy}. Re-assess it or upgrade.`
  );
}

process.exit(1);
