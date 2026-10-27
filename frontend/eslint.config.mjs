import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import storybook from "eslint-plugin-storybook";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "public/mockServiceWorker.js",
    "storybook-static/**",
    "coverage/**",
    "test-results/**",
    "playwright-report/**",
    "blob-report/**",
  ]),
  {
    rules: {
      "no-restricted-imports": [
        "error",
        { patterns: [{ group: ["../*"], message: "Use the @/ alias instead." }] },
      ],
    },
  },
  ...storybook.configs["flat/recommended"],
  eslintConfigPrettier,
]);

export default eslintConfig;
