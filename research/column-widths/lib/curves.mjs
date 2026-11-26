/**
 * Кэш кривых «ширина → число строк» и модель стоимости по сетке breakpoints.
 *
 * Для колонки и строки `lineCount(prepared, usable)` — ступенчатая функция
 * ширины: она меняется только в тех точках, где жадный перенос перестаёт
 * укладываться в очередное число строк. Если один раз найти эти пороги
 * (для переноса с `clamp` — пороги `b1..b_clamp`), то любая ширина оценивается
 * без вызова измерителя: `lines = 1 + #{k: b_k > usable}`. Именно это снимает
 * главную стоимость `narrowing`: пересчёт всех строк на каждый шаг заменяется
 * чтением массива.
 *
 * Сетка кандидатов колонки — объединение порогов всех её строк (плюс `min`),
 * обрезанное `maxShare` и продедуплицированное: кандидат, у которого вектор
 * `(lines, trunc)` совпадает с более узким, доминируется (та же стоимость,
 * больше пикселей) и выбрасывается. После дедупликации перебор по сетке
 * эквивалентен перебору по всем порогам — на этом стоит оракул.
 */
import {
  CELL_PADDING_PX,
  LINE_HEIGHT_PX,
  MIN_ROW_HEIGHT_PX,
  ROW_PADDING_PX,
  baselineWidths,
  maxWidth,
} from "./columns.mjs";
import { measureCell } from "./evaluate.mjs";

/** Потолок кандидатов на колонку у эвристик (оракул берёт все пороги). */
export const DEFAULT_MAX_CANDIDATES = 40;

/** Сколько строк листа видит поиск: подвыборка по H2 (полная проверка — #482). */
export const DEFAULT_SAMPLE_ROWS = 500;

/**
 * Сколько строк-выбросов гарантированно попадает в подвыборку: по одной на
 * каждую гибкую колонку (самая длинная ячейка). Остальное — равномерная
 * сетка по листу. Делать хвост долей подвыборки нельзя: `cost` чувствителен к
 * доле обрезанных ячеек, и перекос в длинные строки систематически завышает
 * ширину «под хвост» (измерено на `long-tail`: +7% cost против полного листа).
 */
function longCellCount(flexCount) {
  return Math.max(1, flexCount);
}

/** Потолок строк для колонки без `line-clamp` (защита от бесконечного перебора). */
const MAX_LINES = 64;

/**
 * Динамический минимум текстовой колонки: `max(minPx, maxWordWidth + padding)`.
 *
 * #479 (H4, браузер): `pretext` рвёт слово по графемам, а CSS предпросмотра с
 * `overflow-wrap: normal` оставляет его в одной переполненной строке. Если
 * ширина меньше самого широкого слова листа, модель систематически завышает
 * число строк. Поэтому оптимизатор не имеет права сузить текстовую колонку
 * ниже слова — иначе `cost` считает несуществующие переносы.
 */
export function effectiveMinWidth(column, maxWordWidth) {
  const wordMin = Math.ceil(maxWordWidth) + CELL_PADDING_PX;
  return Math.max(column.minPx, wordMin);
}

/** Самый широкий неразрывный кусок по каждой переносимой колонке листа. */
export function columnMaxWordWidths(prepared) {
  const { rows, columns, measurer } = prepared;
  const result = new Map();
  columns.forEach((column, index) => {
    if (!column.wrap) {
      result.set(column.id, 0);
      return;
    }
    let widest = 0;
    for (let row = 0; row < rows.length; row += 1) {
      const cell = rows[row][index];
      if (!cell.prepared) continue;
      const width = measurer.maxWordWidth(cell.prepared);
      if (width > widest) widest = width;
    }
    result.set(column.id, widest);
  });
  return result;
}

/**
 * Детерминированная стратифицированная подвыборка: длинные ячейки (хвост и
 * выбросы) попадают в неё гарантированно, остаток — равномерно по листу.
 * Индексы возвращаются по возрастанию, поэтому поиск не зависит от порядка
 * строк в исходном листе.
 */
