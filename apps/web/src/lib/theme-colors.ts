/**
 * The two token values that cannot be read from CSS.
 *
 * Everything in this product reads colour through a CSS custom property in src/styles/tokens.css, and the
 * lint rule forbids a hex literal anywhere else. Two places genuinely cannot: the `theme-color` meta tag,
 * which the browser reads before any stylesheet is parsed, and anything generating an image outside the
 * document.
 *
 * So the values live here, once, with a note that they mirror `--color-paper` in each theme. If they ever
 * disagree with the token file, the browser chrome will not match the page, which is visible immediately
 * and is the cheapest possible way to catch the drift.
 */

export const THEME_COLOR = {
  /** mirrors --color-paper in :root */
  light: "#FBFBF9",
  /** mirrors --color-paper in .dark */
  dark: "#0E1013",
} as const;
