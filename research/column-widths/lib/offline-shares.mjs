/**
 * Оффлайн-доли (#487): один вектор долей гибких колонок, посчитанный без
 * браузера, и таблица по 2–3 бакетам ширины.
 *
 * Мотив. Если рантайм-пересчёт (#483) не уложится в 100 мс, запасной исход —
 * зашить доли константой. Порог §15 сравнивает такую константу не с оптимумом
 * на каждой ширине, а с **текущими продуктовыми долями** (15/21) при полном
 * тексте: ≥4% суммарной высоты или ≥1 п.п. обрезки.
 *
 * Вектор — результат #482: 38.00 / 16.58 / 45.42% бюджета гибких колонок.
 * Здесь он зафиксирован константой, чтобы отчёт и #483 говорили об одних и тех
 * же числах, а не о результате повторного поиска. Пересчёт по сетке профилей и
 * ширин остаётся диагностикой (`fit` в `runOfflineShares`): расхождение с
 * константой видно, но константа не меняется от прогона к прогону.
 *
 * Текст и пилюли считаются раздельно. Полный текст (`clamp = ∞`) не теряет
 * текстовых ячеек, а «Операции» — `nowrap`-пилюли: сужение колонки не добавляет
 * строк, а прячет подпись в `title`. Поэтому высота и обрезка пилюль — разные
 * метрики, и порог §15 проверяется по каждой отдельно.
 */
import {
  CELL_PADDING_PX,
  SERVICE_WIDTH_PX,
  maxWidth,
} from "./columns.mjs";
import { effectiveMinWidth } from "./curves.mjs";
import { evaluate, measureCell } from "./evaluate.mjs";
import { robustShares } from "./robust.mjs";

/**
 * Вектор #482, доли бюджета гибких колонок (`source_name` + `operations` +
 * `errors` = 1). Именно эти числа зашиваются, если рантайм не проходит.
 *
 * Цена: высота против текущих долей −8.17% (seed 1), но обрезка пилюль растёт
 * с 14.18% до 61.81% (+47.63 п.п.): вектор экономит высоту, сужая «Операции».
 * Порог §15 формально пройден по высоте; допустимость пилюль решает #485.
 * Без этого решения константу в продукт не переносить.
 */
export const OFFLINE_FLEX_SHARES = Object.freeze({
  source_name: 0.38,
  operations: 0.1658,
  errors: 0.4542,
});

/** Откуда вектор: отчёт #482, средний gap 1.28%, худший 6.80% к оптимуму. */
export const OFFLINE_FLEX_SHARES_SOURCE =
  "#482: 38.00 / 16.58 / 45.42% гибкого бюджета";

/**
 * Текущая продуктовая обрезка пилюль по ширине таблицы (#487, seed 1, среднее
 * по профилям): предел режима «не хуже текущего фикса» в #488. Числа — не
 * эталон «правильной» обрезки, а факт продукта: 1180 — треть строк, 1920 —
 * практически ноль.
 */
export const PILLS_CURRENT_LIMIT_PCT = Object.freeze({
  1180: 32.79,
  1400: 19.49,
  1500: 12.97,
  1600: 5.64,
  1920: 0.01,
});

/** Строгий режим #488: ≤5% строк с обрезанными пилюлями на любой W. */
export const PILLS_STRICT_LIMIT_PCT = 5;

export const PILLS_LIMIT_MODES = Object.freeze(["current", "strict"]);

const PILLS_CURRENT_POINTS = Object.entries(PILLS_CURRENT_LIMIT_PCT)
  .map(([width, limit]) => [Number(width), limit])
  .sort((a, b) => a[0] - b[0]);

/**
 * Предел обрезки пилюль по ширине: для режима «не хуже текущего» — линейная
 * интерполяция продуктовой кривой (в таблицу попадают и промежуточные W), вне
 * диапазона — ближайшая точка. Строгий режим не зависит от W.
 */
export function pillsLimitPctForWidth(tableWidth, mode = "current") {
  if (mode === "strict") return PILLS_STRICT_LIMIT_PCT;
  const points = PILLS_CURRENT_POINTS;
  if (tableWidth <= points[0][0]) return points[0][1];
  const last = points[points.length - 1];
  if (tableWidth >= last[0]) return last[1];
  for (let index = 1; index < points.length; index += 1) {
    const [rightWidth, rightLimit] = points[index];
    if (tableWidth <= rightWidth) {
      const [leftWidth, leftLimit] = points[index - 1];
      const ratio = (tableWidth - leftWidth) / (rightWidth - leftWidth);
      return leftLimit + (rightLimit - leftLimit) * ratio;
    }
  }
  return last[1];
}

/** То же в долях строк — формат `pillsMaxTruncatedShare` модели. */
export function pillsLimitForWidth(tableWidth, mode = "current") {
  return pillsLimitPctForWidth(tableWidth, mode) / 100;
}

/** Границы бакетов — по ширине таблицы (включая 68 px служебных колонок). */
export const OFFLINE_BUCKET_PLANS = Object.freeze({
  two: {
    label: "2 бакета",
    buckets: [
      { maxTableWidth: 1600, fitWidths: [1180, 1400, 1500, 1600] },
      { maxTableWidth: Number.POSITIVE_INFINITY, fitWidths: [1600, 1920] },
    ],
  },
  three: {
    label: "3 бакета",
    buckets: [
      { maxTableWidth: 1280, fitWidths: [1180, 1280] },
      { maxTableWidth: 1600, fitWidths: [1280, 1400, 1500, 1600] },
      { maxTableWidth: Number.POSITIVE_INFINITY, fitWidths: [1600, 1920] },
    ],
  },
});

