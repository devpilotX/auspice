import type { NextConfig } from "next";

/*
  Two settings here are decisions rather than defaults.

  Image optimisation is off. Every visual in this product is hand written SVG or a token driven CSS
  rule, so the optimiser has nothing to do, and turning it off removes sharp and libvips from the
  runtime surface entirely. That is a smaller attack surface for no loss.

  The security headers are set here rather than at the edge so they hold in local development too. A
  header that only exists in production is a header nobody has tested.
*/

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  images: {
    unoptimized: true,
  },

  typescript: {
    // A type error must fail the build. The whole point of strict mode is that it is not advisory.
    ignoreBuildErrors: false,
  },

  eslint: {
    ignoreDuringBuilds: false,
  },

  // Next's config type declares headers() as returning a promise. Nothing here needs to await, so the
  // promise is produced directly rather than by marking the function async for no reason.
  headers() {
    return Promise.resolve([
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
          {
            // No inline scripts, no eval, no third party anything. The product loads its own fonts
            // through next/font, so there is no font or style CDN to allow either.
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self'" + (process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""),
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              "font-src 'self'",
              `connect-src 'self' ${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}`.trim(),
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join("; "),
          },
        ],
      },
    ]);
  },
};

export default config;
