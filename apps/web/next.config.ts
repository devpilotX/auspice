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

  // The Content Security Policy is set per request in src/middleware.ts rather than here, because the App
  // Router streams hydration data through inline scripts and those need a nonce. A static policy without one
  // serves correct HTML that renders nothing, which is a failure only a browser can see.
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
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ]);
  },
};

export default config;
