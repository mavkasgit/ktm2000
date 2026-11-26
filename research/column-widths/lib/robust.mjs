/**
 * Робастный вектор долей: один набор долей на все профили и сетку ширин `W'`.
 *
 * Мотив (#482). Если доли выбраны под одну опорную ширину `W0`, при ресайзе
 * таблица в процентах масштабируется пропорционально. Вопрос — сколько это
 * стоит против раскладки, оптимальной на самой `W'`. Робастный вектор отвечает
 * на него один раз: ищем доли, которые минимизируют средний (и худший) gap к
 * оптимуму по сетке профилей × ширин. Такой вектор можно зашить константой
 * (вариант «б» в #482) и не пересчитывать на ресайзе.
 *
 * Доли гибких колонок считаются от бюджета гибких (`flexBudget`), потому что
 * фиксированные колонки в продукте всегда стоят на своих продуктовых долях.
 * Сумма долей — 1. Для `<colgroup>` те же числа переводятся в долю контента:
 * `доля × flexBudget / contentWidth`.
 *
 * Оценка идёт по кэшу порогов (`costAtWidths` в `lib/curves.mjs`), поэтому
 * перебор долей не пересчитывает текст. Поиск детерминирован: кандидаты,
 * стартовые точки и порядок обхода фиксированы.
 */
import { maxWidth } from "./columns.mjs";
import {
  buildCostModel,
  costAtWidths,
  fixedAssignments,
} from "./curves.mjs";
import { searchOptimizer } from "./optimizers.mjs";

/** Допуск сравнения долей: 1e-5 — меньше шага продуктовых процентов. */
const SHARE_EPSILON = 1e-5;

function flexColumnsOf(columns) {
  return columns.filter((column) => column.flex);
}

/**
 * Доли гибких колонок относительно бюджета гибких. Сумма = 1, если ширины
 * заполняют бюджет (оптимизатор это гарантирует).
 */
export function flexSharesFromWidths(columns, contentWidth, widths) {
  const { flexBudget } = fixedAssignments(columns, contentWidth);
  const shares = {};
  for (const column of flexColumnsOf(columns)) {
    shares[column.id] = widths[column.id] / flexBudget;
  }
  return shares;
}

/** Ширины всех колонок по долям гибких: фиксированные — продуктовые. */
export function widthsFromFlexShares(columns, contentWidth, shares) {
  const { fixedWidths, flexBudget } = fixedAssignments(columns, contentWidth);
  const widths = { ...fixedWidths };
  for (const column of flexColumnsOf(columns)) {
    widths[column.id] = shares[column.id] * flexBudget;
  }
  return widths;
}

/** Продуктовые доли гибких колонок, нормированные в 1. */
export function baselineFlexShares(columns) {
  const flex = flexColumnsOf(columns);
  const total = flex.reduce((sum, column) => sum + column.baselineShare, 0) || 1;
  const shares = {};
  for (const column of flex) shares[column.id] = column.baselineShare / total;
  return shares;
}

/**
 * Доли всех колонок от ширины контента — то, что нужно для `<colgroup>`:
 * фиксированные остаются на продуктовых долях, гибкие получают
 * `flexShare × flexBudget / contentWidth`.
 */
export function contentSharesFromFlexShares(columns, contentWidth, shares) {
  const { fixedWidths, flexBudget } = fixedAssignments(columns, contentWidth);
  const out = {};
  for (const column of columns) {
    out[column.id] = column.flex
      ? (shares[column.id] * flexBudget) / contentWidth
      : fixedWidths[column.id] / contentWidth;
  }
  return out;
}

function sumShares(ids, shares) {
  return ids.reduce((sum, id) => sum + shares[id], 0);
}

/** Нормирует доли в 1; при нулевой сумме раздаёт поровну. */
export function normalizeShares(ids, shares) {
  const total = sumShares(ids, shares);
  const out = {};
  if (!Number.isFinite(total) || total <= 0) {
    for (const id of ids) out[id] = 1 / ids.length;
    return out;
  }
  for (const id of ids) out[id] = shares[id] / total;
  return out;
}

