/**
 * Seeded-генератор синтетических листов предпросмотра.
 *
 * Профили повторяют реальные вызовы оптимизатора: обычный ОСВ, длинный хвост
 * наименований, один выброс, всё короткое, длинные артикулы без пробелов,
 * смесь алфавитов и пустые значения. Набор фиксируется seed, поэтому прогон
 * воспроизводим, а сравнение оптимизаторов честное.
 *
 * Калибровка (тикет #477) — по реальной выборке без персональных данных:
 * `docs/catalog/ktm-profile-register.csv` (216 наименований и артикулов из
 * прод-каталога, снимок 2026-11-26) и тексты ошибок предпросмотра из
 * `backend/app/stock/import_service.py` / `import_1c_osv.py` (ручная выборка
 * 14 сообщений). Целевые перцентили длин — в `CALIBRATION`; тесты сверяют с
 * ними сгенерированные листы, а не точную последовательность PRNG.
 */
import { createRng, logNormal, pick, randInt } from "./prng.mjs";

export const PROFILES = [
  "realistic",
  "long-tail",
  "outlier",
  "all-short",
  "mono",
  "mixed",
  "empty",
];

/**
 * Границы профилей. Экспортируются, чтобы тесты проверяли те же числа, по
 * которым генератор строит данные, а не дублировали литералы.
 */
export const ALL_SHORT_MAX_LENGTH = 25;
export const OUTLIER_TEXT_MIN_LENGTH = 100;
export const OUTLIER_PILL_COUNT = 6;
/** Потолок обычного наименования: не должен сам попадать в «выбросы». */
export const MAX_NAME_LENGTH = 72;

/**
 * Измеренные перцентили длин (символы) по реальной выборке.
 *
 * `sample` — сколько значений попало в выборку, `max` — максимум.
 * `errors` — только непустые тексты ошибок: в предпросмотре пустая ячейка
 * встречается чаще, чем ошибка, и её длина ничего не говорит о тексте.
 */
export const CALIBRATION = {
  source:
    "docs/catalog/ktm-profile-register.csv (216 наименований и артикулов, " +
    "снимок 2026-11-26) + тексты ошибок из backend/app/stock/import_*.py",
  sampledAt: "2026-11-26",
  name: { p50: 12, p90: 25.5, p99: 46.8, max: 59, sample: 216 },
  sku: { p50: 7, p90: 7, p99: 13, max: 13, sample: 216 },
  errors: { p50: 32.5, p90: 53.2, p99: 71, max: 73, sample: 14 },
};

const NAME_WORDS = [
  "Плинтус",
  "алюминиевый",
  "профиль",
  "вставка",
  "декоративная",
  "уголок",
  "полоса",
  "кант",
  "порог",
  "наличник",
  "планка",
  "труба",
  "заглушка",
  "соединитель",
  "держатель",
  "панель",
  "рейка",
  "окантовка",
  "молдинг",
  "штанга",
];

const SHORT_WORDS = ["Кант", "Плинтус", "Уголок", "Полоса", "Рейка", "Профиль"];

const MIXED_WORDS = [
  "ALS",
  "AT",
  "ZU2.0-5.5",
  "JD",
  "РП-АКП",
  "T1.8L",
  "2,7м",
  "ПВХ",
  "AL-6060",
  "КР-01",
];

const OPERATION_PILLS = [
  "Дробеструй",
  "Чёрный",
  "Золото",
  "Спанбонд",
  "Серебро",
  "Гребенка",
  "Окно",
  "Упаковка",
  "Пиление",
  "Шлифовка",
  "Полировка",
  "Грунт",
];

/** Реальные тексты предпросмотра: `_preview_errors_label`, `_invalidate`. */
const SHORT_ERRORS = [
  "Пропущено: есть в исключениях",
  "Пропущено: нет совпадения",
  "Количество не является числом",
  "Отрицательный остаток",
  "У артикула не указана длина",
  "Остаток меньше одной штуки",
  "Не указана единица измерения",
  "Маршрут не собран: участок не найден",
  "Цвет 07 не найден в справочнике операций",
  "ПФ без цвета: не удалось определить цвет",
];

const MEDIUM_ERRORS = [
  "Единица измерения 'упак' не поддерживается",
  "Количество не является числом, Отрицательный остаток",
  "Артикул неоднозначен: ALS-1103, ALS-1104",
  "В наименовании не указана длина, у артикула несколько длин",
  "Код 12345 не привязан к артикулу, сопоставление по наименованию запрещено",
];

