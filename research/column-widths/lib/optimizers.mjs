/**
 * Оптимизаторы ширин. Все получают одинаковый бюджет W и одинаковую модель
 * колонок, поэтому их высоты сравнимы напрямую.
 *
 * - `baseline`   — текущие доли из продуктовой таблицы;
 * - `auto`       — эмуляция браузерного auto layout (min/max-content);
 * - `p90`        — пропорционально p90 натуральной ширины;
 * - `narrowing`  — Marriott et al.: от широкой раскладки сужаем колонку,
 *                  сужение которой меньше всего увеличивает высоту;
 * - `breakpoints`— рост от минимумов по порогам, где падает число строк;
 * - `oracle`     — полный перебор порогов на малых инстансах (эталон).
 */
import {
  CELL_PADDING_PX,
  baselineWidths,
  maxWidth,
  normalizeToBudget,
  sumWidths,
} from "./columns.mjs";
import { evaluate } from "./evaluate.mjs";

const STEP_PX = 8;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function roundWidths(columns, widths) {
  const out = {};
  for (const column of columns) out[column.id] = Math.round(widths[column.id]);
  return out;
}

function fillToBudget(columns, widths, budget) {
  const rounded = roundWidths(columns, widths);
  const flexible = columns.filter((column) => column.flex);
  let total = sumWidths(columns, rounded);
  if (total > budget) return normalizeToBudget(columns, rounded, budget);
  if (total === budget || flexible.length === 0) return rounded;

  const remaining = budget - total;
  const weights = flexible.map((column) => Math.max(0, column.maxShare ?? 0.2));
  const weightSum = weights.reduce((sum, weight) => sum + weight, 0) || 1;
  flexible.forEach((column, index) => {
    rounded[column.id] += (remaining * weights[index]) / weightSum;
  });
  return normalizeToBudget(columns, rounded, budget);
}

/** Фиксированные колонки остаются на текущих долях, гибкие получают остаток. */
function fixedBudget(columns, contentWidth) {
  const baseline = baselineWidths(columns, contentWidth);
  const flex = columns.filter((column) => column.flex);
  const fixed = { ...baseline };
  let fixedTotal = 0;
  for (const column of columns) {
    if (column.flex) continue;
    fixedTotal += fixed[column.id];
  }
  const flexBudget = Math.max(
    flex.reduce((sum, column) => sum + column.minPx, 0),
    contentWidth - fixedTotal,
  );
  return { baseline, fixed, flex, flexBudget };
}

function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
}

function cellsFor(prepared, columnIndex) {
  return prepared.rows.map((row) => row[columnIndex]);
}

export function baselineOptimizer(prepared, contentWidth) {
  const { columns } = prepared;
  return { widths: roundWidths(columns, baselineWidths(columns, contentWidth)) };
}

/** Натуральные ширины по колонкам: p50/p90/p99/max — основа остальных эвристик. */
export function widthStats(prepared) {
  const stats = new Map();
  prepared.columns.forEach((column, index) => {
    const widths = cellsFor(prepared, index).map((cell) => cell.naturalWidth);
    stats.set(column.id, {
      p50: percentile(widths, 0.5),
      p90: percentile(widths, 0.9),
      p99: percentile(widths, 0.99),
      max: widths.reduce((max, value) => Math.max(max, value), 0),
      values: widths,
    });
  });
  return stats;
}

