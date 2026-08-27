/**
 * The published documents. Section 12 day 24.
 *
 * One route for three pages, because they are the same thing: a version controlled document in `docs/` that
 * the product commits to publicly. Reading the file at build time rather than restating it here means there
 * is one copy of every claim. A second copy of a methodology is a second methodology, and the two will
 * disagree eventually.
 *
 * `/method` was linked from the site header before this route existed and returned 404 on every page. That
 * is the reason this exists now rather than later.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublishedDocument } from "@/components/published-document";
import { Label, Rule } from "@/components/primitives";
import { documentTitle, parseDocument } from "@/lib/published-doc";

/** The three published documents, and the only three. `OPERATIONS.md` is internal and is not routed. */
const DOCUMENTS = {
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
      "Every source Auspice reads, how it is fetched, how often, and what happens when a source goes dark.",
  },
} as const;

type Slug = keyof typeof DOCUMENTS;

function isSlug(value: string): value is Slug {
  return Object.hasOwn(DOCUMENTS, value);
}

/**
 * Statically generate all three. They change when the repository changes, not when a request arrives.
 */
export function generateStaticParams(): { slug: Slug }[] {
  return (Object.keys(DOCUMENTS) as Slug[]).map((slug) => ({ slug }));
}

async function load(slug: Slug) {
  const entry = DOCUMENTS[slug];
  // Four levels up from apps/web/src/app to the repository root.
  const repoRoot = path.resolve(process.cwd(), "..", "..");
  const source = await readFile(path.join(repoRoot, "docs", entry.file), "utf8");
  const blocks = parseDocument(source);
  return { entry, blocks, title: documentTitle(blocks) };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  if (!isSlug(slug)) return {};
  const entry = DOCUMENTS[slug];
  const { title } = await load(slug);
  return {
    title,
    description: entry.description,
    alternates: { canonical: `/${slug}` },
  };
}

export default async function PublishedDocumentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  if (!isSlug(slug)) notFound();

  const { entry, blocks } = await load(slug);

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
