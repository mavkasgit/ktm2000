/**
 * Адаптивная политика ширин предпросмотра (#489) — числа для решения.
 *
 * Считает **продуктовую** функцию `computePreviewColumnWidths`
 * (`frontend/src/features/spg/lib/previewColumnWidths.ts`) на тех же
 * синтетических профилях и сетке ширин, что бенч: `H_full`, `H_trunc`,
 * `Δ = H_full / H_trunc − 1`, выбранную политику (порог `θ = 0.05`) и долю
 * конфигураций в ветке `full-text`.
 *
 * Зачем бандл, а не копия формул: политика — свойство продуктовой реализации
 * вместе с её аллокатором. Копия высоты «на глаз» доказывала бы модель, а не
 * продукт. Поэтому модуль собирается Vite'ом в `browser/.product-build`
 * (каталог в `.gitignore`) и импортируется как обычный ESM; шрифт и
 * `pretext` — те же, что в бенче и браузерном стенде.
 *
 * Оговорки, которые нельзя прятать:
 *
 * - «Ошибки» меряются весом 400 (`11px "Inter"` как в research `cssFont`), а в
 *   продукте они `font-medium`; H4 на фактическом CSS — `browser:test`. На
 *   высоту это влияет только через ширину текста, не через `line-height`.
 * - Профили — синтетика (`lib/generator.mjs`), а не реальные листы ОСВ.
 *
 * Запуск:
 *
 *   node research/column-widths/adaptive.mjs
 *   node research/column-widths/adaptive.mjs --rows=1000 --seeds=3
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { buildColumns } from "./lib/columns.mjs";
import { generateSheet } from "./lib/generator.mjs";
import { createMeasurer } from "./lib/measurers.mjs";
import { loadProductBundle } from "./lib/product-bundle.mjs";
import { pillsWidth } from "./lib/text.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");

/** Порог из тикета #489 и спеки §4/§15 — зафиксирован до прогона. */
const THRESHOLD = 0.05;

