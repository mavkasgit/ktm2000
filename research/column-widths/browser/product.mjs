/**
 * H4 на фактическом CSS предпросмотра (#483).
 *
 * Стенд H4 (#479) проверял контракт исследования: `11px "Inter"`, вес 400,
 * `line-height: 20px`, `overflow-wrap: normal`. Продукт живёт на другом:
 *
 * - системный стек `--font-sans` Tailwind v4 (никакого webfont не грузится);
 * - ячейка «Ошибок» — `font-medium leading-snug`: вес 500, `line-height`
 *   1.375 × 11 = 15.125 px;
 * - строка таблицы не выше 29 px: `py-0.5` (2+2) + control `h-6` (24) + 1 px
 *   бордер; текст ошибок выше этого ритма растягивает строку.
 *
 * Модель обязана считать теми же числами и тем же шрифтом, иначе
 * `lines × lineHeight` разойдётся с CSS и виртуализатор получит ложную высоту.
 * Здесь та же строка меряется дважды: `pretext` (canvas с computed-стеком и
 * весом 500) и реальный DOM.
 */
import { PROFILES, generateSheet } from "../lib/generator.mjs";
import { CELL_PADDING_PX, buildColumns } from "../lib/columns.mjs";
import { FONT_PX } from "../lib/measurers.mjs";

/** Строка таблицы: `py-0.5` (4) + control `h-6` (24) + 1 px бордер снизу. */
export const PRODUCT_MIN_ROW_HEIGHT_PX = 29;
/** `leading-snug` = 1.375 при `text-[11px]`. */
export const PRODUCT_LINE_HEIGHT_PX = 1.375 * FONT_PX;
/** Вес ячейки «Ошибок» (`font-medium`). */
export const PRODUCT_ERRORS_FONT_WEIGHT = 500;
/** `py-0.5` (2+2) + 1 px `border-b`. */
export const PRODUCT_ROW_PADDING_PX = 5;

const SEED = 1;
const ROWS = 100;
const WIDTHS = [90, 120, 150, 180, 220, 280];
const H4_THRESHOLD = 0.01;
const HEIGHT_TOLERANCE_PX = 0.5;

const SAMPLE = "АБВГДабвгдЁё 0123456789 .,—№ %";

/** Ячейки «Ошибок» из продуктовой политики: перенос без потолка строк. */
const ERROR_COLUMN = {
  ...buildColumns(11).find((column) => column.id === "errors"),
  clamp: null,
};

function emptyStats() {
  return {
    cells: 0,
    lineMismatch: 0,
    heightMismatch: 0,
    widthMismatch: 0,
    maxLineDelta: 0,
    maxAbsHeightDelta: 0,
  };
}

function summarize(stats) {
  const cells = stats.cells || 1;
  return {
    ...stats,
    lineMismatchRate: stats.lineMismatch / cells,
    heightMismatchRate: stats.heightMismatch / cells,
  };
}

/**
 * pretext-адаптер с параметрами CSS продукта: computed-стек семейств, вес 500,
 * размер 11 px. `fontFamily` берётся у самой ячейки — canvas резолвит стек так
 * же, как DOM, поэтому модель не привязана к конкретному установленному шрифту.
 */
async function createProductMeasurer(fontFamily) {
  const pretext = await import("@chenglou/pretext");
  const cssFont = `${PRODUCT_ERRORS_FONT_WEIGHT} ${FONT_PX}px ${fontFamily}`;
  return {
    cssFont,
    prepare(text) {
      const value = text ?? "";
      const prepared = pretext.prepareWithSegments(value, cssFont, {
        whiteSpace: "normal",
      });
      const { kinds, widths } = prepared;
      let maxWordWidth = 0;
      for (let index = 0; index < kinds.length; index += 1) {
        if (kinds[index] !== "text") continue;
        if (widths[index] > maxWordWidth) maxWordWidth = widths[index];
      }
      return {
        prepared,
        text: value,
        naturalWidth: pretext.measureNaturalWidth(prepared),
        maxWordWidth,
      };
    },
    lineCount(prepared, usable) {
      if (!(usable > 0)) return Number.MAX_SAFE_INTEGER;
      if (!prepared.text) return 1;
      return Math.max(1, pretext.measureLineStats(prepared.prepared, usable).lineCount);
    },
    clearCache() {
      pretext.clearCache();
    },
  };
}

