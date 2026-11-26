/**
 * `OffscreenCanvas`-полифилл для Node.
 *
 * @chenglou/pretext не трогает DOM, но на этапе `prepare()` измеряет сегменты
 * через Canvas 2D: `new OffscreenCanvas(1, 1).getContext('2d')`, затем
 * `context.font = font` и `context.measureText(text).width`. В браузере это
 * настоящий canvas; в Node его нет, поэтому подставляем объект с тем же
 * минимальным контрактом.
 *
 * Контракт полифилла (ровно то, что читает pretext):
 *
 * - `new OffscreenCanvas(width, height)`;
 * - `getContext("2d") -> context`;
 * - `context.font` — строковое свойство: pretext пишет CSS-шрифт и читает его
 *   обратно, чтобы убедиться, что контекст его принял;
 * - `context.measureText(text) -> { width, actualBoundingBoxLeft,
 *   actualBoundingBoxRight }` — ширина в пикселях. Боковые метрики нужны
 *   только Han-kerning'у и здесь нулевые: синтетика кириллическая/латинская;
 * - **нет** `context.letterSpacing`: pretext проверяет
 *   `typeof context.letterSpacing === "string"` и без него не идёт по ветке
 *   letter-spaced shaping. Полифилл letter-spacing не моделирует — это
 *   осознанное ограничение (см. README, «Границы модели»).
 *
 * Ширина символа берётся из той же таблицы 11px, что и у `greedy`
 * ([`text.mjs`](./text.mjs)): так Node-прогон pretext детерминирован и
 * сравним с greedy, но абсолютные пиксели — синтетика, а не метрики Inter.
 */

import { naturalWidth } from "./text.mjs";

/** Семейство из строки canvas-шрифта: всё, что содержит `mono`, — моноширинное. */
function fontClass(font) {
  return /mono|JetBrains/i.test(font) ? "mono" : "sans";
}

function createContext2D() {
  const context = {
    font: "11px sans-serif",
    measureText(text) {
      const width = naturalWidth(String(text), fontClass(context.font));
      return {
        width,
        actualBoundingBoxLeft: 0,
        actualBoundingBoxRight: width,
        actualBoundingBoxAscent: 0,
        actualBoundingBoxDescent: 0,
      };
    },
  };
  return context;
}

export class OffscreenCanvasPolyfill {
  constructor(width = 0, height = 0) {
    this.width = width;
    this.height = height;
    this.context2d = null;
  }

  getContext(type) {
    if (type !== "2d") return null;
    if (!this.context2d) this.context2d = createContext2D();
    return this.context2d;
  }
}

/**
 * Ставит полифилл в `globalThis`, если `OffscreenCanvas` ещё нет.
 * Идемпотентна: повторный вызов ничего не меняет.
 *
 * @returns {boolean} `true`, если полифилл установлен этим вызовом.
 */
export function installOffscreenCanvas() {
  if (globalThis.OffscreenCanvas) return false;
  globalThis.OffscreenCanvas = OffscreenCanvasPolyfill;
  return true;
}