export function selectSampleRows(prepared, limit = DEFAULT_SAMPLE_ROWS) {
  const { rows, columns } = prepared;
  const total = rows.length;
  if (total <= limit) return Array.from({ length: total }, (_, index) => index);

  const scoreColumns = [];
  columns.forEach((column, index) => {
    if (column.flex) scoreColumns.push(index);
  });
  if (scoreColumns.length === 0) {
    columns.forEach((_, index) => scoreColumns.push(index));
  }

  const scores = new Float64Array(total);
  for (let row = 0; row < total; row += 1) {
    let score = 0;
    for (const index of scoreColumns) {
      score += Math.log1p(rows[row][index].naturalWidth);
    }
    scores[row] = score;
  }

  const order = Array.from({ length: total }, (_, index) => index);
  order.sort((a, b) => scores[b] - scores[a] || a - b);

  const chosen = new Uint8Array(total);
  const longCount = Math.min(total, longCellCount(scoreColumns.length));
  for (let i = 0; i < longCount; i += 1) chosen[order[i]] = 1;

  const rest = [];
  for (let row = 0; row < total; row += 1) if (!chosen[row]) rest.push(row);
  const need = limit - longCount;
  for (let i = 0; i < need; i += 1) {
    const pick = Math.min(
      rest.length - 1,
      Math.round((i * (rest.length - 1)) / Math.max(1, need - 1)),
    );
    chosen[rest[pick]] = 1;
  }

  const sample = [];
  for (let row = 0; row < total && sample.length < limit; row += 1) {
    if (chosen[row]) sample.push(row);
  }
  return sample;
}

/**
 * Пороги одной ячейки: возрастающий список полезных ширин `b1..b_cap`, где
 * `b_k` — минимальная ширина, при которой строк не больше `k`, и отдельный
 * порог обрезки `truncAt` (ширина `b_cap`: ниже неё текст не влезает в
 * `line-clamp`).
 *
 * Пороги ниже `minUsable` не нужны: колонка уже не станет уже `min`. Поэтому
 * `truncAt = 0` означает «в достижимом диапазоне обрезки нет».
 */
function cellThresholds(measurer, cell, limit, minUsable) {
  const natural = cell.naturalWidth;
  if (cell.kind === "control" || cell.kind === "numeric") {
    return { lines: [], truncAt: 0 };
  }
  if (!cell.wrap) return { lines: [], truncAt: natural };
  if (natural <= minUsable) return { lines: [], truncAt: 0 };

  const cap = Math.min(limit, MAX_LINES);
  if (cap < 2) return { lines: [natural], truncAt: natural };

  const lines = [natural];
  let truncAt = 0;
  let completed = false;
  for (let target = 2; target <= cap; target += 1) {
    if (measurer.lineCount(cell.prepared, minUsable) <= target) break;
    let low = minUsable;
    let high = natural;
    // Инвариант: lineCount(low) > target, lineCount(high) <= target.
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (measurer.lineCount(cell.prepared, middle) <= target) high = middle;
      else low = middle;
    }
    lines.push(high);
    if (target === cap) {
      truncAt = high;
      completed = true;
    }
  }
  if (!completed) truncAt = 0;
  lines.sort((a, b) => a - b);
  return { lines, truncAt };
}

/** Таблица `(lines, trunc)` колонки на всех кандидатах и строках подвыборки. */
function buildTable(thresholdRows, width, limit, wrap) {
  const rowCount = thresholdRows.length;
  const usable = width - CELL_PADDING_PX;
  const lines = new Uint8Array(rowCount);
  const trunc = new Uint8Array(rowCount);
  let truncCount = 0;

  for (let row = 0; row < rowCount; row += 1) {
    const { lines: thresholds, truncAt } = thresholdRows[row];
    if (thresholds.length === 0) {
      lines[row] = 1;
    } else {
      let above = 0;
      for (let i = thresholds.length - 1; i >= 0; i -= 1) {
        if (thresholds[i] > usable) above += 1;
        else break;
      }
      lines[row] = wrap ? Math.min(limit, 1 + above) : 1;
    }
    if (truncAt > usable) {
      trunc[row] = 1;
      truncCount += 1;
    }
  }
  return { width, lines, trunc, truncCount };
}

/** Таблица `(lines, trunc)` колонки на всех кандидатах и строках подвыборки. */
function sameTable(a, b) {
  if (a.truncCount !== b.truncCount) return false;
  const length = a.lines.length;
  for (let index = 0; index < length; index += 1) {
    if (a.lines[index] !== b.lines[index]) return false;
    if (a.trunc[index] !== b.trunc[index]) return false;
  }
  return true;
}

