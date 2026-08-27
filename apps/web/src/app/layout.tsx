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
    default: "Auspice",
    template: "%s | Auspice",
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
                    letterSpacing: "0.18em",
                    color: "var(--text-primary)",
                  }}
                >
                  Auspice
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
                Auspice produces a probabilistic opinion with a disclosed methodology. It is not legal
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
            </div>
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
