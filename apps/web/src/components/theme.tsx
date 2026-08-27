"use client";

import { ThemeProvider as NextThemes } from "next-themes";
import type { ReactNode } from "react";

/**
 * Dark mode as a real second theme.
 *
 * next-themes only toggles the `dark` class. The values behind it are a separate set of tokens in
 * tokens.css with their own greys and a brass that lifts to C99A3C for contrast, rather than a filter
 * inversion. Inverting would give a brass that reads as mustard and a paper that reads as blue.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemes attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
      {children}
    </NextThemes>
  );
}
