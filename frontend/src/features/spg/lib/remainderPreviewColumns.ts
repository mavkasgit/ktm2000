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

export type RemainderPreviewColumn = ColumnSpec<RemainderPreviewSortField> & {
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
  { id: "row", label: "#", filterField: "row", sortField: "row", headerClassName: "w-10" },
  { id: "sku", label: "Артикул", filterField: "sku", sortField: "sku", headerClassName: "w-24" },
  {
    id: "quantity",
    label: "Кол-во",
    filterField: "quantity",
    sortField: "quantity",
    headerClassName: "w-14 text-right",
  },
  { id: "length", label: "Длина", filterField: "length", sortField: "length", headerClassName: "w-16" },
  {
    id: "operations",
    label: "Операции",
    filterField: "operations",
    sortField: "operations",
    headerClassName: "min-w-[160px]",
  },
  {
    id: "quality",
    label: "Качество",
    filterField: "quality",
    sortField: "quality",
    headerClassName: "w-24",
  },
  {
    id: "section",
    label: "Участок",
    filterField: "section",
    sortField: "section",
    headerClassName: "min-w-[150px]",
  },
  {
    id: "errors",
    label: "Ошибки",
    filterField: "errors",
    sortField: "errors",
    headerClassName: "min-w-[140px]",
    mapValue: errorValueOnly,
  },
];

/** Список полей для сбора значений: тот же, что и в шапке, а не свой. */
export const remainderPreviewColumnFields = remainderPreviewColumns.map(
  (column) => column.filterField!,
);