function renderTable(width, values) {
  const table = document.createElement("table");
  table.className = "product-table";
  // Ширина таблицы — ровно сумма колонок: content + 12 padding + control 24.
  table.style.width = `${width + CELL_PADDING_PX + 24}px`;

  const colgroup = document.createElement("colgroup");
  const contentCol = document.createElement("col");
  contentCol.style.width = `${width + CELL_PADDING_PX}px`;
  const controlCol = document.createElement("col");
  controlCol.style.width = "24px";
  colgroup.append(contentCol, controlCol);
  table.appendChild(colgroup);

  const tbody = document.createElement("tbody");
  for (const value of values) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "errors";
    td.textContent = value ?? "";
    const control = document.createElement("td");
    control.className = "control";
    control.innerHTML = '<span class="control-box"></span>';
    tr.append(td, control);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

function domLineCount(node) {
  if (!node.firstChild) return 0;
  const range = document.createRange();
  range.selectNodeContents(node);
  const tops = new Set();
  for (const rect of range.getClientRects()) {
    if (rect.width <= 0.01 || rect.height <= 0.01) continue;
    tops.add(Math.round(rect.top));
  }
  return tops.size;
}

async function run() {
  const startedAt = new Date().toISOString();
  const status = document.getElementById("status");
  await document.fonts.ready;

  const probeTable = document.createElement("table");
  probeTable.className = "product-table";
  probeTable.innerHTML = '<tbody><tr><td class="errors"></td></tr></tbody>';
  const probeCell = probeTable.querySelector("td");
  probeCell.textContent = SAMPLE;
  document.body.appendChild(probeTable);
  const style = getComputedStyle(probeCell);
  const fontFamily = style.fontFamily;
  const fontWeight = Number(style.fontWeight);
  const lineHeight = Number.parseFloat(style.lineHeight);
  probeTable.remove();

  const measurer = await createProductMeasurer(fontFamily);

  const byProfile = {};
  const overall = emptyStats();
  const samples = [];

  for (const profile of PROFILES) {
    const sheet = generateSheet({
      profile,
      rows: ROWS,
      columns: [ERROR_COLUMN],
      seed: SEED,
    });
    const values = sheet.rows.map((row) => row.values[ERROR_COLUMN.id] ?? "");
    const profileStats = emptyStats();

    for (const width of WIDTHS) {
      const table = renderTable(width, values);
      document.body.appendChild(table);
      void table.offsetHeight;

      const rows = table.tBodies[0].rows;
      for (let index = 0; index < rows.length; index += 1) {
        const tr = rows[index];
        const td = tr.cells[0];
        const text = values[index] ?? "";
        if (!text) continue;

        const cellStyle = getComputedStyle(td);
        const contentWidth =
          td.getBoundingClientRect().width -
          Number.parseFloat(cellStyle.paddingLeft) -
          Number.parseFloat(cellStyle.paddingRight);
        const widthOk = Math.abs(contentWidth - width) <= 0.51;
        if (!widthOk && samples.length < 40) {
          samples.push({ profile, width, contentWidth, kind: "width" });
        }

        const prepared = measurer.prepare(text);
        const predictedLines = measurer.lineCount(prepared, contentWidth);
        const domLines = domLineCount(td);
        const predictedHeight = Math.max(
          PRODUCT_MIN_ROW_HEIGHT_PX,
          predictedLines * lineHeight + PRODUCT_ROW_PADDING_PX,
        );
        const domHeight = tr.getBoundingClientRect().height;
        const lineMatch = predictedLines === domLines;
        const heightMatch = Math.abs(predictedHeight - domHeight) <= HEIGHT_TOLERANCE_PX;

        for (const target of [overall, profileStats]) {
          target.cells += 1;
          if (!widthOk) target.widthMismatch += 1;
          if (!lineMatch) {
            target.lineMismatch += 1;
            target.maxLineDelta = Math.max(
              target.maxLineDelta,
              Math.abs(predictedLines - domLines),
            );
          }
          if (!heightMatch) {
            target.heightMismatch += 1;
            target.maxAbsHeightDelta = Math.max(
              target.maxAbsHeightDelta,
              Math.abs(predictedHeight - domHeight),
            );
          }
        }
        if (!lineMatch && samples.length < 40) {
          samples.push({
            profile,
            width,
            text,
            predictedLines,
            domLines,
            predictedHeight,
            domHeight,
            maxWordWidth: prepared.maxWordWidth,
          });
        }
      }
      table.remove();
    }

    byProfile[profile] = summarize(profileStats);
    if (status) status.textContent = `Профиль ${profile}: готово`;
  }

  const summary = summarize(overall);
  const result = {
    meta: {
      ticket: 483,
      epic: 475,
      startedAt,
      seed: SEED,
      rows: ROWS,
      widths: WIDTHS,
      profiles: PROFILES,
      cell: "errors (font-medium 500, leading-snug)",
      fontPx: FONT_PX,
      fontWeight,
      fontFamily,
      lineHeight,
      minRowHeightPx: PRODUCT_MIN_ROW_HEIGHT_PX,
      rowPaddingPx: PRODUCT_ROW_PADDING_PX,
      cssFont: measurer.cssFont,
      overflowWrap: "normal",
      devicePixelRatio: window.devicePixelRatio,
      userAgent: navigator.userAgent,
    },
    h4: {
      threshold: H4_THRESHOLD,
      cells: summary.cells,
      lineMismatch: summary.lineMismatch,
      lineMismatchRate: summary.lineMismatchRate,
      heightMismatch: summary.heightMismatch,
      heightMismatchRate: summary.heightMismatchRate,
      widthMismatch: summary.widthMismatch,
      maxLineDelta: summary.maxLineDelta,
      maxAbsHeightDelta: summary.maxAbsHeightDelta,
      pass:
        summary.lineMismatchRate < H4_THRESHOLD &&
        summary.heightMismatchRate < H4_THRESHOLD,
    },
    byProfile: Object.fromEntries(
      Object.entries(byProfile).map(([profile, stats]) => [
        profile,
        {
          ...stats,
          lineMismatchRate: stats.lineMismatchRate,
          heightMismatchRate: stats.heightMismatchRate,
        },
      ]),
    ),
    samples,
  };

  if (status) {
    status.textContent = `H4 (продукт): ${(summary.lineMismatchRate * 100).toFixed(2)}% — ${result.h4.pass ? "pass" : "fail"}`;
  }
  return result;
}

let cached = null;
window.runProductValidation = () => {
  cached ??= run();
  return cached;
};

window.__ready = false;
document.fonts.ready.then(() => {
  window.__ready = true;
});
