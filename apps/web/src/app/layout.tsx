import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeProvider } from "@/components/theme";
import { THEME_COLOR } from "@/lib/theme-colors";
import "./globals.css";

/*
  Three families, each with one job.

  Geist Sans for interface. Geist Mono for every number, identifier and timestamp, with tabular figures
  so columns align when the page is printed into a credit memo. Newsreader for display headings and
  quoted evidence only, nowhere else.

  Loaded through next/font so they are self hosted and there is no third party font request, which keeps
  the content security policy in next.config.ts as tight as it is.
*/

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  display: "swap",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: {
    default: "Permission Bureau",
    template: "%s | Permission Bureau",
  },
  description:
    "A rating bureau for the right to build. Calibrated permission risk forecasts with a published accuracy record.",
  icons: {
    icon: [
      { url: "/brand/templum-favicon-16.svg", sizes: "16x16", type: "image/svg+xml" },
      { url: "/brand/templum-primary.svg", type: "image/svg+xml" },
    ],
    apple: "/brand/templum-app-icon.svg",
  },
  robots: {
    // The accuracy record and the jurisdiction profiles are the marketing, so they are indexed.
    // Section 10.4: "[County] data centre approval rate" is exactly what a developer searches.
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLOR.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLOR.dark },
  ],
};

const NAV = [
  { href: "/portfolio", label: "Portfolio" },
  { href: "/accuracy", label: "Accuracy" },
  { href: "/jurisdictions", label: "Coverage" },
  { href: "/method", label: "Method" },
  { href: "/neutrality", label: "Neutrality" },
];

/** Rendered from `docs/`, so the published claim and the enforced one cannot come apart. */
const FOOTER_LINKS = [
  { href: "/method", label: "Method" },
  { href: "/neutrality", label: "Neutrality" },
  { href: "/data-sources", label: "Data sources" },
  { href: "/terms", label: "Terms of use" },
  { href: "/privacy", label: "Privacy" },
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${newsreader.variable}`}
    >
      <body>
        <ThemeProvider>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:rounded-sm focus:px-3 focus:py-2"
            style={{ backgroundColor: "var(--bg-raised)", border: "1px solid var(--line-strong)" }}
          >
            Skip to content
          </a>

          <header
            data-no-print
            style={{ borderBottom: "1px solid var(--line-hairline)" }}
          >
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
              <Link href="/" className="flex items-center gap-3 rounded-sm">
                <Image
                  src="/brand/templum-primary.svg"
                  alt=""
                  width={22}
                  height={22}
                  className="dark:hidden"
                />
                <Image
                  src="/brand/templum-reversed.svg"
                  alt=""
                  width={22}
                  height={22}
                  className="hidden dark:block"
                />
                <span
                  className="uppercase"
                  style={{
                    fontSize: "var(--text-small)",
                    fontWeight: 600,
                    // 0.18em was tuned for a seven letter mark. At seventeen letters that tracking
                    // makes the wordmark wider than the navigation beside it, so it comes down rather
                    // than the name being abbreviated: an abbreviated brand in the header and a full
                    // one everywhere else reads as two products.
                    letterSpacing: "0.1em",
                    color: "var(--text-primary)",
                  }}
                >
                  Permission Bureau
                </span>
              </Link>

              <nav aria-label="Main" className="flex items-center gap-6">
                {NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="rounded-sm"
                    style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>

          <main id="main" className="mx-auto max-w-6xl px-6 py-12">
            {children}
          </main>

          <footer
            data-no-print
            className="mt-24"
            style={{ borderTop: "1px solid var(--line-hairline)" }}
          >
            <div className="mx-auto max-w-6xl px-6 py-8">
              <p
                className="max-w-2xl"
                style={{ fontSize: "var(--text-small)", color: "var(--text-secondary)" }}
              >
                Permission Bureau produces a probabilistic opinion with a disclosed methodology. It is not legal
                advice, not an appraisal and not a guarantee. We model published voting records and stated
                positions, never inferred motives, and we never predict how a named individual will vote.
              </p>
              <p
                className="mt-4"
                style={{ fontSize: "var(--text-tiny)", color: "var(--text-tertiary)" }}
              >
                The same data is available to developers, lenders, insurers, counties and community
                groups. The last two at no cost.
              </p>

              {/*
                The legal surfaces, in the footer rather than the header, because they are things a reader
                should be able to find rather than things the product is about. Each is rendered from a file
                in docs/, so what is published and what the build enforces cannot come apart.
              */}
              <nav aria-label="Legal and method" className="mt-6 flex flex-wrap gap-x-6 gap-y-2">
                {FOOTER_LINKS.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="font-mono uppercase"
                    style={{
                      fontSize: "var(--text-micro)",
                      letterSpacing: "0.12em",
                      color: "var(--text-tertiary)",
                      textDecoration: "none",
                    }}
                  >
                    {link.label}
                  </Link>
                ))}
              </nav>
            </div>
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
