/**
 * H4 на фактическом CSS предпросмотра (#483), **обе переносимые колонки**.
 *
 * Под флагом «Наименование» и «Ошибки» переносятся (основной сценарий спеки,
 * `clamp = ∞`), и ширина каждой участвует в высоте строки. Продукт живёт на
 * своём CSS:
 *
 * - системный стек `--font-sans` Tailwind v4 (webfont не грузится);
 * - «Ошибки» — `font-medium leading-snug`: вес 500, `line-height` 15.125 px;
 * - «Наименование» — обычный вес 400 и наследуемый `line-height: 1.5`
 *   (16.5 px при 11 px), `whitespace-pre-line` вместо `truncate`;
 * - строка не ниже 29 px: `py-0.5` (2+2) + control `h-6` (24) + 1 px бордер.
 *
 * Каждая строка меряется дважды по каждой колонке: `pretext` (canvas с
 * computed-стеком и весом) против реального DOM. Высота строки — максимум по
 * колонкам со своими `line-height`, а не один общий.
 */
import { PROFILES, generateSheet } from "../lib/generator.mjs";
import { CELL_PADDING_PX, buildColumns } from "../lib/columns.mjs";
import { FONT_PX } from "../lib/measurers.mjs";

/** Строка таблицы: `py-0.5` (4) + control `h-6` (24) + 1 px бордер снизу. */
export const PRODUCT_MIN_ROW_HEIGHT_PX = 29;
/** `py-0.5` (2+2) + 1 px `border-b`. */
export const PRODUCT_ROW_PADDING_PX = 5;

const SEED = 1;
const ROWS = 100;
const WIDTHS = [90, 120, 150, 180, 220, 280];
const H4_THRESHOLD = 0.01;
const HEIGHT_TOLERANCE_PX = 0.5;

const SAMPLE = "АБВГДабвгдЁё 0123456789 .,—№ %";

const PREVIEW_COLUMNS = buildColumns(11);
const NAME_COLUMN = {
  ...PREVIEW_COLUMNS.find((column) => column.id === "source_name"),
  wrap: true,
  clamp: null,
};
const ERROR_COLUMN = {
  ...PREVIEW_COLUMNS.find((column) => column.id === "errors"),
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

function mergeStats(target, source) {
  target.cells += source.cells;
  target.lineMismatch += source.lineMismatch;
  target.heightMismatch += source.heightMismatch;
  target.widthMismatch += source.widthMismatch;
  target.maxLineDelta = Math.max(target.maxLineDelta, source.maxLineDelta);
  target.maxAbsHeightDelta = Math.max(
    target.maxAbsHeightDelta,
    source.maxAbsHeightDelta,
  );
}

/**
 * pretext-адаптер: computed-стек семейств + размер + вес конкретной колонки.
 * `fontFamily` берётся у самой ячейки — canvas резолвит стек так же, как DOM.
 */
async function createProductMeasurer(fontFamily, weight, sizePx) {
  const pretext = await import("@chenglou/pretext");
  const cssFont = `${weight} ${sizePx}px ${fontFamily}`;
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
  };
}

