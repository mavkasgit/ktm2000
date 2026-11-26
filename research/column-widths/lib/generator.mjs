/**
 * Seeded-генератор синтетических листов предпросмотра.
 *
 * Профили повторяют реальные вызовы оптимизатора: обычный ОСВ, длинный хвост
 * наименований, один выброс, всё короткое, длинные артикулы без пробелов,
 * смесь алфавитов и пустые значения. Набор фиксируется seed, поэтому прогон
 * воспроизводим, а сравнение оптимизаторов честное.
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

const ERROR_TEXTS = [
  "Пропущено: есть в исключениях",
  "Неизвестный участок",
  "Остаток меньше одной штуки",
  "Артикул не найден в каталоге",
  "Дубликат строки 12 из плана",
  "Не удалось определить длину: нет габарита в справочнике",
  "Строка 48: остаток меньше одной штуки; участок не найден в справочнике; дубликат по артикулу и длине",
];

const LONG_ERROR =
  "Строка 128: остаток меньше одной штуки, участок не найден в справочнике, дубликат по артикулу и длине, " +
  "качество не определено, операция завершена с браком, требуется ручная проверка оператором";

const SECTION_NAMES = [
  "Склад готовой продукции",
  "Склад сырья",
  "Дробеструй",
  "Склад полуфабриката",
  "Упаковка",
  "Подготовительный участок",
];

const QUALITY_NAMES = ["Годный", "Брак", "Переделка", "Годный"];

function makeName(rng, profile) {
  const count =
    profile === "all-short" ? randInt(rng, 1, 2) : randInt(rng, 2, 4);
  const source = profile === "all-short" ? SHORT_WORDS : NAME_WORDS;
  return Array.from({ length: count }, () => pick(rng, source)).join(" ");
}

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

function makeMixedName(rng) {
  const parts = [];
  const count = randInt(rng, 2, 4);
  for (let i = 0; i < count; i += 1) {
    parts.push(rng() < 0.5 ? pick(rng, MIXED_WORDS) : pick(rng, NAME_WORDS));
  }
  return parts.join(" ");
}

function makeSku(rng, profile) {
  if (profile === "mono") {
    const length = randInt(rng, 12, 24).toString();
    return `ALS-${length}${"X".repeat(randInt(rng, 2, 6))}-${randInt(rng, 100, 999)}`;
  }
  return `${pick(rng, ["ALS", "AT", "КР", "РП", "JD", "OPS"])}-${randInt(rng, 10, 9999)}`;
}

function makeCode(rng, profile) {
  if (profile === "mono") return `${randInt(rng, 100000, 999999)}-${randInt(rng, 10, 99)}`;
  return String(randInt(rng, 10000, 99999));
}

function makePills(rng, profile) {
  const count =
    profile === "outlier" && rng() < 0.5
      ? 6
      : profile === "all-short"
        ? 1
        : randInt(rng, 1, 4);
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

function makeError(rng, profile) {
  if (profile === "empty") return rng() < 0.4 ? "" : pick(rng, ERROR_TEXTS);
  if (profile === "long-tail") return rng() < 0.12 ? LONG_ERROR : pick(rng, ERROR_TEXTS);
  if (rng() < 0.06) return pick(rng, ERROR_TEXTS);
  if (rng() < 0.015) return LONG_ERROR;
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
      return makeName(rng, "all-short");
    case "mixed":
      return makeMixedName(rng);
    default:
      return makeName(rng, profile);
  }
}

function applyEmpty(rng, value) {
  if (Array.isArray(value)) return rng() < 0.2 ? [] : value;
  if (typeof value !== "string") return value;
  return rng() < 0.3 ? "" : value;
}

function applyOutlier(row, columns) {
  for (const column of columns) {
    if (column.kind === "numeric" || column.kind === "control") continue;
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
    row.values[column.id] =
      "Алюминиевая декоративная вставка 5,3*6 ZU2.0-5.5 T1.8L 2,7м с покрытием " +
      "под дерево и защитной плёнкой, партия № 4471, паллета 12";
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