const argValue = (name, fallback) => {
  const prefix = `--${name}=`;
  const found = process.argv.find((argument) => argument.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
};

const ROWS = Number(argValue("rows", 500));
const SEEDS = Number(argValue("seeds", 1));
const WIDTHS = (argValue("widths", "1180,1280,1400,1500,1600,1920") ?? "")
  .split(",")
  .map(Number);
const COLUMN_COUNT = 11;

const PROFILES = [
  "realistic",
  "long-tail",
  "outlier",
  "all-short",
  "mono",
  "mixed",
  "empty",
];

/**
 * Продуктовые метрики строки: `ImportRemaindersDialog` / `previewColumnWidths`.
 * Источник — CSS предпросмотра (`text-[11px]`, `leading-snug`, `py-0.5`).
 */
const FONTS = {
  name: { family: '"Inter"', sizePx: 11, weight: 400, lineHeightPx: 16.5 },
  errors: { family: '"Inter"', sizePx: 11, weight: 500, lineHeightPx: 15.125 },
  pill: { family: '"Inter"', sizePx: 10, weight: 500, lineHeightPx: 20 },
};

async function bundleProduct() {
  return loadProductBundle();
}

/** Общий интерфейс research-измерителя → `PreviewTextMeasurer` продукта. */
function toProductMeasurer(base) {
  return {
    prepare: (text) => base.prepare(text, "sans"),
    naturalWidth: (prepared) => base.naturalWidth(prepared),
    maxWordWidth: (prepared) => base.maxWordWidth(prepared),
    lineCount: (prepared, usableWidth) => base.lineCount(prepared, usableWidth),
  };
}

const round = (value, digits = 2) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

async function main() {
  const { computePreviewColumnWidths } = await bundleProduct();
  const base = await createMeasurer("pretext");
  const measurer = toProductMeasurer(base);
  const columns = buildColumns(COLUMN_COUNT);

  const cells = [];
  for (const profile of PROFILES) {
    for (const width of WIDTHS) {
      for (let seed = 1; seed <= SEEDS; seed += 1) {
        const sheet = generateSheet({ profile, rows: ROWS, columns, seed });
        const rows = sheet.rows.map((row, index) => ({
          rowKey: index + 1,
          nameText: String(row.values.source_name ?? ""),
          errorsText: String(row.values.errors ?? ""),
          errorsWraps: true,
          pillWidth: pillsWidth(row.values.operations, "sans"),
        }));
        base.clearCache?.();
        const result = computePreviewColumnWidths({
          containerWidth: width,
          rows,
          measurer,
          fonts: FONTS,
        });
        cells.push({
          profile,
          width,
          seed,
          policy: result.policy,
          fullTextHeightPx: result.fullTextHeightPx,
          baselineHeightPx: result.baselineHeightPx,
          heightDeltaPct: round((result.fullTextHeightPx / result.baselineHeightPx - 1) * 100, 2),
          thresholdPct: THRESHOLD * 100,
          rule: `H_full ≤ H_trunc × ${1 + THRESHOLD}`,
          nameWidthPx: result.nameWidthPx,
          errorsWidthPx: result.errorsWidthPx,
          pillsWidthPx: result.pillsFloorPx,
          textTruncatedShare: round(result.textTruncatedCells / ROWS, 4),
          overflow: result.overflow,
        });
      }
    }
  }

  const byProfile = PROFILES.map((profile) => {
    const own = cells.filter((cell) => cell.profile === profile);
    const full = own.filter((cell) => cell.policy === "full-text").length;
    return {
      profile,
      cells: own.length,
      fullText: full,
      fullTextShare: round(full / own.length, 3),
      meanDeltaPct: round(
        own.reduce((sum, cell) => sum + cell.heightDeltaPct, 0) / own.length,
        2,
      ),
    };
  });
  const fullTextShare = round(
    cells.filter((cell) => cell.policy === "full-text").length / cells.length,
    3,
  );

  // Markdown: профиль × W, средняя Δ по seed'ам (при seeds=1 — одна строка).
  const header = `| Профиль | ${WIDTHS.map((width) => `W=${width}`).join(" | ")} |`;
  const divider = `|---|${WIDTHS.map(() => "---:").join("|")}|`;
  const lines = [header, divider];
  for (const profile of PROFILES) {
    const values = WIDTHS.map((width) => {
      const own = cells.filter((cell) => cell.profile === profile && cell.width === width);
      const full = own.filter((cell) => cell.policy === "full-text").length;
      const meanDelta = round(
        own.reduce((sum, cell) => sum + cell.heightDeltaPct, 0) / own.length,
        1,
      );
      return `${meanDelta >= 0 ? "+" : ""}${meanDelta}% → ${full}/${own.length} full-text`;
    });
    lines.push(`| \`${profile}\` | ${values.join(" | ")} |`);
  }

  mkdirSync(path.join(here, "results"), { recursive: true });
  writeFileSync(
    path.join(here, "results/adaptive.json"),
    `${JSON.stringify(
      {
        meta: {
          ticket: 489,
          generatedAt: new Date().toISOString(),
          rows: ROWS,
          widths: WIDTHS,
          profiles: PROFILES,
          seeds: SEEDS,
          threshold: THRESHOLD,
          measurer: "pretext",
          fonts: FONTS,
          productModule: "frontend/src/features/spg/lib/previewColumnWidths.ts",
          note: "H_trunc — текущий фикс: доли remainderPreviewColumns, наименование в одну строку",
        },
        summary: { cells: cells.length, fullTextShare, byProfile },
        cells,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  console.log(`[adaptive] rows=${ROWS} seeds=${SEEDS} cells=${cells.length} θ=${THRESHOLD}`);
  console.log(lines.join("\n"));
  console.log(
    `[adaptive] full-text: ${(fullTextShare * 100).toFixed(1)}% конфигураций ` +
      `(${byProfile.map((entry) => `${entry.profile} ${Math.round(entry.fullTextShare * 100)}%`).join(", ")})`,
  );
  console.log(`[adaptive] JSON: ${path.relative(repoRoot, path.join(here, "results/adaptive.json"))}`);
}

await main();
