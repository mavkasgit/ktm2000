/**
 * Описание колонок складских остатков — единственное место, где объявляется,
 * что это за колонка, как она фильтруется, сортируется и каким значением
 * уезжает в запрос (#198, ADR-0038).
 *
 * Пока параметры собирались в панели пятью почти одинаковыми строками, а
 * перекодировка качества и отбрасывание служебных значений «#12» жили в
 * вызовах, колонка знала своё имя, а что именно уедет — знал вызов рядом.
 *
 * Колонка «Размеры» объявлена без фильтра и без сортировки намеренно: бэкенд
 * `GET /stock/balance` не принимает параметра габарита, а `_BALANCE_SORT_COLUMNS`
 * в `backend/app/stock/api.py` его не содержит. Разные длины одного артикула —
 * разные строки (ADR-0001), и это свойство строки, а не колонки, по которой
 * можно отфильтровать.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { BalanceSortField } from "@/shared/lib/stockSortParams";

export type StockBalanceColumn = ColumnSpec<BalanceSortField> & {
  id: string;
  label: string;
  headerClassName?: string;
  /** Колонка скрывается, когда панель показывает остатки по заводу. */
  hideWhenNoLocation?: boolean;
};

/** Пусто — не значение: сервер такого не понимает. */
const dropDash = (value: string) => (value === "—" ? undefined : value);

/**
 * Мест без названия отображаются как «#12» — это подпись для оператора, а не
 * значение, по которому сервер что-то найдёт.
 */
const dropNumericPlaceholder = (value: string) =>
  value.startsWith("#") ? undefined : value;

/** Подпись качества переводится в код сервера. */
const qualityStateCode = (label: string) => {
  if (label === "—") return undefined;
  switch (label.toLowerCase()) {
    case "годный":
      return "good";
    case "брак":
      return "scrap";
    case "окончательный брак":
      return "final_scrap";
    case "переделка":
      return "rework";
    default:
      return label;
  }
};

export const stockBalanceColumns: StockBalanceColumn[] = [
  {
    id: "sku",
    label: "Артикул",
    filterField: "sku",
    sortField: "sku",
    mapValue: dropNumericPlaceholder,
  },
  {
    id: "quantity",
    label: "Количество",
    filterField: "quantity",
    sortField: "quantity",
    mapValue: dropDash,
  },
  { id: "dimensions", label: "Размеры", headerClassName: "px-2" },
  {
    id: "operations",
    label: "Операции",
    filterField: "operations",
    sortField: "operations",
    headerClassName: "min-w-[140px]",
    // Ячейка печатает `formatCompletedOperationsLabel`: пустое состояние —
    // «не зафиксировано»/«без операций», а не «—» (#239), и сервер
    // (`_balance_operations_filter`) понимает обе подписи. Сбрасывать их
    // значило бы выбрать пустую строку и молча отправить фильтр без значения.
  },
  {
    id: "quality",
    label: "Статус качества",
    filterField: "quality",
    sortField: "quality",
    mapValue: qualityStateCode,
  },
  {
    id: "location",
    label: "Участок",
    filterField: "location",
    sortField: "location",
    hideWhenNoLocation: true,
    mapValue: dropNumericPlaceholder,
  },
];
