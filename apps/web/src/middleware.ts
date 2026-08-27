import { type NextRequest, NextResponse } from "next/server";

import { apiConnectSrc } from "@/lib/api-origin";

/*
  Content Security Policy.

  This file records two bugs, because the second one was hiding behind the fix for the first.

  The policy started as a static header in next.config.ts with `script-src 'self'`, which looks correct and
  is not: the App Router streams hydration data through inline scripts, and a policy with no nonce and no
  unsafe-inline blocks them. Pages served correct HTML and rendered nothing, because React received no
  hydration payload and discarded the server tree. The visual suite caught it by finding zero h1 elements on
  a page that plainly has one.

  The fix was a per request nonce with 'strict-dynamic'. That made the h1 appear, so it looked done. It was
  not. Nothing on the site hydrated, and no test noticed because every page until the portfolio screen was a
  server component displaying data, and server rendered HTML does not need JavaScript to look right. The
  first interactive page exposed it: the button was present, enabled, and did nothing at all.

  Two facts collide. Every route here is prerendered at build time, which the build output labels Static, so
  there is no request in flight when the HTML is generated and nothing to read a per request nonce from.
  Next stamps a nonce onto its script tags only when it renders on demand. Separately, 'strict-dynamic'
  instructs the browser to ignore 'self' and every other host expression, trusting only nonces and hashes.
  Together they blocked all twenty script tags on the page: the header advertised a nonce, the HTML carried
  none, and 'self' had been switched off.

  So a nonce cannot work here without making every page dynamic, and that is the wrong trade for a set of
  public pages whose whole job is to be fast and cacheable. The policy below drops both the nonce and
  'strict-dynamic' and allows 'self' for script sources and unsafe-inline for the hydration payload.

  What that costs, stated plainly: CSP no longer protects against an injected inline script. What it still
  buys is worth keeping, and is the reason this is not simply deleted: no third party script origin can
  load, eval is blocked in production, object-src is none, the site cannot be framed, base-uri and
  form-action are pinned to self, and connect-src names the one API origin. The residual risk is bounded by
  the fact that nothing here renders user supplied markup and every API response passes a Zod schema before
  it reaches a component.

  If a route ever needs the stronger policy, the way to get it is to render that route on demand and give it
  a nonce, not to reintroduce 'strict-dynamic' across statically generated pages.

  `style-src` allows unsafe-inline for a different and deliberate reason. Components read design tokens
  through the style attribute rather than through generated class names, which keeps every colour traceable
  to a token. A style injection is a defacement risk rather than a code execution one.
*/

const PUBLIC_FILE = /\.(svg|png|ico|json|txt|xml|webmanifest)$/;

export function middleware(request: NextRequest) {
  // Static assets need no policy.
  if (PUBLIC_FILE.test(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const isDevelopment = process.env.NODE_ENV === "development";
  // Read through the same helper the client uses, so the policy cannot name a different origin than the
  // code calls. They were separate expressions once and disagreed, and the browser blocked every request.
  const apiOrigin = apiConnectSrc();

  const policy = [
    "default-src 'self'",
    // No 'strict-dynamic'. It would switch off 'self' and block every chunk, which is exactly the bug
    // documented above. unsafe-eval is for the dev server's fast refresh and cannot reach production.
    `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    // MapLibre decodes tiles in a web worker, which it constructs from a blob URL. Without this the map
    // renders nothing and the console says the worker was blocked. Restricted to blob and self rather than
    // opened to any origin: a worker from a third party host would be arbitrary code execution.
    "worker-src 'self' blob:",
    "child-src 'self' blob:",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "upgrade-insecure-requests",
  ].join("; ");

  const response = NextResponse.next();
  response.headers.set("content-security-policy", policy);
  return response;
}

export const config = {
  matcher: [
    // Everything except Next's own static output, which is immutable and needs no policy.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
