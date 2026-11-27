/**
 * Текст ячейки «Ошибок» предпросмотра остатков — одно правило на ячейку и на
 * модель ширин (#483).
 *
 * Модель считает строки по тому же тексту, который печатается: если бы она
 * брала сырые `errors`, переводы и префикс пропуска разошлись бы с DOM, и
 * предсказанная высота строки стала бы вымыслом.
 */
import { translateImportError } from "@/shared/api/errorMessages";
import type { RemainderImportItem } from "@/shared/api/stock";

/** Подпись пропуска из предпросмотра: «нет совпадения» / «есть в исключениях». */
function skipReasonLabel(item: RemainderImportItem): string {
  return item.skip_reason_label?.trim() || "нет совпадения";
}

/**
 * Подпись фильтра «Ошибки». Правило повторяет `_preview_errors_label`
 * (`stock/import_service.py`): пропуск — не ошибка, но колонка объясняет
 * строку, и по этой же подписи сервер фильтрует `?errors=`. Предупреждения
 * в фильтр не входят — иначе значения поповера не находили бы строк на сервере.
 */
export function previewErrorsText(item: RemainderImportItem): string {
  if (item.status === "skipped") {
    return `Пропущено: ${skipReasonLabel(item)}`;
  }
  if (item.errors.length === 0) {
    return item.status === "valid" ? "—" : "Ошибка";
  }
  return item.errors.map(translateImportError).join(", ");
}

/**
 * Класс ячейки «Наименование»: под флагом #483 — перенос
 * (`whitespace-pre-line`, ширина посчитана, высота предсказана), без флага —
 * прежний `truncate` в одну строку.
 */
export function previewNameCellClass(nameWraps: boolean): string {
  return nameWraps ? "whitespace-pre-line" : "truncate";
}

/**
 * Текст, который печатает ячейка «Наименование»: имя каталога, иначе имя из
 * 1С, иначе прочерк. Модель считает перенос по этому же тексту.
 */
export function previewNameCellText(item: RemainderImportItem): string {
  return item.product_name ?? item.source_name ?? "—";
}

/**
 * Текст, который печатает ячейка «Ошибки»: у пропуска — подпись причины,
 * у остальных — предупреждения и ошибки. Предупреждение о длине, взятой из
 * карточки, обязано быть видно в строке, а не только в подсказке. Модель
 * считает строки по этому тексту.
 */
export function previewErrorsCellText(item: RemainderImportItem): string {
  if (item.status === "skipped") return previewErrorsText(item);
  const messages = [...item.warnings, ...item.errors];
  if (messages.length === 0) {
    return item.status === "valid" ? "—" : "Ошибка";
  }
  return messages.map(translateImportError).join(", ");
}

/**
 * `false` — ячейка печатается одной строкой (`whitespace-nowrap` у пропуска):
 * такая строка не растягивает таблицу, сколько бы ни было текста.
 */
export function previewErrorsWraps(item: RemainderImportItem): boolean {
  return item.status !== "skipped";
}
