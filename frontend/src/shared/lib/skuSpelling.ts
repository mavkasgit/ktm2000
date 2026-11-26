/**
 * skuSpelling.ts — допустимые написания артикула при сопоставлении (#474).
 *
 * Канон хранения серии ALS — без дефиса (`ALS1103`), потому что так его пишут
 * 1С и упаковочная карта. Дефис между буквой и цифрой — оформление, а не часть
 * кода: экран, который сравнивает SKU позиции (снимок импорта) с каталожным,
 * обязан видеть в `ALS-1103` и `ALS1103` один артикул. Дефис между цифрами —
 * часть номера (`12-34`) и не снимается.
 *
 * Одна реализация на фронт; правило совпадает с серверным `sku_loose`.
 */

const DASH_VARIANTS = /[\u2010\u2011\u2012\u2013\u2014\u2212\u2043\uFE58\uFE63\uFF0D]/g;
const SPACES = /[\s\u00A0]/g;
const DASH_BETWEEN_LETTER_AND_DIGIT = /([a-zа-яё])-(?=[0-9])/g;

export function skuLoose(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(DASH_VARIANTS, "-")
    .replace(SPACES, "")
    .replace(DASH_BETWEEN_LETTER_AND_DIGIT, "$1");
}