/** Равномерное прореживание сетки с сохранением первого и последнего кандидата. */
function thinCandidates(tables, limit) {
  if (!limit || tables.length <= limit) return tables;
  const target = Math.max(2, limit);
  const kept = [tables[0]];
  for (let i = 1; i < target - 1; i += 1) {
    kept.push(tables[Math.round((i * (tables.length - 1)) / (target - 1))]);
  }
  kept.push(tables[tables.length - 1]);
  return kept.filter((table, index) => index === 0 || !sameTable(table, kept[index - 1]));
}

/**
 * Кривая одной гибкой колонки: сетка кандидатов и таблицы строк/обрезки.
 * `maxWidthLimit` позволяет оракулу учесть бюджет остальных колонок.
 */
function buildFlexCurve(prepared, column, index, context) {
  const { measurer, sampleIndexes, contentWidth, maxCandidates, widthCap, maxWordWidth } =
    context;
  const max = Math.min(
    maxWidth(column, contentWidth),
    Number.isFinite(widthCap) ? widthCap : Number.POSITIVE_INFINITY,
  );
  const min = Math.min(
    Math.max(column.minPx, effectiveMinWidth(column, maxWordWidth)),
    max,
  );
  const minUsable = min - CELL_PADDING_PX;
  const limit = column.wrap ? (column.clamp ?? MAX_LINES) : 1;

  const thresholdRows = new Array(sampleIndexes.length);
  const widths = new Set([min]);
  for (let i = 0; i < sampleIndexes.length; i += 1) {
    const cell = prepared.rows[sampleIndexes[i]][index];
    const thresholds = cellThresholds(measurer, cell, limit, minUsable);
    thresholdRows[i] = thresholds;
    for (const usable of thresholds.lines) {
      const width = Math.ceil(usable) + CELL_PADDING_PX;
      if (width > min && width <= max) widths.add(width);
    }
    const truncatedAt = Math.ceil(thresholds.truncAt) + CELL_PADDING_PX;
    if (thresholds.truncAt > 0 && truncatedAt > min && truncatedAt <= max) {
      widths.add(truncatedAt);
    }
  }

  let tables = [...widths]
    .sort((a, b) => a - b)
    .map((width) => buildTable(thresholdRows, width, limit, Boolean(column.wrap)))
    .filter((table, position, all) => position === 0 || !sameTable(table, all[position - 1]));

  tables = thinCandidates(tables, maxCandidates);

  return {
    column,
    index,
    max,
    min,
    minUsable,
    limit,
    wrap: Boolean(column.wrap),
    // Сырые пороги строк: позволяют оценить `cost` на произвольной ширине,
    // а не только на сетке кандидатов (`costAtWidths`). Нужно робастному
    // вектору долей: он проверяет одну долю на нескольких W.
    thresholds: thresholdRows,
    candidates: tables.map((table) => table.width),
    lines: tables.map((table) => table.lines),
    trunc: tables.map((table) => table.trunc),
    truncCounts: tables.map((table) => table.truncCount),
  };
}

/**
 * Фиксированные колонки остаются на продуктовых долях, бюджет гибких —
 * остаток. Одна и та же база у всех оптимизаторов: разница в `cost` не может
 * возникнуть из-за того, что кто-то «съел» ширину контролов.
 */
export function fixedAssignments(columns, contentWidth) {
  const baseline = baselineWidths(columns, contentWidth);
  const fixedWidths = {};
  let fixedTotal = 0;
  for (const column of columns) {
    if (column.flex) continue;
    fixedWidths[column.id] = Math.round(baseline[column.id]);
    fixedTotal += fixedWidths[column.id];
  }
  return {
    baseline,
    fixedWidths,
    fixedTotal,
    flexBudget: contentWidth - fixedTotal,
  };
}

/** Округление до целых пикселей с сохранением суммы бюджета (метод остатков). */
export function roundToBudget(columns, targets, budget) {
  const out = {};
  const fractions = [];
  let sum = 0;
  for (const column of columns) {
    const value = Math.max(column.minPx, targets[column.id]);
    const base = Math.floor(value);
    out[column.id] = base;
    sum += base;
    fractions.push({ id: column.id, fraction: value - base });
  }
  let extra = Math.round(budget) - sum;
  if (extra <= 0) return out;
  fractions.sort((a, b) => b.fraction - a.fraction || (a.id < b.id ? -1 : 1));
  let index = 0;
  while (extra > 0 && fractions.length > 0) {
    out[fractions[index % fractions.length].id] += 1;
    index += 1;
    extra -= 1;
  }
  return out;
}

