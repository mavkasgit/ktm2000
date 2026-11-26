/**
 * Метрики текста без DOM.
 *
 * В браузере эталон — canvas/pretext. В Node нужна детерминированная модель,
 * чтобы бенч был воспроизводим: ширина символа берётся из таблицы для 11px,
 * перенос — жадный по пробелам (ровно то, что делает `white-space: normal`).
 * Абсолютные пиксели здесь важны меньше, чем порядок ширин: оптимизатор
 * сравнивает раскладки между собой на одной и той же модели.
 */

const MONO_ADVANCE = 6.6;

/** Узкие/широкие символы для 11px sans; остальное — средняя ширина. */
const SANS_WIDTHS = new Map(
  Object.entries({
    " ": 3.0,
    "\t": 16,
    "\u00a0": 3.0,
    ".": 3.0,
    ",": 3.0,
    ":": 3.0,
    ";": 3.0,
    "!": 3.0,
    "'": 2.6,
    "|": 3.0,
    "(": 4.0,
    ")": 4.0,
    "[": 4.0,
    "]": 4.0,
    "-": 3.8,
    "–": 5.4,
    "—": 9.0,
    "/": 3.4,
    "\\": 3.8,
    "@": 8.8,
    "%": 8.4,
    "№": 8.0,
    "«": 5.0,
    "»": 5.0,
    "×": 5.6,
    "→": 7.0,
    "·": 3.4,
    "•": 4.0,
  }),
);

const NARROW_LATIN = new Set(["i", "l", "j", "t", "f", "r"]);
const WIDE_LATIN = new Set(["m", "w", "W", "M"]);
const WIDE_CYRILLIC = new Set(["м", "ш", "щ", "ж", "ю", "М", "Ш", "Щ", "Ж", "Ю", "Ф", "Ы"]);

export function charWidth(char, font = "sans") {
  if (font === "mono") return MONO_ADVANCE;
  const known = SANS_WIDTHS.get(char);
  if (known !== undefined) return known;
  if (char >= "0" && char <= "9") return 6.2;
  if (char >= "A" && char <= "Z") return WIDE_LATIN.has(char) ? 9.0 : 6.9;
  if (char >= "a" && char <= "z") {
    if (NARROW_LATIN.has(char)) return 3.0;
    return WIDE_LATIN.has(char) ? 8.8 : 5.7;
  }
  if (char >= "А" && char <= "я") {
    const upper = char >= "А" && char <= "Я";
    if (WIDE_CYRILLIC.has(char)) return 7.6;
    return upper ? 7.2 : 6.1;
  }
  return 6.0;
}

const naturalWidthCache = new Map();
const preparedCache = new Map();

export function naturalWidth(text, font = "sans") {
  const key = `${font}\u0000${text}`;
  const cached = naturalWidthCache.get(key);
  if (cached !== undefined) return cached;
  let width = 0;
  for (const char of text) width += charWidth(char, font);
  naturalWidthCache.set(key, width);
  return width;
}

/**
 * Одна подготовка текста на весь прогон: ширина, слова и самое длинное слово.
 * Аналог `prepare()` у pretext, только на табличных метриках.
 */
export function prepareText(text, font = "sans") {
  const value = text ?? "";
  const key = `${font}\u0000${value}`;
  const cached = preparedCache.get(key);
  if (cached) return cached;

  const words = [];
  let current = "";
  let currentWidth = 0;
  let maxWordWidth = 0;
  for (const char of value) {
    if (/\s/.test(char)) {
      if (current) {
        words.push({ text: current, width: currentWidth });
        if (currentWidth > maxWordWidth) maxWordWidth = currentWidth;
        current = "";
        currentWidth = 0;
      }
      continue;
    }
    current += char;
    currentWidth += charWidth(char, font);
  }
  if (current) {
    words.push({ text: current, width: currentWidth });
    if (currentWidth > maxWordWidth) maxWordWidth = currentWidth;
  }

  const prepared = {
    text: value,
    font,
    naturalWidth: naturalWidth(value, font),
    words,
    maxWordWidth,
    spaceWidth: charWidth(" ", font),
  };
  preparedCache.set(key, prepared);
  return prepared;
}

/**
 * Число строк жадным переносом по пробелам.
 *
 * Возвращает `Infinity` для нулевой/отрицательной ширины. Длинное слово без
 * пробелов не рвётся (как `overflow-wrap: normal`): оно занимает строку, даже
 * если вылезает за ширину, — это сигнал оптимизатору, что колонка слишком узкая.
 */
export function greedyLineCount(prepared, usableWidth) {
  if (!(usableWidth > 0)) return Infinity;
  if (prepared.naturalWidth <= usableWidth) return 1;
  if (prepared.words.length === 0) return 1;

  let lines = 1;
  let lineWidth = 0;
  for (let i = 0; i < prepared.words.length; i += 1) {
    const word = prepared.words[i];
    const separator = i === 0 ? 0 : prepared.spaceWidth;
    if (lineWidth > 0 && lineWidth + separator + word.width > usableWidth) {
      lines += 1;
      lineWidth = word.width;
    } else if (lineWidth === 0) {
      lineWidth = word.width;
    } else {
      lineWidth += separator + word.width;
    }
  }
  return lines;
}

/** Грубая модель из черновика: линейное деление, без слов. Только для baseline. */
export function ceilLineCount(prepared, usableWidth) {
  if (!(usableWidth > 0)) return Infinity;
  return Math.max(1, Math.ceil(prepared.naturalWidth / usableWidth));
}

/**
 * Число строк с потолком (`line-clamp`). `truncated` — текст не поместился
 * в разрешённые строки; полный текст обязан остаться в `title`.
 */
export function clampedLineCount(prepared, usableWidth, clamp) {
  const raw = greedyLineCount(prepared, usableWidth);
  if (!Number.isFinite(raw)) return { lines: raw, truncated: false };
  const limit = clamp ?? Infinity;
  return { lines: Math.min(raw, limit), truncated: raw > limit };
}

/** Ширина ряда пилюль операций: текст + внутренние отступы + разделители. */
export function pillsWidth(pillTexts, font = "sans", chrome = 26) {
  if (!pillTexts || pillTexts.length === 0) return 0;
  const widened = pillTexts.reduce(
    (sum, text) => sum + naturalWidth(text, font) + chrome,
    0,
  );
  return widened + Math.max(0, pillTexts.length - 1) * 10;
}
