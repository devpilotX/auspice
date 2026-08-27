import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";

/*
  Flat config, with the Next rules pulled in as a plugin rather than through eslint-config-next.

  eslint-config-next still routes through @rushstack/eslint-patch, which exists to make legacy
  eslintrc resolution work and refuses to load under ESLint 9 flat config. Using
  @next/eslint-plugin-next directly gets the same rules with none of the patching.

  Two project rules beyond the recommended sets, both deliberate.

  `any` is an error rather than a warning. The build specification is explicit: if you reach for `any`,
  the type model is wrong. A warning gets scrolled past.

  Hardcoded colours are an error outside the token file. Every token lives in src/styles/tokens.css, and
  the fastest way to lose a design system is one component that just needed a slightly different grey.
*/

export default tseslint.config(
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      "next-env.d.ts",
      // MapLibre's worker and its shared chunk, copied verbatim by scripts/copy-maplibre-worker.mjs.
      // Vendor code, not ours, and 478 kB of it.
      "public/maplibre/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    plugins: { "@next/next": nextPlugin },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
  {
    languageOptions: {
      parserOptions: {
        projectService: {
          // The build scripts are not part of the app's TypeScript project, and the project service
          // needs to be told that rather than failing to resolve them.
          allowDefaultProject: ["scripts/*.mjs", "*.config.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/restrict-template-expressions": [
        "error",
        { allowNumber: true, allowBoolean: false, allowNullish: false },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6,8})$/]",
          message:
            "No hardcoded colours. Add a token in src/styles/tokens.css and reference it. The brand " +
            "SVGs under public/brand are standalone files and are not linted.",
        },
      ],
    },
  },
  {
    // Build scripts are plain Node modules with no TypeScript project behind them.
    files: ["scripts/**/*.mjs", "*.config.mjs"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      globals: { console: "readonly", process: "readonly" },
    },
  },
  {
    // The one file allowed to name a colour. See its docstring: the theme-color meta tag is read by
    // the browser before any stylesheet is parsed, so it cannot come from a CSS custom property.
    files: ["src/lib/theme-colors.ts"],
    rules: { "no-restricted-syntax": "off" },
  },
);