const LONG_ERRORS = [
  "Строка 48: остаток меньше одной штуки; участок не найден в справочнике; дубликат по артикулу и длине",
  "Строка 128: остаток меньше одной штуки, участок не найден в справочнике, дубликат по артикулу и длине, " +
    "качество не определено, операция завершена с браком, требуется ручная проверка оператором",
];

/** all-short обещает не длиннее 25 символов — значит, и ошибки тоже. */
const ALL_SHORT_ERRORS = [
  "Нет совпадения",
  "Нет артикула",
  "Нет участка",
  "Нет длины",
  "Нет цвета",
  "Не число",
];

const SECTION_NAMES = [
  "Склад готовой продукции",
  "Склад сырья",
  "Дробеструй",
  "Склад полуфабриката",
  "Упаковка",
  "Подготовительный участок",
];

const QUALITY_NAMES = ["Годный", "Брак", "Переделка", "Годный"];

const OUTLIER_NAME =
  "Алюминиевая декоративная вставка 5,3*6 ZU2.0-5.5 T1.8L 2,7м с покрытием " +
  "под дерево и защитной плёнкой, партия № 4471, паллета 12";

const OUTLIER_ERROR =
  "Строка 128: остаток меньше одной штуки, участок не найден в справочнике, " +
  "дубликат по артикулу и длине, качество не определено, операция завершена " +
  "с браком, требуется ручная проверка оператором";

/**
 * Наименование «как в каталоге»: длина тянется из log-normal с медианой 9 и
 * σ 0.62, слова подбираются до цели и не выходят за MAX_NAME_LENGTH. Это даёт
 * p50/p90/p99 ≈ 12/23/45 при измеренных 12/25,5/46,8.
 */
function makeRealisticName(rng) {
  const target = Math.min(MAX_NAME_LENGTH, Math.max(4, Math.round(logNormal(rng, 9, 0.62))));
  const words = [];
  let length = 0;
  while (length < target) {
    const word = pick(rng, NAME_WORDS);
    const nextLength = words.length === 0 ? word.length : length + 1 + word.length;
    if (nextLength > MAX_NAME_LENGTH) break;
    if (words.length > 0 && nextLength > target + 8) break;
    words.push(word);
    length = nextLength;
  }
  if (words.length === 0) words.push(pick(rng, NAME_WORDS));
  return words.join(" ");
}

/** Длинный хвост: p50/p90/p99 ≈ 3× реалистичных — стресс, а не калибровка. */
function makeLongTailName(rng) {
  const target = Math.round(logNormal(rng, 34, 0.65));
  const words = [];
  let length = 0;
  while (length < target) {
    const word = pick(rng, NAME_WORDS);
    words.push(word);
    length += word.length + 1;
  }
  return words.join(" ");
}

function makeAllShortName(rng) {
  const count = randInt(rng, 1, 2);
  return Array.from({ length: count }, () => pick(rng, SHORT_WORDS)).join(" ");
}

function makeMixedName(rng) {
  const target = Math.max(6, Math.round(logNormal(rng, 12, 0.55)));
  const parts = [];
  let length = 0;
  while (length < target) {
    const word = rng() < 0.5 ? pick(rng, MIXED_WORDS) : pick(rng, NAME_WORDS);
    const nextLength = parts.length === 0 ? word.length : length + 1 + word.length;
    if (nextLength > MAX_NAME_LENGTH) break;
    parts.push(word);
    length = nextLength;
  }
  if (parts.length === 0) parts.push(pick(rng, MIXED_WORDS));
  return parts.join(" ");
}

function makeSku(rng, profile) {
  if (profile === "mono") {
    const length = randInt(rng, 12, 24).toString();
    return `ALS-${length}${"X".repeat(randInt(rng, 2, 6))}-${randInt(rng, 100, 999)}`;
  }
  const base = `${pick(rng, ["ALS", "AT", "КР", "РП", "JD", "OPS"])}-${randInt(rng, 100, 9999)}`;
  // Измеренный артикул короткий (p90 = 7), но p99 тянется до 13 символов:
  // редкие исполнения с суффиксом, а не общий длинный хвост.
  if (rng() < 0.03) return `${base}-${randInt(rng, 10, 99)}`;
  if (rng() < 0.02) return `${base}-${randInt(rng, 10, 99)},${randInt(rng, 1, 9)}`;
  return base;
}

