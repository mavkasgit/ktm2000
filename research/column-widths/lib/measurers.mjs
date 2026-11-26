/**
 * Три реализации измерителя текста:
 *
 * - `greedy`  — табличные метрики 11px + жадный перенос по пробелам (дефолт бенча);
 * - `ceil`    — линейное `ceil(width / usable)` из первого черновика (baseline);
 * - `pretext` — @chenglou/pretext; в Node ему подставляется OffscreenCanvas
 *               с той же табличной метрикой, в браузере — настоящий canvas.
 *
 * Интерфейс одинаковый, поэтому оптимизатор не знает, каким движком считается
 * строка. Именно это позволяет позже заменить модель на реальный pretext/DOM
 * без переписывания алгоритма:
 *
 * ```js
 * const prepared = measurer.prepare(text, font); // font: "sans" | "mono"
 * measurer.naturalWidth(prepared);               // ширина в одну строку
 * measurer.maxWordWidth(prepared);               // самый широкий неразрывный кусок
 * measurer.lineCount(prepared, usableWidth);     // число строк при ширине
 * ```
 *
 * `ceil` помечен `role: "baseline"`: он нужен только как точка отсчёта в
 * отчёте и не должен попадать в финальное решение (дефолт — `greedy`).
 *
 * Шрифты синхронизированы с CSS через `cssFont()`: `11px "Inter"` для текста и
 * `11px "JetBrains Mono"` для артикулов/кодов. Источник размера и семейств —
 * эта функция, а не строки, разбросанные по коду.
 */
import {
  ceilLineCount,
  greedyLineCount,
  prepareText,
} from "./text.mjs";
import { installOffscreenCanvas } from "./offscreen-canvas.mjs";

export const MEASURERS = ["greedy", "ceil", "pretext"];

/** Размер шрифта предпросмотра в px — как `text-[11px]` в продуктовой таблице. */
export const FONT_PX = 11;

/** Семейства из CSS предпросмотра. */
export const FONT_FAMILY = {
  sans: '"Inter"',
  mono: '"JetBrains Mono"',
};

const FONT_ALIASES = {
  sans: "sans",
  text: "sans",
  mono: "mono",
  code: "mono",
};

/** CSS font string для canvas/pretext: `11px "Inter"` или `11px "JetBrains Mono"`. */
export function cssFont(font = "sans") {
  const family = FONT_ALIASES[font] ?? "sans";
  return `${FONT_PX}px ${FONT_FAMILY[family]}`;
}

function unbounded(prepared, usable, count) {
  const lines = count(prepared, usable);
  return Number.isFinite(lines) ? Math.max(1, lines) : Number.MAX_SAFE_INTEGER;
}

function normalizeFont(font) {
  return FONT_ALIASES[font] ?? "sans";
}

function syntheticMeasurer(kind) {
  return {
    name: kind,
    role: kind === "ceil" ? "baseline" : "primary",
    prepare: (text, font = "sans") => prepareText(text, normalizeFont(font)),
    naturalWidth: (prepared) => prepared.naturalWidth,
    maxWordWidth: (prepared) => prepared.maxWordWidth,
    lineCount: (prepared, usable) =>
      unbounded(prepared, usable, kind === "ceil" ? ceilLineCount : greedyLineCount),
  };
}

/** Синхронный измеритель на табличных метриках: `greedy` (дефолт) или `ceil` (baseline). */
export function createSyntheticMeasurer(kind = "greedy") {
  if (kind !== "greedy" && kind !== "ceil") {
    throw new Error(`unknown synthetic measurer: ${kind}`);
  }
  return syntheticMeasurer(kind);
}

/**
 * Node/браузерный адаптер pretext: скрывает разницу API
 * (`prepareWithSegments` / `measureLineStats` / `measureNaturalWidth`) за общим
 * интерфейсом. В Node перед импортом ставит `OffscreenCanvas`-полифилл; в
 * браузере `globalThis.OffscreenCanvas` уже есть и полифилл не нужен.
 *
 * `maxWordWidth` считается по сегментам самого pretext: это самый широкий
 * неразрывный кусок, поэтому для слова с дефисом он может быть меньше, чем
 * whitespace-токен у greedy (pretext/браузер переносят после дефиса).
 */
export async function createPretextMeasurer() {
  installOffscreenCanvas();
  const pretext = await import("@chenglou/pretext");
  if (typeof pretext.setLocale === "function") {
    try {
      pretext.setLocale("ru");
    } catch {
      /* локаль не критична для синтетики */
    }
  }
  return {
    name: "pretext",
    role: "primary",
    prepare(text, font = "sans") {
      const value = text ?? "";
      const family = normalizeFont(font);
      const prepared = pretext.prepareWithSegments(value, cssFont(family), {
        whiteSpace: "normal",
      });
      const { kinds, widths } = prepared;
      let maxWordWidth = 0;
      for (let index = 0; index < kinds.length; index += 1) {
        if (kinds[index] !== "text") continue;
        const width = widths[index];
        if (width > maxWordWidth) maxWordWidth = width;
      }
      return {
        prepared,
        text: value,
        font: family,
        naturalWidth: pretext.measureNaturalWidth(prepared),
        maxWordWidth,
      };
    },
    naturalWidth: (prepared) => prepared.naturalWidth,
    maxWordWidth: (prepared) => prepared.maxWordWidth,
    lineCount(prepared, usable) {
      if (!(usable > 0)) return Number.MAX_SAFE_INTEGER;
      if (!prepared.text) return 1;
      const stats = pretext.measureLineStats(prepared.prepared, usable);
      return Math.max(1, stats.lineCount);
    },
  };
}

/** Создаёт измеритель по имени. `pretext` асинхронный (динамический import). */
export async function createMeasurer(kind = "greedy") {
  if (kind === "pretext") return createPretextMeasurer();
  return createSyntheticMeasurer(kind);
}