export function autoOptimizer(prepared, contentWidth) {
  const { columns } = prepared;
  const stats = widthStats(prepared);
  const minContent = {};
  const maxContent = {};
  for (const column of columns) {
    const columnStats = stats.get(column.id);
    if (column.kind === "control" || column.kind === "numeric") {
      minContent[column.id] = column.minPx;
      maxContent[column.id] = column.minPx;
      continue;
    }
    const preparedCells = prepared.rows.map(
      (row) => row[columns.indexOf(column)],
    );
    const longestWord = preparedCells.reduce((max, cell) => {
      if (!cell.prepared) return max;
      return Math.max(max, prepared.measurer.maxWordWidth(cell.prepared));
    }, 0);
    minContent[column.id] = Math.min(
      maxWidth(column, contentWidth),
      Math.max(column.minPx, longestWord + CELL_PADDING_PX),
    );
    maxContent[column.id] = Math.min(
      maxWidth(column, contentWidth),
      Math.max(minContent[column.id], columnStats.p99 + CELL_PADDING_PX),
    );
  }

  const minTotal = sumWidths(columns, minContent);
  if (minTotal >= contentWidth) {
    return { widths: roundWidths(columns, minContent) };
  }

  const maxTotal = sumWidths(columns, maxContent);
  const spare = contentWidth - minTotal;
  const wantedSpare = Math.max(0.001, maxTotal - minTotal);
  const growth = Math.min(1, spare / wantedSpare);
  const widths = {};
  for (const column of columns) {
    widths[column.id] =
      minContent[column.id] + (maxContent[column.id] - minContent[column.id]) * growth;
  }
  return { widths: fillToBudget(columns, widths, contentWidth) };
}

export function p90Optimizer(prepared, contentWidth) {
  const { columns } = prepared;
  const stats = widthStats(prepared);
  const { fixed, flex, flexBudget } = fixedBudget(columns, contentWidth);
  const desired = flex.map((column) =>
    clamp(
      stats.get(column.id).p90 + CELL_PADDING_PX,
      column.minPx,
      maxWidth(column, contentWidth),
    ),
  );
  const desiredSum = desired.reduce((sum, value) => sum + value, 0);
  const widths = { ...fixed };
  flex.forEach((column, index) => {
    widths[column.id] = (desired[index] * flexBudget) / Math.max(1, desiredSum);
  });
  return { widths: fillToBudget(columns, widths, contentWidth) };
}

export function narrowingOptimizer(prepared, contentWidth, options = {}) {
  const { lambda = 20, step = STEP_PX } = options;
  const { columns } = prepared;
  const stats = widthStats(prepared);
  const { fixed, flex, flexBudget } = fixedBudget(columns, contentWidth);
  if (flex.length === 0) return { widths: roundWidths(columns, fixed) };

  // «Самая широкая разумная» раскладка: p99, но не больше maxShare.
  const widths = { ...fixed };
  for (const column of flex) {
    const p99 = stats.get(column.id).p99 + CELL_PADDING_PX;
    widths[column.id] = Math.max(
      column.minPx,
      Math.min(maxWidth(column, contentWidth), Math.max(p99, column.minPx)),
    );
  }
  let total = sumWidths(columns, widths);
  // Если разумный максимум не заполняет бюджет — растягиваем гибкие до бюджета.
  if (total < flexBudget) {
    const spare = flexBudget - total;
    const weight = flex.reduce((sum, column) => sum + (column.maxShare ?? 0.2), 0) || 1;
    for (const column of flex) {
      widths[column.id] += (spare * (column.maxShare ?? 0.2)) / weight;
    }
    return { widths: roundWidths(columns, widths) };
  }

  const score = (candidate) =>
    evaluate(prepared, candidate, { lambda, collectRows: false }).cost;

  while (total > flexBudget + 0.5) {
    let best = null;
    for (const column of flex) {
      const current = widths[column.id];
      if (current - step < column.minPx) continue;
      const candidate = { ...widths, [column.id]: current - step };
      const cost = score(candidate);
      if (
        best === null ||
        cost < best.cost ||
        (cost === best.cost && column.id < best.column.id)
      ) {
        best = { column, candidate, cost };
      }
    }
    if (!best) break;
    widths[best.column.id] = best.candidate[best.column.id];
    total = sumWidths(columns, widths);
  }

  return { widths: fillToBudget(columns, widths, contentWidth) };
}

function candidateWidths(prepared, column, index, contentWidth, limit = 48) {
  const max = maxWidth(column, contentWidth);
  const candidates = new Set([column.minPx, Math.min(max, column.minPx + STEP_PX)]);
  const values = cellsFor(prepared, index).map((cell) => cell.naturalWidth);
  for (const value of values) {
    const breakpoints = column.wrap ? (column.clamp ?? 1) : 1;
    for (let lines = 1; lines <= breakpoints; lines += 1) {
      const width = value / lines + CELL_PADDING_PX;
      if (width > column.minPx && width <= max) candidates.add(width);
    }
  }
  const sorted = [...candidates].sort((a, b) => a - b);
  if (sorted.length <= limit) return sorted;
  // Прореживаем равномерно, сохраняя min и max.
  const out = [];
  for (let i = 0; i < limit; i += 1) {
    out.push(sorted[Math.round((i * (sorted.length - 1)) / (limit - 1))]);
  }
  return [...new Set(out)];
}

