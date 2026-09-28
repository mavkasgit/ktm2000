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

import { fmtQtyPrecise, QTY_EMPTY } from "@/shared/lib/quantityFormat";

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

/**
 * Формат «Итога» — дробь живая, домен `fmtQtyPrecise` (ADR-0040). Источник
 * один: пока ячейка печатала `fmtQtyPrecise(primary.total)`, а попапер и
 * предикат брали `String(row.total)`, дробной итог в строке читался как
 * «2,5», а в списке фильтра как «2.5» — выбранное значение не совпадало с
 * напечатанным. Поле берётся `row.total`: это уже итог «основной длины»
 * с авто-приоритетом и ручным запасным значением, и именно его сортирует
 * `sortHangerCalcRows`, то есть расхождение источника закрывается здесь.
 */
export function hangerCalcTotalText(row: HangerCalcRow | PairedHangerCalcRow): string {
  return row.total != null ? fmtQtyPrecise(row.total) : QTY_EMPTY;
}

/** Значение ячейки: и в списке фильтра, и в ключе клиентской выборки. */
export function hangerCalcCellValue(
  row: HangerCalcRow | PairedHangerCalcRow,
  field: HangerCalcSortField,
): string {
  if (field === "sku") return rowSku(row);
  if (field === "total") return hangerCalcTotalText(row);
  return row.limiter ? LIMITER_LABELS[row.limiter] : "—";
}

/**
 * Порядок значений «Итога» в поповере. Сравнивается напечатанная строка:
 * «2,5» — это не `Number("2,5")`, то есть разбор запятой обязателен, иначе
 * список сортировался бы по `NaN`. «—» (нет значения) уходит в конец.
 */
export function compareHangerCalcTotals(a: string, b: string): number {
  // «—» и любой не-числовой текст дают `NaN` и уходят в конец списка.
  const numA = Number(a.replace(",", "."));
  const numB = Number(b.replace(",", "."));
  if (!Number.isFinite(numA)) return Number.isFinite(numB) ? 1 : 0;
  if (!Number.isFinite(numB)) return -1;
  return numA - numB;
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
  },
  { id: "perimeter", label: "Периметр", headerClassName: "w-28" },
  { id: "mountWidth", label: "Габарит", headerClassName: "w-28" },
  {
    id: "length",
    // Подпись длины, а не «длины → кол-во»: строка разбита на подстроки по
    // длинам (ADR-0050), и своя длина каждой подстроки печатается в своей
    // строке, а её N — в «Итоге» этой же подстроки.
    label: "Длина",
    headerClassName: "min-w-56",
  },
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
    sortValues: compareHangerCalcTotals,
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