/**
 * Расширяет раскладку до бюджета, не выходя за `maxShare`. Расширение не
 * ухудшает `cost`, поэтому остаток можно отдавать произвольно; при полном
 * отсутствии запаса ширина честно остаётся меньше бюджета.
 */
export function distributeLeftover(columns, widths, contentWidth) {
  const out = { ...widths };
  const flexible = columns.filter((column) => column.flex);
  let total = 0;
  for (const column of columns) {
    out[column.id] = Math.max(column.minPx, Math.round(out[column.id] ?? column.minPx));
    total += out[column.id];
  }
  const leftover = contentWidth - total;
  if (leftover <= 0 || flexible.length === 0) return out;

  const slack = flexible.map((column) => {
    const cap = maxWidth(column, contentWidth);
    const limit = Number.isFinite(cap) ? Math.round(cap) : contentWidth;
    return Math.max(0, limit - out[column.id]);
  });
  const slackTotal = slack.reduce((sum, value) => sum + value, 0);
  if (slackTotal <= 0) return out;
  const toSpend = Math.min(leftover, slackTotal);

  const shares = slack.map((value) => (toSpend * value) / slackTotal);
  let spent = 0;
  flexible.forEach((column, index) => {
    const whole = Math.floor(shares[index]);
    out[column.id] += whole;
    spent += whole;
  });
  const order = shares
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  let rest = toSpend - spent;
  for (let i = 0; i < order.length && rest > 0; i += 1) {
    out[flexible[order[i].index].id] += 1;
    rest -= 1;
  }
  return out;
}

/**
 * Модель стоимости для поиска: фиксированные колонки считаются один раз,
 * гибкие — по кэшу. `costOf` повторяет `evaluate` бит-в-бит на подвыборке
 * (это проверяет тест), но без вызовов измерителя.
 */