/**
 * Один сценарий для робастного поиска: лист, ширина, кэш кривых и эталон
 * `search` на этой же ширине. `referenceCost` считается тем же
 * `costAtWidths`, каким будет оцениваться робастный вектор, — сравнение
 * честное, без подмены `cost`.
 */
export function buildRobustScenario({
  prepared,
  contentWidth,
  lambda = 0,
  rowLimit = 500,
  maxCandidates = 12,
  profile = null,
  tableWidth = null,
}) {
  const columns = prepared.columns;
  const model = buildCostModel(prepared, contentWidth, {
    lambda,
    rowLimit,
    maxCandidates,
  });
  const reference = searchOptimizer(prepared, contentWidth, {
    lambda,
    rowLimit,
    maxCandidates,
  });
  const referenceCost = costAtWidths(model, reference.widths);

  const flex = model.flexColumns;
  const lower = {};
  const upper = {};
  for (const column of flex) {
    lower[column.id] = model.minimums[column.id] / model.flexBudget;
    const cap = maxWidth(column, contentWidth);
    upper[column.id] = Number.isFinite(cap) ? cap / model.flexBudget : 1;
  }

  return {
    profile,
    tableWidth,
    prepared,
    columns,
    contentWidth,
    model,
    reference,
    referenceCost,
    flex: flex.map((column) => column.id),
    lower,
    upper,
  };
}

/** Мягкая проверка: доля уважает `minPx`/`maxShare` в этом сценарии. */
function shareViolations(scenario, shares) {
  const violations = [];
  for (const id of scenario.flex) {
    if (shares[id] < scenario.lower[id] - SHARE_EPSILON) {
      violations.push({ column: id, kind: "min", share: shares[id] });
    }
    if (shares[id] > scenario.upper[id] + 1e-9) {
      violations.push({ column: id, kind: "maxShare", share: shares[id] });
    }
  }
  return violations;
}

/**
 * Сводные ограничения по всем сценариям: одна доля должна попадать в
 * пересечение `[min, maxShare]` каждой ширины. Если пересечение пустое —
 * вектор физически не может уважать минимумы на всех `W'`; это фиксируется,
 * а не прячется.
 */
function aggregateBounds(scenarios, ids) {
  const lower = {};
  const upper = {};
  for (const id of ids) {
    lower[id] = Math.max(...scenarios.map((scenario) => scenario.lower[id]));
    upper[id] = Math.min(...scenarios.map((scenario) => scenario.upper[id]));
  }
  const feasible = ids.every((id) => lower[id] <= upper[id] + SHARE_EPSILON);
  return { lower, upper, feasible };
}

function collectCandidates(scenarios, ids, bounds) {
  const sets = {};
  for (const id of ids) {
    const values = [];
    for (const scenario of scenarios) {
      const curve = scenario.model.curves.find(
        (item) => item.column.id === id,
      );
      for (const width of curve.candidates) {
        values.push(width / scenario.model.flexBudget);
      }
      values.push(
        scenario.reference.widths[id] / scenario.model.flexBudget,
      );
    }
    const low = bounds.lower[id];
    const high = bounds.upper[id];
    const kept = [];
    for (const value of values) {
      if (!Number.isFinite(value)) continue;
      if (value < low - SHARE_EPSILON) continue;
      if (value > high + SHARE_EPSILON) continue;
      kept.push(Math.round(value / SHARE_EPSILON) * SHARE_EPSILON);
    }
    kept.sort((a, b) => a - b);
    const unique = [];
    for (const value of kept) {
      if (unique.length === 0 || value - unique[unique.length - 1] > SHARE_EPSILON) {
        unique.push(value);
      }
    }
    sets[id] = unique;
  }
  return sets;
}

function scenarioGap(scenario, shares) {
  const widths = widthsFromFlexShares(
    scenario.columns,
    scenario.contentWidth,
    shares,
  );
  const cost = costAtWidths(scenario.model, widths);
  const raw = (cost / scenario.referenceCost - 1) * 100;
  return {
    raw,
    gap: Math.max(0, raw),
    cost,
    widths,
  };
}

