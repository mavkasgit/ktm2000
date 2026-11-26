/**
 * Измеритель текста для модели ширин предпросмотра (#483).
 *
 * `pretext` грузится динамически: пока флаг выключен, чанк не скачивается, и
 * начальный пакет не растёт. Меряется **только то, что переносится**:
 * «Ошибки» — единственная колонка, чья высота зависит от ширины. Подписи
 * пилюль — однострочные, им хватает `measureText` (тот же canvas, что внутри
 * `pretext`, но без сегментации).
 *
 * Шрифт не захардкожен: семейство, размер, вес и `line-height` берутся из
 * фактического CSS ячейки. В продукте не грузится webfont, поэтому модель
 * обязана мерить системный стек, который резолвит DOM, — иначе H4 на CSS
 * продукта (см. `research/column-widths/browser/product.spec.mjs`) не
 * переносится на машину оператора.
 */
import type { ImportOperationStep, RemainderImportItem } from "@/shared/api/stock";

import { pillRowNaturalWidth } from "./previewPillWidths";
import {
  previewErrorsCellText,
  previewErrorsWraps,
} from "./remainderPreviewErrors";

/** Классы ячейки «Ошибок»: то же, что `font-medium leading-snug` + `text-[11px]`. */
export const PREVIEW_ERRORS_TEXT_CLASS = "text-[11px] font-medium leading-snug";

export interface PreviewFont {
  family: string;
  sizePx: number;
  weight: number;
  lineHeightPx: number;
}

export interface PreviewTextMeasurer {
  prepare(text: string, font: PreviewFont): unknown;
  naturalWidth(prepared: unknown): number;
  maxWordWidth(prepared: unknown): number;
  lineCount(prepared: unknown, usableWidth: number): number;
}

export interface PreviewRowMeasurement {
  /** `source_row_number`: ключ строки в предпросмотре. */
  rowKey: number;
  errorsText: string;
  /** `false` — ячейка печатается одной строкой (пропуск). */
  errorsWraps: boolean;
  /** Натуральная ширина ряда пилюль без padding ячейки, px. */
  pillWidth: number;
}

export interface PreviewWidthEngine {
  fonts: { errors: PreviewFont; pill: PreviewFont };
  measurer: PreviewTextMeasurer;
  buildRows(
    items: readonly RemainderImportItem[],
    referenceOps: readonly ImportOperationStep[] | null | undefined,
  ): PreviewRowMeasurement[];
}

function cssFontValue(font: PreviewFont): string {
  return `${font.weight} ${font.sizePx}px ${font.family}`;
}

/**
 * Читает метрики ячейки «Ошибок» из фактического CSS. Проба — один скрытый
 * `<span>` с теми же классами; так модель следует за CSS, а не за копией
 * констант в коде.
 */
function readErrorsFont(): PreviewFont {
  const probe = document.createElement("span");
  probe.className = PREVIEW_ERRORS_TEXT_CLASS;
  probe.textContent = "АБВГД 0123456789";
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.style.pointerEvents = "none";
  document.body.appendChild(probe);
  const style = getComputedStyle(probe);
  const sizePx = Number.parseFloat(style.fontSize) || 11;
  const lineHeight = Number.parseFloat(style.lineHeight);
  const font: PreviewFont = {
    family: style.fontFamily,
    sizePx,
    weight: Number(style.fontWeight) || 400,
    lineHeightPx: Number.isFinite(lineHeight) ? lineHeight : sizePx * 1.5,
  };
  probe.remove();
  return font;
}

/**
 * Создаёт движок замера: `pretext` + canvas для подписей пилюль.
 *
 * Кэш подготовленного текста живёт на время жизни движка (движок один на
 * приложение): при пересчёте на ресайз повторная сегментация 500 строк — это
 * та самая работа, которую тикет убирает. Кэш ограничен, чтобы смена листов
 * не копила подготовленные тексты бесконечно.
 */
export async function createPreviewWidthEngine(): Promise<PreviewWidthEngine> {
  if (typeof document === "undefined") {
    throw new Error("preview widths: нужен браузер");
  }
  await document.fonts.ready;

  const errorsFont = readErrorsFont();
  const pillFont: PreviewFont = {
    ...errorsFont,
    sizePx: 10,
    weight: 500,
    lineHeightPx: 20,
  };

  const pretext = await import("@chenglou/pretext");
  if (typeof pretext.setLocale === "function") {
    try {
      pretext.setLocale("ru");
    } catch {
      /* локаль не критична: тот же сегментатор, что у браузера */
    }
  }

  const preparedCache = new Map<string, unknown>();
  const preparedMaxEntries = 20_000;

  const measurer: PreviewTextMeasurer = {
    prepare(text, font) {
      const value = text ?? "";
      const cssFont = cssFontValue(font);
      const key = `${cssFont}\u0000${value}`;
      const cached = preparedCache.get(key);
      if (cached !== undefined) return cached;

      const prepared = pretext.prepareWithSegments(value, cssFont, {
        whiteSpace: "normal",
      });
      if (preparedCache.size >= preparedMaxEntries) preparedCache.clear();
      preparedCache.set(key, prepared);
      return prepared;
    },
    naturalWidth(prepared) {
      return pretext.measureNaturalWidth(
        prepared as ReturnType<typeof pretext.prepareWithSegments>,
      );
    },
    maxWordWidth(prepared) {
      const { kinds, widths } = prepared as ReturnType<
        typeof pretext.prepareWithSegments
      >;
      let max = 0;
      for (let index = 0; index < kinds.length; index += 1) {
        if (kinds[index] !== "text") continue;
        if (widths[index] > max) max = widths[index];
      }
      return max;
    },
    lineCount(prepared, usableWidth) {
      if (!(usableWidth > 0)) return Number.MAX_SAFE_INTEGER;
      const value = prepared as ReturnType<typeof pretext.prepareWithSegments>;
      if (pretext.measureNaturalWidth(value) <= 0) return 1;
      return Math.max(1, pretext.measureLineStats(value, usableWidth).lineCount);
    },
  };

  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const labelCache = new Map<string, number>();
  const measurePillLabel = (text: string): number => {
    if (!context) return 0;
    const cssFont = cssFontValue(pillFont);
    const key = `${cssFont}\u0000${text}`;
    const cached = labelCache.get(key);
    if (cached !== undefined) return cached;
    context.font = cssFont;
    const width = context.measureText(text).width;
    labelCache.set(key, width);
    return width;
  };

  return {
    fonts: { errors: errorsFont, pill: pillFont },
    measurer,
    buildRows(items, referenceOps) {
      return items.map((item) => ({
        rowKey: item.source_row_number,
        errorsText: previewErrorsCellText(item),
        errorsWraps: previewErrorsWraps(item),
        pillWidth: pillRowNaturalWidth(
          item.completed_stages,
          referenceOps,
          measurePillLabel,
        ),
      }));
    },
  };
}