export function buildCostModel(prepared, contentWidth, options = {}) {
  const lambda = options.lambda ?? 20;
  const rowLimit = options.rowLimit ?? DEFAULT_SAMPLE_ROWS;
  const maxCandidates = options.maxCandidates ?? DEFAULT_MAX_CANDIDATES;
  // Ограничение на долю строк с обрезанными пилюлями (#488). Доля — от 0 до 1
  // по строкам подвыборки; `null` — без ограничения (воспроизводимость H1).
  const pillsMaxTruncatedShare = Number.isFinite(options.pillsMaxTruncatedShare)
    ? Math.min(1, Math.max(0, options.pillsMaxTruncatedShare))
    : null;
  const { columns, rows, measurer } = prepared;

  const { fixedWidths, fixedTotal, flexBudget } = fixedAssignments(columns, contentWidth);

  const sampleIndexes = selectSampleRows(prepared, rowLimit);
  const rowCount = sampleIndexes.length;

  const fixedLines = new Uint8Array(rowCount);
  let fixedTruncTotal = 0;
  columns.forEach((column, index) => {
    if (column.flex) return;
    const usable = fixedWidths[column.id] - CELL_PADDING_PX;
    for (let row = 0; row < rowCount; row += 1) {
      const measured = measureCell(measurer, rows[sampleIndexes[row]][index], usable);
      const lines = Math.min(measured.lines, 255);
      if (lines > fixedLines[row]) fixedLines[row] = lines;
      if (measured.truncated) fixedTruncTotal += 1;
    }
  });

  const flexColumns = columns.filter((column) => column.flex);
  // Минимум — не только статический `minPx`: колонка не уже самого широкого
  // слова листа (#479/H4).
  const maxWordWidths = columnMaxWordWidths(prepared);
  const minimums = {};
  for (const column of flexColumns) {
    const widthCap = Math.max(
      column.minPx,
      maxWidth(column, contentWidth),
    );
    minimums[column.id] = Math.min(
      effectiveMinWidth(column, maxWordWidths.get(column.id) ?? 0),
      widthCap,
    );
  }
  const flexMinSum = flexColumns.reduce((sum, column) => sum + minimums[column.id], 0);

  const curves = [];
  columns.forEach((column, index) => {
    if (!column.flex) return;
    // Колонка не может занять больше, чем остаётся после минимумов соседей.
    const widthCap = Math.max(
      minimums[column.id],
      flexBudget - (flexMinSum - minimums[column.id]),
    );
    curves.push(
      buildFlexCurve(prepared, column, index, {
        measurer,
        sampleIndexes,
        contentWidth,
        maxCandidates,
        widthCap,
        maxWordWidth: maxWordWidths.get(column.id) ?? 0,
      }),
    );
  });

  // Нижние границы по кривым (#488). Ограничение пилюль — не штраф в `cost`
  // (пилюли не влияют на высоту), а запрет опускать колонку ниже ширины, на
  // которой доля строк с обрезанными пилюлями уже уложилась в лимит. Ищем
  // первый кандидат с `truncCount ≤ лимит × строк`: `truncCounts` убывает с
  // шириной, поэтому это и есть минимальная допустимая ширина.
  const floors = curves.map(() => 0);
  const floorWidths = {};
  const pillConstraints = [];
  if (pillsMaxTruncatedShare !== null && rowCount > 0) {
    curves.forEach((curve, c) => {
      if (curve.column.kind !== "pills") return;
      const target = pillsMaxTruncatedShare * rowCount;
      let index = curve.candidates.length - 1;
      for (let i = 0; i < curve.candidates.length; i += 1) {
        if (curve.truncCounts[i] <= target + 1e-9) {
          index = i;
          break;
        }
      }
      floors[c] = index;
      const width = curve.candidates[index];
      floorWidths[curve.column.id] = width;
      const sampleShare = curve.truncCounts[index] / rowCount;
      pillConstraints.push({
        column: curve.column.id,
        limitPct: pillsMaxTruncatedShare * 100,
        requiredWidth: width,
        requiredFlexSharePct: (width / flexBudget) * 100,
        sampleTruncatedSharePct: sampleShare * 100,
        minWidth: curve.min,
        maxWidth: curve.max,
        // `false` — даже самый широкий кандидат не уложился в лимит: это
        // фиксируется честно, а не выдаётся за выполненное ограничение.
        satisfied: sampleShare <= pillsMaxTruncatedShare + 1e-9,
      });
    });
  }
  const lowerBounds = {};
  for (const column of flexColumns) {
    lowerBounds[column.id] = Math.max(
      minimums[column.id],
      floorWidths[column.id] ?? 0,
    );
  }
  const lowerBoundTotal = flexColumns.reduce(
    (sum, column) => sum + lowerBounds[column.id],
    0,
  );
  // Сумма минимумов с ограничением больше бюджета — не «победа» поиска, а
  // честное переполнение: раскладка останется на нижних границах.
  const budgetFeasible = lowerBoundTotal <= flexBudget + 1e-6;

  const scratch = new Int32Array(rowCount);

  function costOfWith(indices, overrideColumn, overrideIndex) {
    let truncTotal = fixedTruncTotal;
    if (rowCount === 0) return lambda * truncTotal;
    scratch.set(fixedLines);
    for (let c = 0; c < curves.length; c += 1) {
      const curve = curves[c];
      const index = c === overrideColumn ? overrideIndex : indices[c];
      const lines = curve.lines[index];
      truncTotal += curve.truncCounts[index];
      for (let row = 0; row < rowCount; row += 1) {
        const value = lines[row];
        if (value > scratch[row]) scratch[row] = value;
      }
    }
    let total = 0;
    for (let row = 0; row < rowCount; row += 1) {
      const height = scratch[row] * LINE_HEIGHT_PX + ROW_PADDING_PX;
      total += height > MIN_ROW_HEIGHT_PX ? height : MIN_ROW_HEIGHT_PX;
    }
    return total + lambda * truncTotal;
  }

  function costOf(indices) {
    return costOfWith(indices, -1, 0);
  }

  const othersMax = new Int32Array(rowCount);

  /**
   * Стоимость для набора кандидатов одной колонки. Максимум по остальным
   * колонкам считается один раз (O(строки × колонки)), дальше каждый кандидат
   * стоит O(строки): перебор «все пороги колонки» перестаёт быть
   * квадратичным по числу гибких колонок.
   */
  function costOfColumnCandidates(indices, column, candidates) {
    othersMax.set(fixedLines);
    let truncOthers = fixedTruncTotal;
    for (let d = 0; d < curves.length; d += 1) {
      if (d === column) continue;
      const other = curves[d];
      const index = indices[d];
      const otherLines = other.lines[index];
      truncOthers += other.truncCounts[index];
      for (let row = 0; row < rowCount; row += 1) {
        const value = otherLines[row];
        if (value > othersMax[row]) othersMax[row] = value;
      }
    }

    const curve = curves[column];
    const out = new Array(candidates.length);
    for (let t = 0; t < candidates.length; t += 1) {
      const index = candidates[t];
      const lines = curve.lines[index];
      let total = 0;
      for (let row = 0; row < rowCount; row += 1) {
        const value = lines[row] > othersMax[row] ? lines[row] : othersMax[row];
        const height = value * LINE_HEIGHT_PX + ROW_PADDING_PX;
        total += height > MIN_ROW_HEIGHT_PX ? height : MIN_ROW_HEIGHT_PX;
      }
      out[t] = total + lambda * (truncOthers + curve.truncCounts[index]);
    }
    return out;
  }

  function widthSumOf(indices) {
    let sum = 0;
    for (let c = 0; c < curves.length; c += 1) sum += curves[c].candidates[indices[c]];
    return sum;
  }

  return {
    lambda,
    columns,
    flexColumns: curves.map((curve) => curve.column),
    curves,
    fixedWidths,
    fixedTotal,
    fixedLines,
    fixedTruncTotal,
    flexBudget,
    minimums,
    // Нижние границы модели: `minimums` плюс ширина, требуемая ограничением
    // пилюль. Поиск не опускается ниже `floors`, робастный вектор — ниже
    // `lowerBounds`.
    floors,
    floorWidths,
    lowerBounds,
    lowerBoundTotal,
    budgetFeasible,
    pillsMaxTruncatedShare,
    pillConstraints,
    maxWordWidths,
    sampleIndexes,
    rowCount,
    costOf,
    costOfWith,
    costOfColumnCandidates,
    widthSumOf,
  };
}

