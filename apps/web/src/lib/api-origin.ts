/**
 * Where the API lives.
 *
 * One module because two copies of this value disagreed and broke the product. `src/lib/api.ts` defaulted to
 * `http://127.0.0.1:8000` when `NEXT_PUBLIC_API_BASE_URL` was unset, while the middleware built
 * `connect-src` from the same variable and, finding it empty, emitted `connect-src 'self'`. The browser then
 * blocked every request the client code was written to make. Nothing in the build or the type checker can
 * see that, because the two values are correct in isolation and only wrong together.
 *
 * Importing this from both means the policy cannot name a different origin than the code calls.
 */

/** Used when the environment does not say. Matches the port `uv run uvicorn` binds by default. */
export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  return configured !== undefined && configured !== "" ? configured : DEFAULT_API_BASE_URL;
}

/**
 * The origin to name in `connect-src`.
 *
 * Returns the origin rather than the full URL, because CSP matches on origin and a trailing path would make
 * the directive silently stricter than intended. A value that does not parse yields an empty string, which
 * leaves the policy at `'self'`: a malformed configuration should fail closed and be visible in the browser
 * console, not open a hole.
 */
export function apiConnectSrc(): string {
  try {
    return new URL(apiBaseUrl()).origin;
  } catch {
    return "";
  }
}
