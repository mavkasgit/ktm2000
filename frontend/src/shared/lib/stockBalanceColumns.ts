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
 * `GET /stock/balance` не принимает параметра габарита, а `BALANCE_SORT_FIELDS`
 * в `backend/app/stock/api.py` его не содержит. Разные длины одного артикула —
 * разные строки (ADR-0001), и это свойство строки, а не колонки, по которой
 * можно отфильтровать.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { BalanceSortField } from "@/shared/lib/stockSortParams";
import {
  balanceGroupSkus,
  completedOperationsServerLabel,
  formatBalanceGroupLabel,
  formatQualityStateLabel,
  type StockBalanceEntry,
} from "@/shared/api/stock";
import { fmtQty } from "@/shared/lib/quantityFormat";

export type StockBalanceColumn = ColumnSpec<
  BalanceSortField,
  BalanceSortField,
  StockBalanceEntry
> & {
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
    // Ячейка группы — её подпись «A, B (эквиваленты)», а не одна SKU-строка:
    // сервер уже сложил кучу, и колонка читает поля группы.
    cellValue: (balance) => formatBalanceGroupLabel(balance),
    // Список фильтра — отдельные SKU группы: сервер ищет `?sku=` по строкам
    // кучи, и значение «A, B» он бы не нашёл.
    filterValuesFrom: (balance) => balanceGroupSkus(balance),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "quantity",
    label: "Количество",
    filterField: "quantity",
    sortField: "quantity",
    mapValue: dropDash,
    cellValue: (balance) => fmtQty(balance.balance_qty),
    sortValues: (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
  },
  { id: "dimensions", label: "Размеры", headerClassName: "px-2" },
  {
    id: "operations",
    label: "Операции",
    filterField: "operations",
    sortField: "operations",
    headerClassName: "min-w-[140px]",
    // Ячейка печатает прочерк для обоих пустых состояний, а в списке фильтра
    // стоят серверные подписи («не зафиксировано» / «без операций»): это выбор,
    // и двумя одинаковыми прочерками выбрать нельзя. В запрос уходит ровно то,
    // что выбрано — `_balance_operations_filter` разбирает обе подписи в явные
    // предикаты, прочерк он не знает. Сбрасывать их значило бы выбрать пустую
    // строку и молча отправить фильтр без значения.
    cellValue: (balance) =>
      completedOperationsServerLabel(balance.completed_operations, balance.completed_stages),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "quality",
    label: "Статус качества",
    filterField: "quality",
    sortField: "quality",
    mapValue: qualityStateCode,
    cellValue: (balance) => formatQualityStateLabel(balance.quality_state),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "location",
    label: "Участок",
    filterField: "location",
    sortField: "location",
    hideWhenNoLocation: true,
    mapValue: dropNumericPlaceholder,
    cellValue: (balance) => balance.location_name || `#${balance.location_id}`,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
];
