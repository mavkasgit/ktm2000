/**
 * lib/planPrintSettings.ts
 * ======================
 * Колонки плана участка и наборы колонок печати — всё как данные в коде.
 *
 * Таблица рендерит только выбранные колонки, поэтому печать и предпросмотр
 * совпадают: лишних ячеек в DOM нет, CSS-прятание не используется.
 * Профиль участка (по коду секции) задаёт набор по умолчанию; кнопки
 * «Колонки печати» и пресеты позволяют его переопределить.
 *
 * Колонки, которой у участка не бывает, нет ни в наборе, ни в кнопках:
 * «Упаковка» печатается только там, где в справочнике операций участка есть
 * упаковочная операция (`Section.has_packaging`, константа
 * `PACKAGING_ONLY_COLUMNS`). Поэтому профиль вправе перечислять `packaging` —
 * на участке без упаковки колонка не появится: базовый пресет участка и все
 * остальные пресеты приводятся к применимым колонкам в `loadPresets`
 * (`lib/planPresets.ts`).
 *
 * Как добавить исключение для участка — одна строка в `PRINT_PROFILES`:
 *
 *   PACKING: ["sku", "size", "preOps", "packaging", "balance"],
 */

export type PlanColumnKey =
  | "group"
  | "sku"
  | "size"
  | "preOps"
  | "operation"
  | "packaging"
  | "hangers"
  | "perHanger"
  | "issued"
  | "done"
  | "transferred"
  | "balance"
  | "actions";

export type PlanColumnDef = {
  key: PlanColumnKey;
  title: string;
  /** `label` — текстовые (объединяются в шапке группы), `number` — числовые. */
  kind: "label" | "number";
  /**
   * Служебная колонка окна: рисуется всегда, в шапке не подписывается, в
   * «Колонках печати» не предлагается. Интерактивные служебные колонки (`×`
   * скрытия группы) на печать не выводятся (`no-print-col`); отметка строки
   * внутри группы печатается — иначе заголовок группы, объединяющий метки
   * через `colSpan`, на бумаге сдвинул бы свои итоги на колонку вправо.
   */
  service?: boolean;
};

export const PLAN_COLUMNS: PlanColumnDef[] = [
  { key: "group", title: "Группа", kind: "label", service: true },
  { key: "sku", title: "Артикул", kind: "label" },
  { key: "size", title: "Размер", kind: "label" },
  { key: "preOps", title: "Пред операции", kind: "label" },
  { key: "operation", title: "Операция", kind: "label" },
  { key: "packaging", title: "Упаковка", kind: "label" },
  { key: "hangers", title: "Подвесы", kind: "number" },
  { key: "perHanger", title: "Кол-во на подвес", kind: "number" },
  { key: "issued", title: "Выдано", kind: "number" },
  { key: "done", title: "Сделано", kind: "number" },
  { key: "transferred", title: "Передано", kind: "number" },
  { key: "balance", title: "Осталось", kind: "number" },
  { key: "actions", title: "", kind: "number", service: true },
];

const COLUMN_KEYS = new Set<string>(PLAN_COLUMNS.map((column) => column.key));

export function isPlanColumnKey(value: unknown): value is PlanColumnKey {
  return typeof value === "string" && COLUMN_KEYS.has(value);
}

/** Колонки, доступные для печати: всё, кроме служебных. */
export const PRINTABLE_COLUMNS: PlanColumnDef[] = PLAN_COLUMNS.filter((column) => !column.service);

/**
 * Расширенный набор печати: артикул, размер, операции, упаковка и остаток.
 * Основа встроенного пресета «Полный план».
 * Ни цвета, ни плана в печати нет: на анодировании цвет — это операция
 * участка, а план производная величина от остатка.
 */
export const DEFAULT_PRINT_COLUMNS: PlanColumnKey[] = [
  "sku",
  "size",
  "preOps",
  "operation",
  "packaging",
  "balance",
];

/** Базовый набор участка: артикул → операции → остаток. */
const OPERATION_COLUMNS: PlanColumnKey[] = [
  "sku",
  "size",
  "preOps",
  "operation",
  "balance",
];

/**
 * Анодирование: мастер идёт от остатка и делит его на подвесы по норме.
 * «Подвесы» печатаются по решению владельца (#205): мастер готовит подвесы
 * заранее, норма рядом — «Кол-во на подвес». «План» не печатается: после
 * выдачи он не равен остатку. Отдельной колонки «Цвет» нет — цвет
 * анодирования и есть операция участка
 * (`ANOD_01 Серебро`, `ANOD_05 Чёрный`, `ANOD_08 Титан`).
 */
const ANODIZING_COLUMNS: PlanColumnKey[] = [
  "sku",
  "size",
  "preOps",
  "operation",
  "packaging",
  "hangers",
  "perHanger",
  "balance",
];

/**
 * Профили печати по коду секции; `*` — для всех остальных.
 * Участки и их операции: `backend/app/seeds/sections.py`.
 */
export const PRINT_PROFILES: Record<string, PlanColumnKey[]> = {
  // Начало цепочки: предопераций выше по маршруту нет.
  DRILLING: ["sku", "size", "operation", "balance"],
  PRESSING: OPERATION_COLUMNS,
  SHOT_BLAST: OPERATION_COLUMNS,
  ANODIZING: ANODIZING_COLUMNS,
  // На пиле упаковки нет: тип упаковки печатается на анодировании.
  SAWING: OPERATION_COLUMNS,
  // «Упаковка» — имя операции участка, колонка «Упаковка» несёт её тип.
  PACKING: ["sku", "size", "preOps", "packaging", "balance"],
  "*": OPERATION_COLUMNS,
};

/** Альтернативный набор: используется как встроенный пресет. */
export const COMPACT_PRINT_COLUMNS: PlanColumnKey[] = ["sku", "size", "operation", "balance"];

export function printColumnsFor(sectionCode?: string | null): PlanColumnKey[] {
  return (sectionCode ? PRINT_PROFILES[sectionCode] : undefined) ?? PRINT_PROFILES["*"];
}

/**
 * Колонки, которые печатаются только у участка с упаковочными операциями.
 *
 * «Упаковка» — свойство участка, а не набора печати: колонка есть только там,
 * где в справочнике операций участка есть упаковочная операция (флаг
 * `Section.has_packaging`). Печать транслирует доску — на участке без
 * упаковки колонки нет ни в наборе, ни в кнопках.
 *
 * Флаг отсутствует (старый кэш, ошибка справочника) — колонка остаётся:
 * ошибка справочника не должна прятать данные, а «Упаковка» на анодировании
 * несёт тип упаковки, а не украшает шапку.
 */
export const PACKAGING_ONLY_COLUMNS: readonly PlanColumnKey[] = ["packaging"];

export interface PrintSettings {
  /** Набор печати: ключи из `PLAN_COLUMNS`. */
  columns: PlanColumnKey[];
  title: string;
}

/** Приводит сохранённые настройки к валидным: неизвестные ключи отбрасываются. */
export function normalizePrintSettings(
  stored: Partial<PrintSettings> | null | undefined,
  fallbackColumns: PlanColumnKey[],
): PrintSettings {
  const columns = Array.isArray(stored?.columns)
    ? stored.columns.filter(isPlanColumnKey)
    : [];
  return {
    columns: columns.length > 0 ? columns : [...fallbackColumns],
    title: typeof stored?.title === "string" ? stored.title : "",
  };
}