/**
 * Средняя/худшая стоимость вектора по сценариям (в % от оптимума `search`).
 * `raw` может быть отрицательным: `search` — эвристика, вектор вправе её
 * обойти. Для отчёта gap не отрицательный (ноль = оптимум достигнут).
 */
export function scoreShares(scenarios, shares) {
  const gaps = [];
  let mean = 0;
  let worst = 0;
  let worstIndex = -1;
  const perScenario = [];
  for (let index = 0; index < scenarios.length; index += 1) {
    const scenario = scenarios[index];
    const result = scenarioGap(scenario, shares);
    mean += result.gap;
    if (result.gap > worst) {
      worst = result.gap;
      worstIndex = index;
    }
    gaps.push(result.gap);
    perScenario.push({
      gapPct: result.gap,
      cost: result.cost,
      violations: shareViolations(scenario, shares),
      widths: result.widths,
    });
  }
  mean /= Math.max(1, scenarios.length);
  return { mean, worst, worstIndex, gaps, perScenario };
}

function isBetter(candidate, incumbent, objective) {
  if (!incumbent) return true;
  if (objective === "worst") {
    if (candidate.worst < incumbent.worst - 1e-9) return true;
    if (Math.abs(candidate.worst - incumbent.worst) <= 1e-9) {
      return candidate.mean < incumbent.mean - 1e-9;
    }
    return false;
  }
  if (objective === "balanced") {
    const a = candidate.mean + candidate.worst;
    const b = incumbent.mean + incumbent.worst;
    if (a < b - 1e-9) return true;
    if (Math.abs(a - b) <= 1e-9) return candidate.worst < incumbent.worst - 1e-9;
    return false;
  }
  // "mean" (по умолчанию)
  if (candidate.mean < incumbent.mean - 1e-9) return true;
  if (Math.abs(candidate.mean - incumbent.mean) <= 1e-9) {
    return candidate.worst < incumbent.worst - 1e-9;
  }
  return false;
}

/**
 * Координатный спуск по долям. Для колонки перебираются доли кандидатов;
 * остаток бюджета раздаётся другим колонкам пропорционально текущим долям,
 * поэтому сумма всегда 1. Жадный шаг принимается только при улучшении
 * выбранной цели.
 */
function descend(scenarios, ids, candidates, seed, objective, bounds, maxSweeps) {
  let current = normalizeShares(ids, seed);
  let currentScore = scoreShares(scenarios, current);
  let improved = true;
  let sweeps = 0;

  while (improved && sweeps < maxSweeps) {
    improved = false;
    sweeps += 1;
    for (const id of ids) {
      const others = ids.filter((other) => other !== id);
      const othersSum = sumShares(others, current);
      let bestScore = currentScore;
      let bestShares = current;

      for (const value of candidates[id]) {
        if (value < bounds.lower[id] - SHARE_EPSILON) continue;
        if (value > bounds.upper[id] + 1e-9) continue;
        const rest = 1 - value;
        if (rest < -SHARE_EPSILON) continue;
        const next = { ...current, [id]: value };
        let ok = true;
        if (others.length === 0) {
          ok = Math.abs(rest) <= SHARE_EPSILON;
        } else if (othersSum <= SHARE_EPSILON) {
          for (const other of others) next[other] = rest / others.length;
        } else {
          for (const other of others) {
            const share = (current[other] * rest) / othersSum;
            next[other] = share;
            if (share < bounds.lower[other] - SHARE_EPSILON) ok = false;
            if (share > bounds.upper[other] + 1e-9) ok = false;
          }
        }
        if (!ok) continue;
        const score = scoreShares(scenarios, next);
        if (isBetter(score, bestScore, objective)) {
          bestScore = score;
          bestShares = next;
        }
      }

      if (bestShares !== current) {
        current = bestShares;
        currentScore = bestScore;
        improved = true;
      }
    }
  }

  return { shares: current, score: currentScore, sweeps };
}