function renderTable(width, nameValues, errorValues) {
  const table = document.createElement("table");
  table.className = "product-table";
  // Сумма колонок: name + errors + control 24.
  table.style.width = `${width * 2 + CELL_PADDING_PX * 2 + 24}px`;

  const colgroup = document.createElement("colgroup");
  for (const column of ["name", "errors"]) {
    const col = document.createElement("col");
    col.style.width = `${width + CELL_PADDING_PX}px`;
    colgroup.appendChild(col);
  }
  const controlCol = document.createElement("col");
  controlCol.style.width = "24px";
  colgroup.appendChild(controlCol);
  table.appendChild(colgroup);

  const tbody = document.createElement("tbody");
  for (let index = 0; index < nameValues.length; index += 1) {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.className = "name";
    name.textContent = nameValues[index] ?? "";
    const errors = document.createElement("td");
    errors.className = "errors";
    errors.textContent = errorValues[index] ?? "";
    const control = document.createElement("td");
    control.className = "control";
    control.innerHTML = '<span class="control-box"></span>';
    tr.append(name, errors, control);
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

function contentWidthOf(td) {
  const style = getComputedStyle(td);
  return (
    td.getBoundingClientRect().width -
    Number.parseFloat(style.paddingLeft) -
    Number.parseFloat(style.paddingRight)
  );
}

function readCellFont(className) {
  const probeTable = document.createElement("table");
  probeTable.className = "product-table";
  probeTable.innerHTML = `<tbody><tr><td class="${className}"></td></tr></tbody>`;
  const cell = probeTable.querySelector("td");
  cell.textContent = SAMPLE;
  document.body.appendChild(probeTable);
  const style = getComputedStyle(cell);
  const font = {
    family: style.fontFamily,
    weight: Number(style.fontWeight) || 400,
    sizePx: Number.parseFloat(style.fontSize) || FONT_PX,
    lineHeightPx: Number.parseFloat(style.lineHeight),
  };
  probeTable.remove();
  return font;
}

async function run() {
  const startedAt = new Date().toISOString();
  const status = document.getElementById("status");
  await document.fonts.ready;

  const nameFont = readCellFont("name");
  const errorsFont = readCellFont("errors");
  const nameMeasurer = await createProductMeasurer(
    nameFont.family,
    nameFont.weight,
    nameFont.sizePx,
  );
  const errorsMeasurer = await createProductMeasurer(
    errorsFont.family,
    errorsFont.weight,
    errorsFont.sizePx,
  );

  const byProfile = {};
  const byColumn = { name: emptyStats(), errors: emptyStats() };
  const overall = emptyStats();
  const samples = [];

  for (const profile of PROFILES) {
    const sheet = generateSheet({
      profile,
      rows: ROWS,
      columns: [NAME_COLUMN, ERROR_COLUMN],
      seed: SEED,
    });
    const nameValues = sheet.rows.map((row) => row.values[NAME_COLUMN.id] ?? "");
    const errorValues = sheet.rows.map((row) => row.values[ERROR_COLUMN.id] ?? "");
    const profileStats = emptyStats();

    for (const width of WIDTHS) {
      const table = renderTable(width, nameValues, errorValues);
      document.body.appendChild(table);
      void table.offsetHeight;

      const rows = table.tBodies[0].rows;
      for (let index = 0; index < rows.length; index += 1) {
        const tr = rows[index];
        const nameCell = tr.cells[0];
        const errorCell = tr.cells[1];
        const nameText = nameValues[index] ?? "";
        const errorText = errorValues[index] ?? "";
        const nameWidth = contentWidthOf(nameCell);
        const errorWidth = contentWidthOf(errorCell);
        const widthOk =
          Math.abs(nameWidth - width) <= 0.51 &&
          Math.abs(errorWidth - width) <= 0.51;
        if (!widthOk && samples.length < 40) {
          samples.push({ profile, width, nameWidth, errorWidth, kind: "width" });
        }

        const preparedName = nameMeasurer.prepare(nameText);
        const preparedErrors = errorsMeasurer.prepare(errorText);
        const nameLines = nameText ? nameMeasurer.lineCount(preparedName, nameWidth) : 0;
        const errorLines = errorText
          ? errorsMeasurer.lineCount(preparedErrors, errorWidth)
          : 0;
        const domNameLines = nameText ? domLineCount(nameCell) : 0;
        const domErrorLines = errorText ? domLineCount(errorCell) : 0;
        const predictedHeight = Math.max(
          PRODUCT_MIN_ROW_HEIGHT_PX,
          Math.max(
            nameLines * nameFont.lineHeightPx,
            errorLines * errorsFont.lineHeightPx,
          ) + PRODUCT_ROW_PADDING_PX,
        );
        const domHeight = tr.getBoundingClientRect().height;

        for (const [column, predicted, dom] of [
          ["name", nameLines, domNameLines],
          ["errors", errorLines, domErrorLines],
        ]) {
          const stats = byColumn[column];
          const matches = predicted === dom;
          stats.cells += 1;
          if (!matches) {
            stats.lineMismatch += 1;
            stats.maxLineDelta = Math.max(stats.maxLineDelta, Math.abs(predicted - dom));
          }
          if (!widthOk) stats.widthMismatch += 1;
          if (!matches && samples.length < 40) {
            samples.push({ profile, width, column, nameText: nameText.slice(0, 80), errorText: errorText.slice(0, 80), predicted, dom });
          }
        }

        for (const target of [overall, profileStats]) {
          target.cells += 1;
          if (!widthOk) target.widthMismatch += 1;
          if (Math.abs(predictedHeight - domHeight) > HEIGHT_TOLERANCE_PX) {
            target.heightMismatch += 1;
            target.maxAbsHeightDelta = Math.max(
              target.maxAbsHeightDelta,
              Math.abs(predictedHeight - domHeight),
            );
          }
        }
      }
      table.remove();
    }

    byProfile[profile] = summarize(profileStats);
    if (status) status.textContent = `Профиль ${profile}: готово`;
  }

  mergeStats(overall, byColumn.name);
  mergeStats(overall, byColumn.errors);
  const summary = summarize(overall);
  const byColumnSummary = {
    name: summarize(byColumn.name),
    errors: summarize(byColumn.errors),
  };

  const result = {
    meta: {
      ticket: 483,
      epic: 475,
      startedAt,
      seed: SEED,
      rows: ROWS,
      widths: WIDTHS,
      profiles: PROFILES,
      columns: {
        name: { ...nameFont, cell: "source_name, перенос (whitespace-pre-line)" },
        errors: { ...errorsFont, cell: "errors, font-medium leading-snug" },
      },
      minRowHeightPx: PRODUCT_MIN_ROW_HEIGHT_PX,
      rowPaddingPx: PRODUCT_ROW_PADDING_PX,
      cssFonts: { name: nameMeasurer.cssFont, errors: errorsMeasurer.cssFont },
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
      byColumn: byColumnSummary,
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
