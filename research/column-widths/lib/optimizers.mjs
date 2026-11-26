/**
 * Оптимизаторы ширин. Все получают одинаковый бюджет W и одинаковую модель
 * колонок, поэтому их высоты сравнимы напрямую.
 *
 * - `baseline`   — текущие доли из продуктовой таблицы;
 * - `auto`       — эмуляция min/max-content для гибких колонок;
 * - `p90`        — пропорционально p90 натуральной ширины;
 * - `narrowing`  — Marriott et al.: от широкой раскладки сужаем колонку,
 *                  сужение которой меньше всего увеличивает высоту;
 * - `breakpoints`— рост от минимумов по порогам, где падает число строк;
 * - `search`     — тот же рост, но по всей сетке порогов + локальный обмен
 *                  бюджета между колонками (сильный эвристический поиск);
 * - `oracle`     — полный перебор порогов на малых инстансах (эталон).
 *
 * `narrowing`, `breakpoints`, `search` и `oracle` работают по кэшу кривых
 * (`lib/curves.mjs`): число строк на каждом кандидате считается один раз,
 * поэтому шаг поиска — чтение массива, а не пересчёт всех строк.
 */
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  MIN_ROW_HEIGHT_PX,
  ROW_PADDING_PX,
  maxWidth,
} from "./columns.mjs";
import {
  DEFAULT_MAX_CANDIDATES,
  DEFAULT_SAMPLE_ROWS,
  buildCostModel,
  columnMaxWordWidths,
  distributeLeftover,
  effectiveMinWidth,
  finalizeWidths,
  fixedAssignments,
  widthsFromIndices,
} from "./curves.mjs";

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
}

function cellsFor(prepared, columnIndex) {
  return prepared.rows.map((row) => row[columnIndex]);
}

/**
 * Продуктовые доли. Фиксированные колонки берутся из той же базы, что и у
 * остальных оптимизаторов (`fixedAssignments`), чтобы ±1 px округления не
 * превращалось в разную ширину контролов и несравнимый `cost`.
 */