function seedVectors(scenarios, ids) {
  const seeds = [];
  const columns = scenarios[0].columns;
  seeds.push({ label: "baseline", shares: baselineFlexShares(columns) });

  const mean = {};
  for (const id of ids) mean[id] = 0;
  for (const scenario of scenarios) {
    for (const id of ids) {
      mean[id] += scenario.reference.widths[id] / scenario.model.flexBudget;
    }
  }
  for (const id of ids) mean[id] /= scenarios.length;
  seeds.push({ label: "reference-mean", shares: normalizeShares(ids, mean) });

  const equal = {};
  for (const id of ids) equal[id] = 1 / ids.length;
  seeds.push({ label: "equal", shares: equal });

  return seeds;
}

/**
 * Робастный вектор: один набор долей гибких колонок (сумма 1).
 *
 * @param {Array} scenarios результаты `buildRobustScenario` по сетке
 *   профиль × ширина.
 * @param {{objectives?: string[], maxSweeps?: number}} options
 */
export function robustShares(scenarios, options = {}) {
  if (scenarios.length === 0) throw new Error("robustShares: нет сценариев");
  const ids = scenarios[0].flex;
  const objectives = options.objectives ?? ["mean", "worst", "balanced"];
  const maxSweeps = options.maxSweeps ?? 6;

  const bounds = aggregateBounds(scenarios, ids);
  const candidates = collectCandidates(scenarios, ids, bounds);
  // Стартовые доли и равномерное распределение обязаны остаться кандидатами,
  // иначе спуск не сможет к ним вернуться.
  const seeds = seedVectors(scenarios, ids);
  for (const seed of seeds) {
    for (const id of ids) {
      const value = Math.round(seed.shares[id] / SHARE_EPSILON) * SHARE_EPSILON;
      if (!candidates[id].some((item) => Math.abs(item - value) <= SHARE_EPSILON)) {
        candidates[id].push(value);
        candidates[id].sort((a, b) => a - b);
      }
    }
  }

  const runs = [];
  for (const seed of seeds) {
    for (const objective of objectives) {
      const result = descend(
        scenarios,
        ids,
        candidates,
        seed.shares,
        objective,
        bounds,
        maxSweeps,
      );
      runs.push({
        seed: seed.label,
        objective,
        shares: result.shares,
        mean: result.score.mean,
        worst: result.score.worst,
        sweeps: result.sweeps,
      });
    }
  }

  // Выбор одного вектора: сначала целевая метрика приёмки
  // `max(mean/2, worst/4)`, затем средний gap. Это ровно порог #482:
  // средний ≤2% и худший ≤4% эквивалентны `max(...) ≤ 1` в этих единицах.
  let best = null;
  for (const run of runs) {
    const key = Math.max(run.mean / 2, run.worst / 4);
    if (
      best === null ||
      key < best.key - 1e-9 ||
      (Math.abs(key - best.key) <= 1e-9 && run.mean < best.run.mean - 1e-9)
    ) {
      best = { key, run };
    }
  }

  const score = scoreShares(scenarios, best.run.shares);
  const contentSharesByWidth = {};
  for (const scenario of scenarios) {
    contentSharesByWidth[scenario.tableWidth] = contentSharesFromFlexShares(
      scenario.columns,
      scenario.contentWidth,
      best.run.shares,
    );
  }
  const contentShares =
    contentSharesByWidth[scenarios[0].tableWidth] ?? {};

  return {
    shares: best.run.shares,
    contentShares,
    contentSharesByWidth,
    bounds,
    candidates: Object.fromEntries(
      Object.entries(candidates).map(([id, values]) => [id, values.length]),
    ),
    seed: best.run.seed,
    objective: best.run.objective,
    meanGapPct: score.mean,
    worstGapPct: score.worst,
    runs: runs.map((run) => ({
      seed: run.seed,
      objective: run.objective,
      meanGapPct: run.mean,
      worstGapPct: run.worst,
      shares: run.shares,
    })),
    scenarios: scenarios.map((scenario, index) => ({
      profile: scenario.profile,
      tableWidth: scenario.tableWidth,
      contentWidth: scenario.contentWidth,
      referenceCost: scenario.referenceCost,
      gapPct: score.perScenario[index].gapPct,
      cost: score.perScenario[index].cost,
      violations: score.perScenario[index].violations,
      widths: score.perScenario[index].widths,
    })),
  };
}
