/**
 * Описание колонок таблицы «Расчёт подвесов» — единственное место, где
 * объявляется, что это за колонка, как она фильтруется, сортируется и каким
 * параметром уезжает в запрос (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока семантика жила в компоненте, колонка называлась в трёх местах: в шапке
 * тремя вызовами `SortableFilterHeader` с раскрытыми полями, в `apiParams`
 * через `buildSortParam` с функцией-маппером и в `uniqueValues`/`predicate` —
 * перебором полей. Список колонок в шапке и список, по которому строится
 * клиентская выборка, могли разойтись, и разойтись молча.
 *
 * Особенность экрана: **все** фильтры колонок здесь клиентские — в запрос
 * уходит только `sort`, а строки сужает предикат по уже загруженному набору.
 * Поэтому у каждой фильтруемой колонки объявлен `clientOnly`: без него
 * объявление выглядело бы как обычная серверная колонка, и добавление
 * серверной выборки молча увезло бы фильтр по «Итогу» на сервер под именем
 * колонки. Фильтр при этом остаётся в шапке — он выбирается из списка
 * значений и применяется к строкам на клиенте, поэтому `filterField` объявлен
 * (без `filterField` объявляется колонка, у которой фильтра нет вовсе, а не
 * клиентский).
 *
 * Сортировка тут двухродная: сервер умеет только артикул, а «Итог» и
 * «Лимитер» считаются на клиенте (`sortHangerCalcRows`), и подменять их
 * другим полем нельзя — оператор кликнул бы по колонке и не увидел эффекта.
 * Род сортировки объявлен отдельно, в `buildHangerCalcSortParam`.
 */
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { buildSortParam } from "@/shared/lib/sortQueryParam";

import {
  LIMITER_LABELS,
  rowSku,
  type HangerCalcRow,
  type HangerCalcSortField,
  type PairedHangerCalcRow,
} from "./hangerCalcRows";

export type HangerCalcColumn = ColumnSpec<HangerCalcSortField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: ширина колонки. */
  headerClassName?: string;
  /**
   * Порядок значений в поповере фильтра. Без него значения шли бы в порядке
   * строк таблицы, и список «Итогов» начинался бы с произвольного числа.
   */
  sortValues?: (a: string, b: string) => number;
};

/** Значение ячейки: и в списке фильтра, и в ключе клиентской выборки. */
export function hangerCalcCellValue(
  row: HangerCalcRow | PairedHangerCalcRow,
  field: HangerCalcSortField,
): string {
  if (field === "sku") return rowSku(row);
  if (field === "total") return row.total != null ? String(row.total) : "—";
  return row.limiter ? LIMITER_LABELS[row.limiter] : "—";
}

/** `p-0` — попапер фильтра сам занимает всю ячейку шапки. */
const filterable = "p-0";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы (по одному
 * `<td>` на колонку в `HangerCalcRowView` и `PairedHangerRowView`, плюс
 * служебный угол сброса). Служебные и нефильтруемые колонки объявлены здесь
 * же, иначе `map` по описанию их потерял бы.
 */
export const hangerCalcColumns: HangerCalcColumn[] = [
  {
    id: "sku",
    label: "Артикул",
    headerClassName: `${filterable} min-w-48`,
    filterField: "sku",
    sortField: "sku",
    clientOnly: true,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  { id: "perimeter", label: "Периметр", headerClassName: "w-28" },
  { id: "mountWidth", label: "Габарит", headerClassName: "w-28" },
  { id: "lengths", label: "Длины → кол-во", headerClassName: "min-w-56" },
  { id: "byArea", label: "По площади", headerClassName: "w-24" },
  { id: "bySize", label: "По размеру", headerClassName: "w-24" },
  {
    id: "total",
    label: "Итог",
    headerClassName: `${filterable} w-24`,
    filterField: "total",
    // Сортируется на клиенте: сервер считает «Итог» у себя и в `?sort=` его
    // не понимает.
    sortField: "total",
    clientOnly: true,
    // Числа по возрастанию, «—» (нет значения) в конец.
    sortValues: (a, b) => (a === "—" ? 1 : b === "—" ? -1 : Number(a) - Number(b)),
  },
  {
    id: "limiter",
    label: "Лимитер",
    headerClassName: `${filterable} w-28`,
    filterField: "limiter",
    // Тоже клиентская сортировка: лимитер выводится из результата расчёта.
    sortField: "limiter",
    clientOnly: true,
  },
  { id: "areaM2", label: "м² на подвес", headerClassName: "w-28" },
];

/** Сортировка, которая уходит на сервер: только артикул. */
const SERVER_SORTED: Record<HangerCalcSortField, boolean> = {
  sku: true,
  total: false,
  limiter: false,
};

/**
 * `?sort=` для products-API. Артикул уходит на сервер, а «Итог» и «Лимитер»
 * остаются клиентскими: строки пересобираются из двух запросов (одиночные и
 * парные), и серверный порядок держит только первичную выборку.
 */
export function buildHangerCalcSortParam(
  sortConfigs: SortConfig<HangerCalcSortField>[],
): string | undefined {
  return buildSortParam(sortConfigs, (field) => (SERVER_SORTED[field] ? field : undefined));
}
