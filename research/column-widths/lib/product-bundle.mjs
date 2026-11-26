/**
 * Сборка продуктового модуля ширин в ESM для research-стендов (#489).
 *
 * Зачем бандл: `adaptive.mjs` и браузерный стенд меряют **продуктовую**
 * `computePreviewColumnWidths`, а не её пересказ. Vite собирает TS-модуль
 * (`frontend/src/features/spg/lib/previewColumnWidths.ts`) в один ESM без
 * внешних зависимостей; `@/…` — только `import type`, они стираются, но alias
 * задан, чтобы сборка не зависела от этой детали.
 *
 * Результат — `browser/.product-build/previewColumnWidths.mjs` (в `.gitignore`):
 * файл лежит внутри корня Vite-стенда, поэтому страница импортирует его
 * обычным относительным путём. `results/` не коммитится.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
export const researchRoot = path.resolve(here, "..");
export const repoRoot = path.resolve(researchRoot, "../..");
export const productBuildDir = path.join(researchRoot, "browser/.product-build");
export const productBundlePath = path.join(productBuildDir, "previewColumnWidths.mjs");

const productEntry = path.join(
  repoRoot,
  "frontend/src/features/spg/lib/previewColumnWidths.ts",
);

/** Собирает бандл (идемпотентно) и возвращает путь к нему. */
export async function buildProductBundle() {
  mkdirSync(productBuildDir, { recursive: true });
  await build({
    configFile: false,
    logLevel: "error",
    resolve: { alias: { "@": path.join(repoRoot, "frontend/src") } },
    build: {
      lib: {
        entry: productEntry,
        formats: ["es"],
        fileName: () => "previewColumnWidths.mjs",
      },
      outDir: productBuildDir,
      emptyOutDir: true,
      minify: false,
      target: "node20",
      write: true,
    },
  });
  return productBundlePath;
}

/** Собирает (если нужно) и импортирует продуктовый модуль. */
export async function loadProductBundle() {
  const file = await buildProductBundle();
  return import(`${pathToFileURL(file).href}?v=${Date.now()}`);
}
