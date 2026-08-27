import { type NextRequest, NextResponse } from "next/server";

/*
  Content Security Policy, with a per request nonce.

  This exists because of a real bug. The policy was originally set as a static header in next.config.ts with
  `script-src 'self'`, which looks correct and is not: the App Router streams hydration data through inline
  scripts, and a policy with no nonce and no unsafe-inline blocks them. The pages then served correct HTML
  and rendered nothing, because React received no hydration payload and discarded the server tree.

  It was caught by the visual regression suite, which found zero h1 elements on a page that plainly has one.
  Worth recording, because the failure mode is invisible to a curl and invisible to a build: the HTML is
  right, the status is 200, and only a browser sees the blank page.

  The fix is a nonce generated per request. Next reads the nonce out of the request's own CSP header and
  stamps it onto every script it emits, so inline hydration works and nothing else inline does.

  Two remaining relaxations, both named rather than quietly included:

  `style-src` allows unsafe-inline. This project sets a great many inline styles, because components read
  design tokens through the style attribute rather than through generated class names, and that is a
  deliberate choice: it keeps every colour traceable to a token. A style injection is a defacement risk
  rather than a code execution risk, and the tradeoff is stated here rather than assumed.

  In development, `script-src` allows unsafe-eval, because the dev server's fast refresh needs it. It is
  conditional on NODE_ENV so it cannot reach production.
*/

const PUBLIC_FILE = /\.(svg|png|ico|json|txt|xml|webmanifest)$/;

export function middleware(request: NextRequest) {
  // Static assets need no policy and generating a nonce for each one is wasted work.
  if (PUBLIC_FILE.test(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDevelopment = process.env.NODE_ENV === "development";
  const apiOrigin = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "upgrade-insecure-requests",
  ].join("; ");

  const headers = new Headers(request.headers);
  // Next reads the nonce from this header and stamps it onto the scripts it emits.
  headers.set("x-nonce", nonce);
  headers.set("content-security-policy", policy);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("content-security-policy", policy);
  return response;
}

export const config = {
  matcher: [
    // Everything except Next's own static output, which is immutable and needs no policy.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
