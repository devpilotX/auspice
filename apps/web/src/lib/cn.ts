import clsx, { type ClassValue } from "clsx";

/**
 * Class name joiner.
 *
 * Deliberately not tailwind-merge. This product has no variant explosion to deduplicate: components
 * take structural props and read tokens through CSS custom properties, so conflicting utility classes
 * are a symptom rather than a thing to paper over.
 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}
