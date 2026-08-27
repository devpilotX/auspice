/**
 * The published documents. Section 12 day 24.
 *
 * `docs/METHODOLOGY.md`, `docs/NEUTRALITY.md` and `docs/DATA_SOURCES.md` are the source of truth for what
 * this product claims about itself. These pages render those files rather than restating them, because a
 * second copy of a methodology is a second methodology and the two will disagree eventually.
 *
 * The shared work lives here and each route is three lines, rather than one `[slug]` route at the root of
 * the app. A root level dynamic segment would catch every URL that does not match a static route, which is
 * a wide net to cast for three known pages.
 *
 * `/method` was linked from the site header before any of this existed and returned 404 on every page.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";

import type { Metadata } from "next";

import { PublishedDocument } from "@/components/published-document";
import { Label, Rule } from "@/components/primitives";
import { documentTitle, parseDocument } from "@/lib/published-doc";

export const DOCUMENTS = {
  method: {
    file: "METHODOLOGY.md",
    label: "methodology",
    description:
      "How Auspice produces a probability, what it measures itself against, and when it refuses to answer.",
  },
  neutrality: {
    file: "NEUTRALITY.md",
    label: "neutrality",
    description:
      "Who Auspice works for, what it will not do, and how a rating bureau stays usable by both sides of a deal.",
  },
  "data-sources": {
    file: "DATA_SOURCES.md",
    label: "data sources",
    description:
      "Every source Auspice reads, how often it is fetched, and what happens when a source goes dark.",
  },
  terms: {
    file: "TERMS.md",
    label: "terms of use",
    description:
      "What Auspice sells, what a probability does and does not mean, and what it will not stand behind.",
  },
  privacy: {
    file: "PRIVACY.md",
    label: "privacy",
    description:
      "What the site collects, what the API receives, what is kept, and what a published score makes public.",
  },
} as const;

export type PublishedSlug = keyof typeof DOCUMENTS;

/** Read and parse one document. Runs at build time, so a malformed document fails the build. */
export async function loadPublished(slug: PublishedSlug) {
  const entry = DOCUMENTS[slug];
  // The web app runs with its own directory as cwd, and docs/ lives at the repository root.
  const repoRoot = path.resolve(process.cwd(), "..", "..");
  const source = await readFile(path.join(repoRoot, "docs", entry.file), "utf8");
  const blocks = parseDocument(source);
  return { entry, blocks, title: documentTitle(blocks) };
}

export async function publishedMetadata(slug: PublishedSlug): Promise<Metadata> {
  const { entry, title } = await loadPublished(slug);
  return {
    title,
    description: entry.description,
    alternates: { canonical: `/${slug}` },
  };
}

export async function PublishedPage({ slug }: { slug: PublishedSlug }) {
  const { entry, blocks } = await loadPublished(slug);

  return (
    <main id="main" className="mx-auto max-w-5xl px-6 py-12">
      <Label>{entry.label}</Label>
      <div className="mt-2">
        <PublishedDocument blocks={blocks} />
      </div>

      <Rule className="mt-12" strong />
      <p
        className="mt-4 max-w-2xl"
        style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
      >
        This page is rendered from <code className="font-mono">docs/{entry.file}</code> in the
        repository. It is the document itself rather than a summary of it, so what is published here and
        what the build enforces cannot come apart.
      </p>
    </main>
  );
}