export function baselineOptimizer(prepared, contentWidth) {
  const { columns } = prepared;
  const { baseline, fixedWidths, flexBudget } = fixedAssignments(columns, contentWidth);
  const flex = columns.filter((column) => column.flex);
  const widths = { ...fixedWidths };
  if (flex.length === 0) return { widths };
  const flexTotal = flex.reduce((sum, column) => sum + baseline[column.id], 0) || 1;
  for (const column of flex) {
    widths[column.id] = (baseline[column.id] / flexTotal) * flexBudget;
  }
  return { widths: distributeLeftover(columns, widths, contentWidth) };
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

/**
 * Min/max-content только для гибких колонок: фиксированные остаются на
 * продуктовых долях, иначе `auto` получает лишние пиксели, отнимая ширину у
 * контролов, и сравнение с остальными алгоритмами перестаёт быть честным.
 */
export function autoOptimizer(prepared, contentWidth) {
  const { columns } = prepared;
  const stats = widthStats(prepared);
  const { fixedWidths, flexBudget } = fixedAssignments(columns, contentWidth);
  const flex = columns.filter((column) => column.flex);
  if (flex.length === 0) return { widths: { ...fixedWidths } };
  const maxWords = columnMaxWordWidths(prepared);

  const minContent = {};
  const maxContent = {};
  for (const column of flex) {
    minContent[column.id] = Math.min(
      maxWidth(column, contentWidth),
      effectiveMinWidth(column, maxWords.get(column.id) ?? 0),
    );
    maxContent[column.id] = Math.min(
      maxWidth(column, contentWidth),
      Math.max(minContent[column.id], stats.get(column.id).p99 + CELL_PADDING_PX),
    );
  }

  const minTotal = flex.reduce((sum, column) => sum + minContent[column.id], 0);
  const widths = { ...fixedWidths };
  if (minTotal >= flexBudget) {
    for (const column of flex) widths[column.id] = minContent[column.id];
    return { widths: distributeLeftover(columns, widths, contentWidth) };
  }

  const maxTotal = flex.reduce((sum, column) => sum + maxContent[column.id], 0);
  const wanted = Math.max(0.001, maxTotal - minTotal);
  const growth = Math.min(1, (flexBudget - minTotal) / wanted);
  for (const column of flex) {
    widths[column.id] =
      minContent[column.id] + (maxContent[column.id] - minContent[column.id]) * growth;
  }
  return { widths: distributeLeftover(columns, widths, contentWidth) };
}

export function p90Optimizer(prepared, contentWidth) {
  const { columns } = prepared;
  const stats = widthStats(prepared);
  const { fixedWidths, flexBudget } = fixedAssignments(columns, contentWidth);
  const flex = columns.filter((column) => column.flex);
  if (flex.length === 0) return { widths: { ...fixedWidths } };
  const maxWords = columnMaxWordWidths(prepared);

  const desired = flex.map((column) =>
    clamp(
      stats.get(column.id).p90 + CELL_PADDING_PX,
      Math.min(
        maxWidth(column, contentWidth),
        effectiveMinWidth(column, maxWords.get(column.id) ?? 0),
      ),
      maxWidth(column, contentWidth),
    ),
  );
  const desiredSum = desired.reduce((sum, value) => sum + value, 0);
  const widths = { ...fixedWidths };
  flex.forEach((column, index) => {
    widths[column.id] = (desired[index] * flexBudget) / Math.max(1, desiredSum);
  });
  return { widths: distributeLeftover(columns, widths, contentWidth) };
}

/** Индексы сетки в объект ширин; бюджет гибких не превышен по построению. */
function solution(model, contentWidth, indices) {
  const widths = finalizeWidths(
    model,
    widthsFromIndices(model, indices),
    contentWidth,
  );
  return { widths, cost: model.costOf(indices) };
}

/**
 * Сужает раскладку до бюджета: шаг — следующий нижний порог колонки, выбираем
 * колонку с минимальным приростом `cost` на освобождённый пиксель
 * (Marriott et al.). Возвращает гарантированно допустимое состояние.
 */
export function narrowToBudget(model, start) {
  const { curves, flexBudget } = model;
  const indices = start.slice();
  let widthSum = model.widthSumOf(indices);
  let cost = model.costOf(indices);

  while (widthSum > flexBudget) {
    let best = null;
    for (let c = 0; c < curves.length; c += 1) {
      const from = indices[c];
      if (from === 0) continue;
      const curve = curves[c];
      const next = from - 1;
      const freed = curve.candidates[from] - curve.candidates[next];
      const [trialCost] = model.costOfColumnCandidates(indices, c, [next]);
      const ratio = (trialCost - cost) / freed;
      if (
        best === null ||
        ratio < best.ratio - 1e-9 ||
        (Math.abs(ratio - best.ratio) <= 1e-9 && freed > best.freed)
      ) {
        best = { column: c, index: next, freed, cost: trialCost, ratio };
      }
    }
    if (best === null) break;
    indices[best.column] = best.index;
    widthSum -= best.freed;
    cost = best.cost;
  }
  return { indices, cost, widthSum };
}

/**
 * Жадный рост от текущих индексов: на каждом шаге берём кандидата с лучшим
 * снижением `cost` на пиксель. Перебираются **все** кандидаты выше текущего,
 * а не только следующий порог: иначе колонка застревает на ступени, где
 * ближайший порог ничего не даёт.
 */
export function greedyGrowth(model, start, ceilings = null) {
  const { curves, flexBudget } = model;
  let indices = start.slice();
  let cost = model.costOf(indices);
  let widthSum = model.widthSumOf(indices);
  if (widthSum > flexBudget) {
    ({ indices, cost, widthSum } = narrowToBudget(model, indices));
  }

  for (;;) {
    let best = null;
    for (let c = 0; c < curves.length; c += 1) {
      const curve = curves[c];
      const from = indices[c];
      const fromWidth = curve.candidates[from];
      const limit = ceilings ? Math.min(ceilings[c], curve.candidates.length - 1) : curve.candidates.length - 1;
      const candidates = [];
      for (let j = from + 1; j <= limit; j += 1) {
        if (widthSum + (curve.candidates[j] - fromWidth) > flexBudget) break;
        candidates.push(j);
      }
      if (candidates.length === 0) continue;
      const costs = model.costOfColumnCandidates(indices, c, candidates);
      for (let t = 0; t < candidates.length; t += 1) {
        const j = candidates[t];
        const deltaWidth = curve.candidates[j] - fromWidth;
        const trialCost = costs[t];
        const gain = cost - trialCost;
        if (gain <= 0) continue;
        const ratio = gain / deltaWidth;
        if (
          best === null ||
          ratio > best.ratio + 1e-9 ||
          (Math.abs(ratio - best.ratio) <= 1e-9 && gain > best.gain)
        ) {
          best = { column: c, index: j, deltaWidth, cost: trialCost, gain, ratio };
        }
      }
    }
    if (best === null) break;
    indices[best.column] = best.index;
    widthSum += best.deltaWidth;
    cost = best.cost;
    if (widthSum >= flexBudget) break;
  }
  return { indices, cost, widthSum };
}

export function narrowingOptimizer(prepared, contentWidth, options = {}) {
  const lambda = options.lambda ?? 20;
  const model = buildCostModel(prepared, contentWidth, {
    lambda,
    rowLimit: options.rowLimit ?? DEFAULT_SAMPLE_ROWS,
    maxCandidates: options.maxCandidates ?? DEFAULT_MAX_CANDIDATES,
  });
  const { curves } = model;
  if (curves.length === 0) {
    return { widths: distributeLeftover(model.columns, model.fixedWidths, contentWidth) };
  }

  // Старт — самая широкая разумная раскладка: последний порог каждой колонки.
  const indices = curves.map((curve) => curve.candidates.length - 1);
  const narrowed = narrowToBudget(model, indices);

  // Освободившийся остаток тратим там, где он даёт снижение cost.
  const grown = greedyGrowth(model, narrowed.indices);
  return solution(model, contentWidth, grown.indices);
}

export function breakpointOptimizer(prepared, contentWidth, options = {}) {
  const lambda = options.lambda ?? 20;
  const model = buildCostModel(prepared, contentWidth, {
    lambda,
    rowLimit: options.rowLimit ?? DEFAULT_SAMPLE_ROWS,
    maxCandidates: options.maxCandidates ?? DEFAULT_MAX_CANDIDATES,
  });
  const start = model.curves.map(() => 0);
  const grown = greedyGrowth(model, start);
  return solution(model, contentWidth, grown.indices);
}

/**
 * Индексы, до которых сужаем колонку в локальном обмене: `from-1` (соседний
 * порог), `0` (минимум) и равномерная сетка между ними. По умолчанию — все
 * нижние пороги; `downgrades` ограничивает перебор, если инстанс большой.
 */
function downgradeTrials(from, limit) {
  if (from <= 0) return [];
  const wanted = Math.max(2, limit);
  if (!Number.isFinite(wanted) || from <= wanted) {
    return Array.from({ length: from }, (_, index) => index);
  }
  const out = new Set([0, from - 1]);
  for (let i = 1; i < wanted - 1; i += 1) {
    out.add(Math.round((i * (from - 1)) / (wanted - 1)));
  }
  return [...out].sort((a, b) => a - b);
}

/**
 * Сильный поиск: жадный рост по всей сетке порогов, затем локальный обмен
 * бюджета — пробуем отдать пиксели другой колонке, освободив их у одной, и
 * снова растим. Это выводит из локального оптимума, в котором застревает
 * чистый жадный рост (и `narrowing`, и `breakpoints`).
 */
export function searchOptimizer(prepared, contentWidth, options = {}) {
  const lambda = options.lambda ?? 20;
  const rounds = options.rounds ?? 4;
  const downgradeLimit = options.downgrades ?? Number.POSITIVE_INFINITY;
  const model = buildCostModel(prepared, contentWidth, {
    lambda,
    rowLimit: options.rowLimit ?? DEFAULT_SAMPLE_ROWS,
    maxCandidates: options.maxCandidates ?? DEFAULT_MAX_CANDIDATES,
  });
  const { curves } = model;

  let best = greedyGrowth(model, curves.map(() => 0));

  for (let round = 0; round < rounds; round += 1) {
    let improved = false;
    for (let c = 0; c < curves.length; c += 1) {
      // `best` мог измениться на прошлой итерации: берём только сужение
      // относительно текущего состояния, иначе старт окажется вне бюджета.
      const trials = downgradeTrials(best.indices[c], downgradeLimit);
      for (const j of trials) {
        const trial = best.indices.slice();
        trial[c] = j;
        // Запрещаем колонке вернуться на прежнюю ширину: освобождённые ею
        // пиксели должны уйти другим колонкам, иначе поиск вернётся в ту же
        // локальную точку.
        const ceilings = curves.map((curve) => curve.candidates.length - 1);
        ceilings[c] = j;
        const grown = greedyGrowth(model, trial, ceilings);
        if (grown.cost < best.cost) {
          best = grown;
          improved = true;
        }
      }
    }
    if (!improved) break;
  }

  return solution(model, contentWidth, best.indices);
}

/**
 * Эталон на малых инстансах: полный перебор сетки порогов **гибких** колонок.
 *
 * Сетка после дедупликации доминируемых кандидатов эквивалентна всем порогам
 * `lineCount`, поэтому перебор даёт точный оптимум в модели. Перебор
 * ограничен числом комбинаций: при слишком большой сетке списки равномерно
 * прореживаются (об этом сообщает `thinned`), чтобы эталон оставался
 * вычислимым, а не молча врал.
 */
export function oracleOptimizer(prepared, contentWidth, options = {}) {
  const lambda = options.lambda ?? 20;
  const maxCombinations = options.maxCombinations ?? 2_000_000;
  const model = buildCostModel(prepared, contentWidth, {
    lambda,
    rowLimit: options.rowLimit ?? 60,
    maxCandidates: options.maxCandidates ?? Number.POSITIVE_INFINITY,
  });
  const { curves, flexBudget } = model;
  if (curves.length === 0) {
    return {
      widths: distributeLeftover(model.columns, model.fixedWidths, contentWidth),
      cost: model.costOf([]),
    };
  }

  let combinations = 1;
  for (const curve of curves) combinations *= curve.candidates.length;
  let thinned = false;
  let lists = curves.map((curve) => curve.candidates.map((_, index) => index));
  while (combinations > maxCombinations) {
    thinned = true;
    const before = combinations;
    lists = lists.map((list) => {
      if (list.length <= 2) return list;
      const target = Math.max(2, Math.ceil(list.length * 0.7));
      const next = [];
      for (let i = 0; i < target; i += 1) {
        next.push(list[Math.round((i * (list.length - 1)) / (target - 1))]);
      }
      return [...new Set(next)];
    });
    combinations = lists.reduce((product, list) => product * list.length, 1);
    if (combinations >= before) break;
  }
  if (combinations > maxCombinations) {
    // Прореживание до двух кандидатов на колонку не помогло: инстанс не
    // «малый», и выдавать частичный перебор за эталон нельзя.
    throw new Error(
      `oracle: ${combinations} комбинаций > ${maxCombinations}; нужен инстанс с меньшим числом гибких колонок`,
    );
  }

  const count = curves.length;
  const rowCount = model.rowCount;
  const rowMax = new Int32Array(rowCount);
  rowMax.set(model.fixedLines);
  const best = { cost: Number.POSITIVE_INFINITY, indices: null };
  const current = new Array(count).fill(0);
  // Оптимистичная нижняя граница: оставшиеся колонки получают самый широкий
  // кандидат (строк не больше, обрезки не больше), бюджет не проверяем.
  const lowestTrunc = curves.map(
    (curve) => curve.truncCounts[curve.truncCounts.length - 1],
  );
  const lowestLines = curves.map(
    (curve) => curve.lines[curve.lines.length - 1],
  );

  // Нижняя граница: текущий rowMax + оставшиеся колонки на самых широких.
  const lowerBound = (depth) => {
    let trunc = model.fixedTruncTotal;
    for (let c = 0; c < depth; c += 1) trunc += curves[c].truncCounts[current[c]];
    for (let c = depth; c < count; c += 1) trunc += lowestTrunc[c];
    let total = 0;
    for (let row = 0; row < rowCount; row += 1) {
      let lines = rowMax[row];
      for (let c = depth; c < count; c += 1) {
        const value = lowestLines[c][row];
        if (value > lines) lines = value;
      }
      const height = lines * LINE_HEIGHT_PX + ROW_PADDING_PX;
      total += height > MIN_ROW_HEIGHT_PX ? height : MIN_ROW_HEIGHT_PX;
    }
    return total + lambda * trunc;
  };

  const saved = Array.from({ length: count }, () => new Int32Array(rowCount));
  const recurse = (depth, spent) => {
    if (depth === count) {
      let trunc = model.fixedTruncTotal;
      for (let c = 0; c < count; c += 1) trunc += curves[c].truncCounts[current[c]];
      let total = 0;
      for (let row = 0; row < rowCount; row += 1) {
        const height = rowMax[row] * LINE_HEIGHT_PX + ROW_PADDING_PX;
        total += height > MIN_ROW_HEIGHT_PX ? height : MIN_ROW_HEIGHT_PX;
      }
      const cost = total + lambda * trunc;
      if (cost < best.cost) {
        best.cost = cost;
        best.indices = current.slice();
      }
      return;
    }

    const curve = curves[depth];
    for (const index of lists[depth]) {
      const width = curve.candidates[index];
      if (spent + width > flexBudget) continue;
      saved[depth].set(rowMax);
      const lines = curve.lines[index];
      for (let row = 0; row < rowCount; row += 1) {
        if (lines[row] > rowMax[row]) rowMax[row] = lines[row];
      }
      current[depth] = index;
      if (lowerBound(depth + 1) < best.cost) recurse(depth + 1, spent + width);
      rowMax.set(saved[depth]);
    }
  };
  recurse(0, 0);

  if (best.indices === null) {
    // Бюджет меньше суммы минимумов: честное переполнение по минимумам.
    const widths = finalizeWidths(
      model,
      widthsFromIndices(model, curves.map(() => 0)),
      contentWidth,
    );
    return { widths, cost: model.costOf(curves.map(() => 0)), thinned };
  }

  return {
    ...solution(model, contentWidth, best.indices),
    thinned,
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
  search: (prepared, width, options) => searchOptimizer(prepared, width, options),
};
