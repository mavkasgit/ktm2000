/**
 * Модель колонок предпросмотра остатков.
 *
 * `minPx` — минимум, ниже которого колонка не имеет смысла: шапка, контрол
 * (Select качества, участок), пара знаков. `flex` — участвует в оптимизации
 * ширины; остальные считаются фиксированными. `wrap`/`clamp` — политика
 * переполнения: перенос с потолком строк, одна строка с обрезкой или пилюли,
 * которые сжимаются и обрезают подпись.
 */

export const SERVICE_WIDTH_PX = 68; // шеврон (28) + ячейка сброса (40)
export const CELL_PADDING_PX = 12; // px-1.5 × 2
export const LINE_HEIGHT_PX = 20; // leading-5
export const ROW_PADDING_PX = 20; // py-0.5 × 2 + рамка: 1 строка = 40px
export const MIN_ROW_HEIGHT_PX = 40;

/** Доли из текущей продуктовой раскладки (сумма 95 + 5 служебных = 100). */
const PREVIEW_COLUMNS = [
  {
    id: "row",
    label: "#",
    kind: "numeric",
    font: "sans",
    minPx: 32,
    baselineShare: 3,
    flex: false,
  },
  {
    id: "source_code",
    label: "Код 1С",
    kind: "mono",
    font: "mono",
    minPx: 60,
    baselineShare: 5.5,
    flex: false,
  },
  {
    id: "sku",
    label: "Артикул",
    kind: "mono",
    font: "mono",
    minPx: 70,
    baselineShare: 7,
    flex: false,
  },
  {
    id: "source_name",
    label: "Наименование",
    kind: "text",
    font: "sans",
    wrap: true,
    clamp: 2,
    minPx: 90,
    maxShare: 0.35,
    baselineShare: 15,
    flex: true,
  },
  {
    id: "quantity",
    label: "Кол-во, шт",
    kind: "numeric",
    font: "sans",
    minPx: 55,
    baselineShare: 5.5,
    flex: false,
  },
  {
    id: "meters",
    label: "Метры",
    kind: "numeric",
    font: "sans",
    minPx: 55,
    baselineShare: 5.5,
    flex: false,
  },
  {
    id: "length",
    label: "Длина",
    kind: "numeric",
    font: "sans",
    minPx: 45,
    baselineShare: 5,
    flex: false,
  },
  {
    id: "operations",
    label: "Операции",
    kind: "pills",
    font: "sans",
    wrap: false,
    minPx: 90,
    maxShare: 0.35,
    baselineShare: 21,
    flex: true,
  },
  {
    id: "quality",
    label: "Качество",
    kind: "control",
    font: "sans",
    minPx: 90,
    baselineShare: 7,
    flex: false,
  },
  {
    id: "section",
    label: "Участок",
    kind: "control",
    font: "sans",
    minPx: 100,
    baselineShare: 9.5,
    flex: false,
  },
  {
    id: "errors",
    label: "Ошибки",
    kind: "text",
    font: "sans",
    wrap: true,
    clamp: 3,
    minPx: 90,
    maxShare: 0.3,
    baselineShare: 11,
    flex: true,
  },
];

const SIX_COLUMN_IDS = new Set([
  "row",
  "sku",
  "source_name",
  "quantity",
  "operations",
  "errors",
]);

function genericColumn(index) {
  return {
    id: `extra_${index}`,
    label: `Колонка ${index}`,
    kind: "text",
    font: "sans",
    wrap: true,
    clamp: 2,
    minPx: 70,
    maxShare: 0.25,
    baselineShare: 8,
    flex: true,
  };
}

/**
 * Собирает набор колонок под нужное их число. 6 — представительная выборка
 * (обе «гибкие» текстовые + операции), 12/20 — превью плюс generic-колонки.
 */
export function buildColumns(count = 11) {
  if (count === 6) {
    return PREVIEW_COLUMNS.filter((column) => SIX_COLUMN_IDS.has(column.id));
  }
  if (count <= 11) return PREVIEW_COLUMNS.slice(0, Math.max(6, count));
  const extras = Array.from({ length: count - 11 }, (_, index) => genericColumn(index + 1));
  return [...PREVIEW_COLUMNS, ...extras];
}

export function columnMinWidth(column) {
  return Math.min(column.minPx, column.maxShare ? Number.POSITIVE_INFINITY : column.minPx);
}

/** Ширина в пикселях по продуктовой доле; сумма долей нормализуется в W. */
export function baselineWidths(columns, contentWidth) {
  const shareSum = columns.reduce((sum, column) => sum + column.baselineShare, 0);
  const widths = {};
  for (const column of columns) {
    widths[column.id] = Math.max(
      column.minPx,
      (column.baselineShare / shareSum) * contentWidth,
    );
  }
  return normalizeToBudget(columns, widths, contentWidth);
}

/**
 * Приводит ширины к бюджету: урезает только гибкие колонки, у фиксированных
 * остаётся минимум. Если сумма минимумов больше бюджета, таблица честно
 * переполняется (как `min-width` у реальной таблицы) — это валидный исход.
 */
export function normalizeToBudget(columns, widths, budget) {
  const out = { ...widths };
  for (const column of columns) {
    if (out[column.id] === undefined) out[column.id] = column.minPx;
    out[column.id] = Math.max(column.minPx, out[column.id]);
  }
  let total = sumWidths(columns, out);
  if (total <= budget + 0.5) return out;

  const flexible = columns.filter((column) => column.flex);
  let excess = total - budget;
  // Срезаем пропорционально «запасу» гибких колонок над минимумом.
  while (excess > 0.5 && flexible.length > 0) {
    const slack = flexible.reduce(
      (sum, column) => sum + Math.max(0, out[column.id] - column.minPx),
      0,
    );
    if (slack <= 0.5) break;
    const ratio = Math.min(1, excess / slack);
    for (const column of flexible) {
      const free = Math.max(0, out[column.id] - column.minPx);
      out[column.id] -= free * ratio;
    }
    total = sumWidths(columns, out);
    excess = total - budget;
  }
  return out;
}

export function sumWidths(columns, widths) {
  return columns.reduce((sum, column) => sum + widths[column.id], 0);
}

export function maxWidth(column, contentWidth) {
  if (!column.maxShare) return Number.POSITIVE_INFINITY;
  return Math.max(column.minPx, contentWidth * column.maxShare);
}