export function breakpointOptimizer(prepared, contentWidth, options = {}) {
  const { lambda = 20 } = options;
  const { columns } = prepared;
  const { fixed, flex, flexBudget } = fixedBudget(columns, contentWidth);
  if (flex.length === 0) return { widths: roundWidths(columns, fixed) };

  const flexIndex = new Map(flex.map((column) => [column.id, columns.indexOf(column)]));
  const candidates = new Map();
  for (const column of flex) {
    const list = candidateWidths(
      prepared,
      column,
      flexIndex.get(column.id),
      contentWidth,
    ).filter((width) => width >= column.minPx && width <= flexBudget);
    candidates.set(column.id, list);
  }

  const widths = { ...fixed };
  for (const column of flex) widths[column.id] = column.minPx;
  const score = (candidate) =>
    evaluate(prepared, candidate, { lambda, collectRows: false }).cost;

  let currentCost = score(widths);
  let total = sumWidths(columns, widths);

  // Жадно берём следующий порог с лучшим снижением cost на пиксель.
  for (;;) {
    let best = null;
    for (const column of flex) {
      const list = candidates.get(column.id);
      const current = widths[column.id];
      const next = list.find((width) => width > current + 0.5);
      if (next === undefined) continue;
      const delta = next - current;
      if (total + delta > flexBudget) continue;
      const candidate = { ...widths, [column.id]: next };
      const cost = score(candidate);
      const gain = (currentCost - cost) / delta;
      if (
        best === null ||
        gain > best.gain ||
        (gain === best.gain && delta < best.delta)
      ) {
        best = { column, width: next, delta, cost, gain };
      }
    }
    if (best === null || best.gain <= 0) break;
    widths[best.column.id] = best.width;
    total += best.delta;
    currentCost = best.cost;
  }

  return { widths: fillToBudget(columns, widths, contentWidth) };
}

/**
 * Точный перебор порогов для гибких колонок на малом инстансе.
 * Возвращает лучший cost, который достижим при бюджете; нужен для gap-метрики.
 */
export function oracleOptimizer(prepared, contentWidth, options = {}) {
  const { lambda = 20, perColumnLimit = 32 } = options;
  const { columns } = prepared;
  const { fixed, flex, flexBudget } = fixedBudget(columns, contentWidth);
  if (flex.length === 0) {
    return { widths: roundWidths(columns, fixed), cost: 0 };
  }

  const lists = flex.map((column) => {
    const list = candidateWidths(
      prepared,
      column,
      columns.indexOf(column),
      contentWidth,
      perColumnLimit,
    ).filter((width) => width >= column.minPx && width <= flexBudget);
    return [...new Set([column.minPx, ...list])].sort((a, b) => a - b);
  });

  let best = null;
  const widths = { ...fixed };
  const recurse = (index, spent) => {
    if (index === flex.length) {
      const cost = evaluate(prepared, widths, { lambda, collectRows: false }).cost;
      if (best === null || cost < best.cost) best = { cost, widths: { ...widths } };
      return;
    }
    for (const width of lists[index]) {
      if (spent + width > flexBudget) continue;
      widths[flex[index].id] = width;
      recurse(index + 1, spent + width);
    }
  };
  recurse(0, 0);

  if (!best) return { widths: roundWidths(columns, fixed), cost: 0 };
  return {
    widths: fillToBudget(columns, best.widths, contentWidth),
    cost: best.cost,
  };
}

export const OPTIMIZERS = {
  baseline: (prepared, width) => baselineOptimizer(prepared, width),
  auto: (prepared, width) => autoOptimizer(prepared, width),
  p90: (prepared, width) => p90Optimizer(prepared, width),
  narrowing: (prepared, width, options) =>
    narrowingOptimizer(prepared, width, options),
  breakpoints: (prepared, width, options) =>
    breakpointOptimizer(prepared, width, options),
};