/**
 * `cost` на произвольных ширинах, а не только на сетке кандидатов.
 *
 * Робастный вектор долей задаёт ширины как `доля × бюджет` на каждой `W'`;
 * это почти никогда не совпадает с порогом из сетки. Оценка идёт по тем же
 * сырым порогам, что и `costOf`, поэтому результат бит-в-бит совпадает с
 * `evaluate` на тех же ширинах (тест).
 */
export function costAtWidths(model, widths) {
  const { curves, rowCount } = model;
  const rowMax = new Int32Array(rowCount);
  rowMax.set(model.fixedLines);
  let truncTotal = model.fixedTruncTotal;

  for (let c = 0; c < curves.length; c += 1) {
    const curve = curves[c];
    const usable = widths[curve.column.id] - CELL_PADDING_PX;
    const { thresholds, limit, wrap } = curve;
    for (let row = 0; row < rowCount; row += 1) {
      const entry = thresholds[row];
      let lines = 1;
      const list = entry.lines;
      if (list.length > 0) {
        // Первый порог, который больше ширины: `lines = 1 + #{threshold > u}`.
        let low = 0;
        let high = list.length;
        while (low < high) {
          const middle = (low + high) >> 1;
          if (list[middle] <= usable) low = middle + 1;
          else high = middle;
        }
        const above = list.length - low;
        lines = wrap ? Math.min(limit, 1 + above) : 1;
      }
      if (entry.truncAt > usable) truncTotal += 1;
      if (lines > rowMax[row]) rowMax[row] = lines;
    }
  }

  let total = 0;
  for (let row = 0; row < rowCount; row += 1) {
    const height = rowMax[row] * LINE_HEIGHT_PX + ROW_PADDING_PX;
    total += height > MIN_ROW_HEIGHT_PX ? height : MIN_ROW_HEIGHT_PX;
  }
  return total + model.lambda * truncTotal;
}

/**
 * Приводит решение к бюджету: ширины уже не больше бюджета, остаток
 * распределяется пропорционально запасу до `maxShare`. Вызывается после
 * поиска: расширение колонки не может ухудшить `cost`.
 */
export function finalizeWidths(model, widths, contentWidth) {
  const out = { ...model.fixedWidths };
  for (const column of model.flexColumns) {
    out[column.id] = Math.round(widths[column.id]);
  }
  return distributeLeftover(model.columns, out, contentWidth);
}

/** Ширины по индексам сетки — то, что вернёт оптимизатор до `finalizeWidths`. */
export function widthsFromIndices(model, indices) {
  const widths = { ...model.fixedWidths };
  for (let c = 0; c < model.curves.length; c += 1) {
    widths[model.curves[c].column.id] = model.curves[c].candidates[indices[c]];
  }
  return widths;
}
