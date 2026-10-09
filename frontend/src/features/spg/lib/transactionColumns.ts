/**
 * Описание колонок ящика истории движения — единственное место, где
 * объявляется, что это за колонка, как она фильтруется, сортируется и каким
 * параметром уезжает в запрос (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока шапка ящика собиралась из семи одинаковых блоков `<th>`, а параметры
 * запроса — из `buildTxColumnApiParams` с перечислением колонок, одна колонка
 * называлась в двух местах, и переименование «Откуда» в `from_location` надо
 * было искать вручную в обоих.
 *
 * Имена колонок короткие (`from`, `to`, `quality`), а параметры бэкенда
 * `GET /stock/transactions` длиннее (`from_location`, `to_location`,
 * `quality_state`), поэтому расхождение выражено явно, через `apiParam`.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { TransactionSortField } from "@/shared/lib/stockSortParams";
import {
  formatQualityStateLabel,
  formatStockReasonLabel,
  type StockTransactionEntry,
} from "@/shared/api/stock";
import { fmtQty } from "@/shared/lib/quantityFormat";

export type TransactionColumn = ColumnSpec<
  TransactionSortField,
  TransactionSortField,
  StockTransactionEntry
> & {
  id: string;
  label: string;
  headerClassName?: string;
};

/** Подпись даты движения — и в ячейке, и в читателе значения колонки. */
export function formatTxDate(createdAt: string | null): string {
  if (!createdAt) return "—";
  return new Date(createdAt).toLocaleString("ru-RU");
}

/** Качество печатается переходом, когда состояние изменилось. */
export function formatTxQuality(tx: StockTransactionEntry): string {
  if (tx.from_quality_state !== tx.to_quality_state) {
    return `${formatQualityStateLabel(tx.from_quality_state)} → ${formatQualityStateLabel(tx.to_quality_state)}`;
  }
  return formatQualityStateLabel(tx.from_quality_state);
}

/**
 * Значение ячейки строки движения (#322): читатель значения объявлен в
 * описании колонки (`cellValue`), а разметка тела берёт то же значение — иначе
 * список попапера и фильтр могли бы показать не то, что напечатано в строке.
 */
export function getTxCellValue(tx: StockTransactionEntry, field: TransactionSortField): string {
  switch (field) {
    case "date":
      return formatTxDate(tx.created_at);
    case "reason":
      return formatStockReasonLabel(String(tx.reason), tx.source_ref);
    case "from":
      return tx.from_location_name || (tx.from_location_id ? `#${tx.from_location_id}` : "—");
    case "to":
      return tx.to_location_name || (tx.to_location_id ? `#${tx.to_location_id}` : "—");
    case "quantity":
      return fmtQty(tx.quantity);
    case "quality":
      return formatTxQuality(tx);
    case "comment":
      return tx.comment || "—";
  }
}

/** Пусто — не значение: сервер такого не понимает. */
const dropDash = (value: string) => (value === "—" ? undefined : value);

/**
 * В колонке качества видно и переход («Годный → Брак»), и просто состояние,
 * а параметр у бэкенда один и точный (`exact match on from/to quality
 * state`). Поэтому качество — точная колонка: выбранное значение переводится
 * в код состояния, а не подстрока из поисковой строки попапера.
 */
const qualityStateCode = (label: string) => {
  if (label === "—") return undefined;
  const state = label.split(" → ")[0]?.trim() ?? label;
  switch (state.toLowerCase()) {
    case "годный":
      return "good";
    case "брак":
      return "scrap";
    case "окончательный брак":
      return "final_scrap";
    case "переделка":
      return "rework";
    default:
      return state;
  }
};

const cell = "p-0 text-left";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы.
 */
export const transactionColumns: TransactionColumn[] = [
  {
    id: "date",
    label: "Дата",
    headerClassName: cell,
    sortField: "date",
    // Фильтра нет: бэкенд знает только диапазон `date_from` / `date_to`,
    // и он уже вынесен в панель над таблицей. Попапер выбора одного момента
    // времени ничего не отправлял — молчащий фильтр хуже его отсутствия.
  },
  {
    id: "reason",
    label: "Причина",
    headerClassName: cell,
    filterField: "reason",
    sortField: "reason",
    mapValue: dropDash,
    cellValue: (tx) => getTxCellValue(tx, "reason"),
  },
  {
    id: "from",
    label: "Откуда",
    headerClassName: cell,
    filterField: "from",
    sortField: "from",
    apiParam: "from_location",
    mapValue: dropDash,
    cellValue: (tx) => getTxCellValue(tx, "from"),
  },
  {
    id: "to",
    label: "Куда",
    headerClassName: cell,
    filterField: "to",
    sortField: "to",
    apiParam: "to_location",
    mapValue: dropDash,
    cellValue: (tx) => getTxCellValue(tx, "to"),
  },
  {
    id: "quantity",
    label: "Кол-во",
    headerClassName: "p-0 text-right",
    sortField: "quantity",
    // Фильтра нет: у `GET /stock/transactions` нет параметра количества, и
    // колонка показывала попапер, который менял только счётчик активных
    // фильтров. Количество — свойство строки движения, а не разрез выборки.
  },
  {
    id: "quality",
    label: "Качество",
    headerClassName: cell,
    filterField: "quality",
    sortField: "quality",
    exactMatch: true,
    apiParam: "quality_state",
    mapValue: qualityStateCode,
    cellValue: (tx) => getTxCellValue(tx, "quality"),
  },
  {
    id: "comment",
    label: "Комментарий",
    headerClassName: cell,
    filterField: "comment",
    sortField: "comment",
    mapValue: dropDash,
    cellValue: (tx) => getTxCellValue(tx, "comment"),
  },
];