/**
 * Индекс бакета по ширине таблицы. Границы полуоткрытые: `W ≤ max` попадает
 * в текущий бакет, следующая ширина — в следующий. На самих границах обе
 * соседние раскладки проверяются отдельно (`bucketSwitchChecks`).
 */
export function bucketIndexForTableWidth(tableWidth, plan) {
  for (let index = 0; index < plan.buckets.length; index += 1) {
    if (tableWidth <= plan.buckets[index].maxTableWidth) return index;
  }
  return plan.buckets.length - 1;
}

/** То же по ширине контента (ResizeObserver в продукте видит её). */
export function bucketIndexForContentWidth(contentWidth, plan) {
  return bucketIndexForTableWidth(contentWidth + SERVICE_WIDTH_PX, plan);
}

/** Ширины в процентах от `W`: то, что кладётся в `<colgroup>`. */
export function contentShares(tableWidth, widths) {
  const contentWidth = tableWidth - SERVICE_WIDTH_PX;
  const out = {};
  for (const [id, width] of Object.entries(widths)) {
    out[id] = width / contentWidth;
  }
  return out;
}

/**
 * Доли одного бакета: `robustShares` по сценариям, попавшим в его диапазон.
 * В `fitWidths` включены обе границы соседних бакетов — иначе вектор,
 * подобранный в середине диапазона, мог бы нарушить `minPx` у края.
 */
export function fitBucketShares(scenarios, plan, options = {}) {
  return plan.buckets.map((bucket, index) => {
    const subset = scenarios.filter((scenario) =>
      bucket.fitWidths.includes(scenario.tableWidth),
    );
    if (subset.length === 0) {
      throw new Error(
        `fitBucketShares: бакет ${index} не получил ни одного сценария`,
      );
    }
    const result = robustShares(subset, options);
    return {
      index,
      maxTableWidth: bucket.maxTableWidth,
      fitWidths: [...bucket.fitWidths],
      shares: result.shares,
      bounds: result.bounds,
      meanGapPct: result.meanGapPct,
      worstGapPct: result.worstGapPct,
      seed: result.seed,
      objective: result.objective,
    };
  });
}

/**
 * Высота и две независимые политики обрезки для произвольных ширин:
 * `textTruncatedSharePct` — только текстовые колонки (потерянный текст),
 * `pillTruncatedSharePct` — только пилюли (`title`, не потеря текста).
 */
export function policyMetrics(prepared, widths) {
  const metrics = evaluate(prepared, widths, { lambda: 0, collectRows: true });
  let textCells = 0;
  let textTruncated = 0;
  let pillCells = 0;
  let pillTruncated = 0;

  prepared.columns.forEach((column, index) => {
    if (column.kind !== "text" && column.kind !== "pills") return;
    const usable = widths[column.id] - CELL_PADDING_PX;
    for (const row of prepared.rows) {
      if (column.kind === "text") {
        textCells += 1;
        if (measureCell(prepared.measurer, row[index], usable).truncated) {
          textTruncated += 1;
        }
      } else {
        pillCells += 1;
        if (measureCell(prepared.measurer, row[index], usable).truncated) {
          pillTruncated += 1;
        }
      }
    }
  });

  return {
    height: metrics.totalHeight,
    meanHeight: metrics.meanHeight,
    p95Height: metrics.p95Height,
    maxHeight: metrics.maxHeight,
    textCells,
    textTruncatedCells: textTruncated,
    textTruncatedSharePct: (textTruncated / (textCells || 1)) * 100,
    pillCells,
    pillTruncatedCells: pillTruncated,
    pillTruncatedSharePct: (pillTruncated / (pillCells || 1)) * 100,
  };
}

/**
 * Нарушения `minPx`/`maxShare` и динамического минимума
 * `max(minPx, maxWordWidth + padding)` (#479/H4). `maxWordWidths` — Map из
 * `columnMaxWordWidths`, если нужен честный минимум для конкретного листа.
 */
export function widthViolations(columns, widths, contentWidth, maxWordWidths = null) {
  const violations = [];
  for (const column of columns) {
    if (widths[column.id] < column.minPx - 0.5) {
      violations.push({
        column: column.id,
        kind: "minPx",
        width: widths[column.id],
        limit: column.minPx,
      });
    }
    if (column.wrap && maxWordWidths) {
      const effective = effectiveMinWidth(
        column,
        maxWordWidths.get(column.id) ?? 0,
      );
      if (widths[column.id] < effective - 0.5) {
        violations.push({
          column: column.id,
          kind: "effectiveMin",
          width: widths[column.id],
          limit: effective,
        });
      }
    }
    const cap = maxWidth(column, contentWidth);
    if (Number.isFinite(cap) && widths[column.id] > cap + 0.5) {
      violations.push({
        column: column.id,
        kind: "maxShare",
        width: widths[column.id],
        limit: cap,
      });
    }
  }
  return violations;
}
