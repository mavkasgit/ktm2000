/**
 * Описание колонок предпросмотра импорта остатков — единственное место, где
 * объявляется, что это за колонка, как она фильтруется и сортируется
 * (#198, ADR-0038).
 *
 * Пока параметры собирались в `buildRemainderPreviewColumnApiParams` восемью
 * строками, а значения ошибок отбрасывались прямо в вызове, колонка называлась
 * в шапке, в сборке и в списке уникальных значений по отдельности.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { RemainderPreviewSortField } from "@/shared/lib/stockSortParams";
import type { RemainderImportItem } from "@/shared/api/stock";

export type RemainderPreviewColumn = ColumnSpec<
  RemainderPreviewSortField,
  RemainderPreviewSortField,
  RemainderImportItem
> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: выравнивание и ширина. */
  headerClassName?: string;
};

/** «—» и «Ошибка» — это не значение, а способ показать, что его нет. */
const errorValueOnly = (value: string) =>
  value === "—" || value === "Ошибка" ? undefined : value;

/**
 * Колонка «Длина» объявлена как подстрочный фильтр, а не как точное
 * совпадение, в отличие от «Размера» на доске. Причина в бэкенде:
 * `_matches_preview_partial` в `backend/app/stock/import_service.py` сравнивает
 * подпись `dimensions_label` через `needle in haystack`, и параметра точного
 * совпадения у предпросмотра нет. Объявлять здесь `exactMatch` означало бы
 * отправить параметр, которого сервер не понимает.
 *
 * Порядок колонок совпадает с шапкой и с телом таблицы предпросмотра.
 */
export const remainderPreviewColumns: RemainderPreviewColumn[] = [
  {
    id: "row",
    label: "#",
    filterField: "row",
    sortField: "row",
    headerClassName: "w-10",
    sortValues: (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
  },
  {
    // Источник из ОСВ 1С. Колоночного фильтра у него нет ни в контракте
    // предпросмотра, ни в спеке §5.2: код участвует только в общем `search`.
    // Сортировки тоже нет — бэкенд её не знает, а иконка без эффекта врёт.
    id: "source_code",
    label: "Код 1С",
    headerClassName: "w-20",
  },
  {
    id: "sku",
    label: "Артикул",
    filterField: "sku",
    sortField: "sku",
    headerClassName: "w-24",
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    // Ячейка печатает `product_name`, а `source_name` уходит в подсказку:
    // наименование 1С нужно для сверки, но фильтровать и сортировать по нему
    // сервер не умеет.
    id: "source_name",
    label: "Наименование",
    headerClassName: "min-w-[220px]",
  },
  {
    id: "quantity",
    label: "Кол-во, шт",
    filterField: "quantity",
    sortField: "quantity",
    headerClassName: "w-20 text-right",
    sortValues: (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
  },
  {
    // Метры из «Конечное сальдо / Количество» ОСВ. Дробные, поэтому
    // фильтра/сортировки нет: сервер их не фильтрует.
    id: "meters",
    label: "Метры",
    headerClassName: "w-20 text-right",
  },
  {
    id: "length",
    label: "Длина",
    filterField: "length",
    sortField: "length",
    headerClassName: "w-16",
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "operations",
    label: "Операции",
    filterField: "operations",
    sortField: "operations",
    headerClassName: "min-w-[140px]",
    sortValues: (a, b) => a.localeCompare(b, "ru"),
    // Значения списка фильтра — серверные подписи (их собирает
    // `getImportItemOperationsServerLabel` по `completed_operations_raw` и
    // этапам), а ячейка печатает прочерк. Переводить нечего: прочерк в
    // `?operations=` не знает ни `_preview_operations_label`, ни
    // `_balance_operations_filter`, а два пустых состояния сервер различает
    // как раз подписями (ADR-0055 п.5).
  },
  {
    id: "quality",
    label: "Качество",
    filterField: "quality",
    sortField: "quality",
    headerClassName: "w-24",
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "section",
    label: "Участок",
    filterField: "section",
    sortField: "section",
    headerClassName: "min-w-[135px]",
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "errors",
    label: "Ошибки",
    filterField: "errors",
    sortField: "errors",
    // Подпись пропуска («Пропущено: есть в исключениях») печатается одной
    // строкой: перенос растягивал строку таблицы выше общего ритма
    // `TABLE_ROW_COMPACT` (40px, ADR-0030). Ширина — под самый длинный
    // базовый вариант; длинные ошибки по-прежнему переносятся.
    headerClassName: "min-w-[200px]",
    mapValue: errorValueOnly,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
];

/**
 * Список полей для сбора значений: тот же, что и в шапке, а не свой.
 * Колонки источника (`Код 1С`, `Наименование`, `Метры`) фильтра не имеют —
 * undefined в списке полей означал бы поле, которого нет в контракте.
 */
export const remainderPreviewColumnFields = remainderPreviewColumns.flatMap(
  (column) => (column.filterField ? [column.filterField] : []),
);
