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
 * без переписывания алгоритма.
 */
import {
  ceilLineCount,
  greedyLineCount,
  naturalWidth as rawNaturalWidth,
  prepareText,
} from "./text.mjs";

export const MEASURERS = ["greedy", "ceil", "pretext"];

function unbounded(prepared, usable, count) {
  const lines = count(prepared, usable);
  return Number.isFinite(lines) ? Math.max(1, lines) : Number.MAX_SAFE_INTEGER;
}

export function createSyntheticMeasurer(kind = "greedy") {
  if (kind === "ceil") {
    return {
      name: "ceil",
      prepare: prepareText,
      naturalWidth: (prepared) => prepared.naturalWidth,
      maxWordWidth: (prepared) => prepared.maxWordWidth,
      lineCount: (prepared, usable) => unbounded(prepared, usable, ceilLineCount),
    };
  }
  return {
    name: "greedy",
    prepare: prepareText,
    naturalWidth: (prepared) => prepared.naturalWidth,
    maxWordWidth: (prepared) => prepared.maxWordWidth,
    lineCount: (prepared, usable) => unbounded(prepared, usable, greedyLineCount),
  };
}

/**
 * Node-адаптер для pretext: библиотека требует Canvas 2D только на этапе
 * `prepare()`, поэтому подменяем измерение символов той же моделью, что и
 * greedy. В браузере (тикет «валидация измерителя») этот слой не нужен.
 */
function installOffscreenCanvas() {
  if (globalThis.OffscreenCanvas) return;
  globalThis.OffscreenCanvas = class OffscreenCanvasPolyfill {
    constructor(width = 0, height = 0) {
      this.width = width;
      this.height = height;
    }

    getContext() {
      const context = {
        font: "11px sans-serif",
        measureText(text) {
          const font = /mono/i.test(context.font) ? "mono" : "sans";
          return { width: rawNaturalWidth(String(text), font) };
        },
      };
      return context;
    }
  };
}

function pretextFont(font) {
  return font === "mono" ? '11px "JetBrains Mono"' : '11px "Inter"';
}

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
    prepare(text, font = "sans") {
      const value = text ?? "";
      const prepared = pretext.prepare(value, pretextFont(font), {
        whiteSpace: "normal",
      });
      return {
        prepared,
        text: value,
        font,
        naturalWidth:
          typeof pretext.measureNaturalWidth === "function"
            ? pretext.measureNaturalWidth(prepared)
            : rawNaturalWidth(value, font),
        maxWordWidth: prepareText(value, font).maxWordWidth,
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

export async function createMeasurer(kind = "greedy") {
  if (kind === "pretext") return createPretextMeasurer();
  return createSyntheticMeasurer(kind);
}
