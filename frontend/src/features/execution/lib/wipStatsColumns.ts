/**
 * Описание колонок сводки по незавершённому производству — единственное место,
 * где объявляется, что это за колонка, как она фильтруется и сортируется
 * (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока две колонки шапки собирались в диалоге двумя блоками `<th>` с
 * `SortableFilterHeader` руками, каждая колонка называла своё поле трижды: в
 * шапке, в списке значений фильтра и в предикате клиентской фильтрации. Третья
 * фильтруемая колонка потребовала бы правки всех трёх мест, а колонка «Размер»
 * жила вне описания и из `map` по нему выпала бы.
 *
 * Таблица целиком клиентская: `getProductWipStats` знает только артикул, и
 * фильтры по «ГХП» и «Остатку» в запрос не уезжают. Поэтому у каждой
 * фильтруемой колонки проставлен `clientOnly` — иначе объявление выглядело бы
 * как обычная серверная колонка, и появление серверной выборки молча увезло бы
 * фильтр под именем колонки в запрос, который такого параметра не понимает.
 * Собирать параметры из этого описания нечего: `buildColumnApiParams` вернёт
 * пустой объект, и это зафиксировано тестом.
 */
import type { ProductWipRemainder } from "@/shared/api/productionPlans";
import { fmtQty } from "@/shared/lib/quantityFormat";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля фильтра и сортировки сводки: обе связи у колонок совпадают. */
export type WipStatsField = "name" | "qty";

export type WipStatsColumn = ColumnSpec<WipStatsField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: `p-0` у колонок с поповером и ширина колонки. */
  headerClassName?: string;
};

/** Попапер фильтра рисует отступы сам, поэтому у фильтруемых колонок их нет. */
const filtered = "p-0";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Колонка
 * «Размер» объявлена здесь же, иначе `map` по описанию её потерял бы, и шапка
 * разъехалась бы с телом.
 */
export const wipStatsColumns: WipStatsColumn[] = [
  {
    id: "name",
    label: "ГХП (выполненные операции)",
    filterField: "name",
    sortField: "name",
    headerClassName: filtered,
    clientOnly: true,
  },
  // Служебная колонка: «Размер» выводится из габаритов строки, фильтровать его
  // нечем (значения в поповере пришлось бы собирать из подписи размера), и в
  // запрос колонка не уезжает.
  { id: "dimensions", label: "Размер", headerClassName: "px-2 w-[100px]" },
  {
    id: "qty",
    label: "Остаток (шт.)",
    filterField: "qty",
    sortField: "qty",
    headerClassName: `${filtered} w-[180px] text-right`,
    clientOnly: true,
  },
];

/**
 * Формат «Остатка» — целые штуки, домен `fmtQty` (ADR-0040). Вынесен
 * рядом с описанием колонки и используется в ячейке, в поповере и в
 * предикате: пока попапер отдавал `String(row.quantity)`, а ячейка печатала
 * `fmtQty`, дробный остаток в таблице читался как «3», а в списке фильтра
 * как «2,5» — и выбранное значение не совпадало с напечатанным.
 */
export function wipStatsQtyText(row: ProductWipRemainder): string {
  return fmtQty(row.quantity);
}

/**
 * Порядок значений «Остатка» в поповере: сравнивается напечатанная строка,
 * а не сырое число, — иначе список сортировался бы по значениям, которых
 * оператор в таблице не видит. Не-число («—») уходит в конец.
 */
export function wipStatsQtyCompare(a: string, b: string): number {
  const numA = Number(a);
  const numB = Number(b);
  if (!Number.isFinite(numA)) return Number.isFinite(numB) ? 1 : 0;
  if (!Number.isFinite(numB)) return -1;
  return numA - numB;
}

/**
 * Значение ячейки, по которому работает клиентский фильтр колонки. Поля
 * названы здесь же: пока предикат сравнивал поле строкой, новое поле можно
 * было забыть, и фильтр по нему молча ничего не сужал. «Остаток» берёт
 * тот же форматтер, что и ячейка, — иначе попапер показывал бы оператору
 * число, которого в строке нет.
 */
export function wipStatsCellValue(row: ProductWipRemainder, field: WipStatsField): string {
  return field === "name" ? row.spg_name : wipStatsQtyText(row);
}

/**
 * Значение для сортировки. Остаток остаётся числом: сравнение строк дало бы
 * порядок «10» раньше «4».
 */
export function wipStatsSortValue(row: ProductWipRemainder, field: WipStatsField): string | number {
  return field === "qty" ? row.quantity : row.spg_name;
}