function makeCode(rng, profile) {
  if (profile === "mono") return `${randInt(rng, 100000, 999999)}-${randInt(rng, 10, 99)}`;
  return String(randInt(rng, 10000, 99999));
}

function makePills(rng, profile) {
  const count = profile === "all-short" ? 1 : randInt(rng, 1, 4);
  const used = new Set();
  const pills = [];
  while (pills.length < count) {
    const pill = pick(rng, OPERATION_PILLS);
    if (used.has(pill)) continue;
    used.add(pill);
    pills.push(pill);
  }
  return pills;
}

/**
 * Ошибки: в `realistic` — измеренные короткие и средние тексты (p99 совпадает
 * с выборкой), в `long-tail` — редкие склеенные причины, в `all-short` — только
 * короткие. `outlier` получает лишь короткие, чтобы единственным выбросом
 * осталась ячейка, которую вставляет `applyOutlier`.
 */
function makeError(rng, profile) {
  if (profile === "all-short") return rng() < 0.06 ? pick(rng, ALL_SHORT_ERRORS) : "";
  if (profile === "empty") return rng() < 0.4 ? "" : pick(rng, MEDIUM_ERRORS);
  if (profile === "long-tail") {
    if (rng() >= 0.4) return "";
    return rng() < 0.35 ? pick(rng, LONG_ERRORS) : pick(rng, MEDIUM_ERRORS);
  }
  if (profile === "outlier") return rng() < 0.06 ? pick(rng, SHORT_ERRORS) : "";
  if (rng() < 0.06) return rng() < 0.7 ? pick(rng, SHORT_ERRORS) : pick(rng, MEDIUM_ERRORS);
  return "";
}

function makeValue(rng, column, profile) {
  if (column.kind === "pills") return makePills(rng, profile);
  if (column.kind === "control") {
    if (column.id === "quality") return pick(rng, QUALITY_NAMES);
    if (column.id === "section") return pick(rng, SECTION_NAMES);
  }
  if (column.kind === "numeric") {
    switch (column.id) {
      case "row":
        return String(randInt(rng, 2, 5000));
      case "quantity":
        return String(randInt(rng, 1, 2500));
      case "meters":
        return `${randInt(rng, 1, 9999)},${randInt(rng, 0, 9)}`;
      case "length":
        return `${randInt(rng, 1, 6)},${randInt(rng, 0, 9)} м`;
      default:
        return String(randInt(rng, 1, 999));
    }
  }
  if (column.id === "source_code") return makeCode(rng, profile);
  if (column.id === "sku") return makeSku(rng, profile);
  if (column.id === "errors") return makeError(rng, profile);

  // Наименование и generic-текст.
  switch (profile) {
    case "long-tail":
      return makeLongTailName(rng);
    case "all-short":
      return makeAllShortName(rng);
    case "mixed":
      return makeMixedName(rng);
    default:
      return makeRealisticName(rng);
  }
}

function applyEmpty(rng, value) {
  if (Array.isArray(value)) return rng() < 0.2 ? [] : value;
  if (typeof value !== "string") return value;
  return rng() < 0.3 ? "" : value;
}

/**
 * Ровно один выброс на текстовую колонку и одна «широкая» строка операций.
 * Числовые и mono-колонки не трогаем: длинный артикул или код — это не выброс
 * реального листа, а другой профиль (`mono`).
 */
function applyOutlier(row, columns) {
  for (const column of columns) {
    if (column.kind === "pills") {
      row.values[column.id] = [
        "Дробеструй",
        "Чёрный",
        "Золото",
        "Спанбонд",
        "Серебро",
        "Гребенка",
      ];
      continue;
    }
    if (column.kind !== "text") continue;
    row.values[column.id] = column.id === "errors" ? OUTLIER_ERROR : OUTLIER_NAME;
  }
}

/**
 * @returns {{ columns: import("./columns.mjs").PREVIEW_COLUMNS[number][], rows: { values: Record<string, string | string[]> }[] }}
 */
export function generateSheet({ profile = "realistic", rows = 1000, columns, seed = 1 }) {
  const rng = createRng(seed);
  const resultRows = [];
  for (let index = 0; index < rows; index += 1) {
    const values = {};
    for (const column of columns) {
      let value = makeValue(rng, column, profile);
      if (profile === "empty") value = applyEmpty(rng, value);
      values[column.id] = value;
    }
    resultRows.push({ values });
  }
  if (profile === "outlier" && resultRows.length > 0) {
    applyOutlier(resultRows[0], columns);
  }
  return { columns, rows: resultRows, profile, seed };
}
