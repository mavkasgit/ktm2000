/**
 * Описание колонок справочника сырья — единственное место, где объявляется,
 * что это за колонка, как она фильтруется, сортируется и каким параметром
 * уезжает в запрос (#198, ADR-0038).
 *
 * Пока семантика жила в двух местах сразу, колонка называлась дважды: в
 * разметке шапки шестью почти одинаковыми блоками `<th>` с
 * `SortableFilterHeader`, а в `buildRawMaterialsApiParams` — шестью строками
 * с `pickColumnApiValue` по имени поля. Седьмая колонка потребовала бы
 * правки обоих списков, а расхождение между ними молча ломало бы фильтр:
 * колонка видна, попапер работает, параметр не уезжает.
 *
 * Все шесть колонок фильтрует и сортирует сервер: у `GET /products` есть
 * `sku`, диапазоны `length_from`/`length_to` и `qty_from`/`qty_to` и три
 * флага (`backend/app/api/routes/products.py`, `list_products`), а набор
 * полей сортировки `_SORT_COLUMNS` содержит все шесть. Поэтому `clientOnly`
 * здесь не встречается: колонок, фильтруемых на клиенте, на этом экране нет,
 * и молчаливое «не отправлять» скрыло бы регресс — значение уехало бы под
 * именем колонки и сузило бы выборку до пустой.
 *
 * Диапазоны «Длина от/до» и «Кол-во от/до» — не колонки, а поля панели
 * фильтров: попапера в шапке у них нет, значения они принимают не из списка,
 * а вводом, и в описание колонок не входят. Их состояние живёт на экране.
 *
 * Список значений попапера тоже объявлен здесь (#322): у колонок-флагов —
 * готовым доменом `filterValues` («Да»/«Нет» не зависят от строк), у
 * «Размеров» — читателем строк `filterValuesFrom` (у артикула несколько длин),
 * у остальных — читателем значения `cellValue`. Поэтому экран больше не держит
 * карту `uniqueValues` и не перечисляет колонки ради попапера.
 */
import type { Product, ProductFilters } from "@/shared/api/products";
import { primaryHangerValue, productLengths } from "@/shared/lib/hangerQuantity";
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";
import { buildTypedColumnApiParams, type ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля, по которым экран фильтрует колонки и строит сортировку. */
export type RawMaterialColumnField =
  | "sku"
  | "quantity_per_hanger"
  | "length_mm"
  | "is_paired_profile"
  | "skip_shot_blast"
  | "is_laminated";

/**
 * Идентификатор колонки совпадает с полем фильтра: у всех шести колонок
 * фильтр есть, и значения попапера берутся из описания по этому же имени.
 */
export type RawMaterialColumnId = RawMaterialColumnField;

export type RawMaterialColumn = ColumnSpec<RawMaterialColumnField, RawMaterialColumnField, Product> & {
  id: RawMaterialColumnId;
  label: string;
  /** Класс `<th>` сверх общего: попапер фильтра занимает ячейку целиком. */
  headerClassName?: string;
  /** Фильтр есть у всех колонок экрана: колонки без него здесь не бывает. */
  filterField: RawMaterialColumnField;
};

/**
 * Оператор выбирает «Да»/«Нет», а `GET /products` ждёт флаг: подпись
 * значения живёт в списке, перекодировка — здесь. Всё, кроме этих двух слов,
 * в параметр не превращается: набранный в попапере «да» — это поиск по
 * списку, а не выбор значения.
 */
const yesNoFlag = (value: string): boolean | undefined => {
  if (value === "Да") return true;
  if (value === "Нет") return false;
  return undefined;
};

/**
 * Длина и количество — это диапазон, поэтому одна выбранная длина раскладывается
 * в две границы. «2700» уходит как `length_from=2700&length_to=2700`; граница
 * есть у обоих концов, потому что выбор оператора — точное значение, а не «от».
 * Нечисловой ввод (в том числе «—») параметра не даёт вовсе.
 */
const lengthRange = (value: string): Record<string, number> => {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return {};
  return { length_from: parsed, length_to: parsed };
};

/** То же для количества на подвесе, только целым числом. */
const qtyRange = (value: string): Record<string, number> => {
  if (value === "—") return {};
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return {};
  return { qty_from: parsed, qty_to: parsed };
};

/**
 * Домен трёх колонок-флагов: набор значений один и тот же на всех строках,
 * поэтому он объявлен в описании, а не выведен перебором строк. Вывод из строк
 * терял бы значения, которых нет на текущей странице, и менял бы порядок.
 */
const yesNoValues: readonly string[] = ["Да", "Нет"];

/**
 * Порядок значения «Кол-во на подвесе»: числа по возрастанию, «—» в конце.
 * Значение уже отформатировано (`fmtQtyPrecise`), поэтому десятичный разделитель
 * — запятая, и сравнивать сырым `parseFloat` нельзя: «2,5» дало бы 2.
 */
const compareHangerQty = (a: string, b: string): number => {
  const left = Number.parseFloat(a.replace(",", "."));
  const right = Number.parseFloat(b.replace(",", "."));
  if (Number.isNaN(left)) return Number.isNaN(right) ? 0 : 1;
  if (Number.isNaN(right)) return -1;
  return left - right;
};

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы.
 *
 * Подпись «Пропуск участка» подставляет страница: это название участка из
 * правил выбора маршрута, а не литерал (см. `skipShotBlastSectionLabel`).
 */
export const rawMaterialColumns: RawMaterialColumn[] = [
  {
    id: "sku",
    label: "Артикул",
    headerClassName: "p-0 w-48",
    filterField: "sku",
    sortField: "sku",
    cellValue: (product) => product.sku,
    // Порядок артикулов — как у `Array.prototype.sort()` по умолчанию: коды
    // UTF-16, а не локаль. Экран сортировал именно так.
    sortValues: (a, b) => (a < b ? -1 : a > b ? 1 : 0),
  },
  {
    id: "quantity_per_hanger",
    label: "Кол-во на подвесе",
    headerClassName: "p-0 w-48",
    filterField: "quantity_per_hanger",
    sortField: "quantity_per_hanger",
    toParams: qtyRange,
    paramKind: "number",
    // Значение — основная длина: серверный фильтр `qty_from/qty_to` и сортировка
    // считают по ней, и ячейка печатает её же (спека #59 п. 25). Нет значения —
    // «—», как и в ячейке, а не «0».
    cellValue: (product) => fmtQtyPrecise(primaryHangerValue(product)?.value ?? null),
    sortValues: compareHangerQty,
  },
  {
    id: "length_mm",
    label: "Размеры",
    headerClassName: "p-0 w-40",
    filterField: "length_mm",
    sortField: "length_mm",
    toParams: lengthRange,
    paramKind: "number",
    valueLabel: (value) => `${value} мм`,
    // «Размеры» многозначны: у артикула несколько длин, и список попапера — их
    // объединение по строкам.
    filterValuesFrom: (product) => productLengths(product).map(String),
    sortValues: (a, b) => Number(a) - Number(b),
  },
  {
    id: "is_paired_profile",
    label: "Парный",
    headerClassName: "p-0 w-36",
    filterField: "is_paired_profile",
    sortField: "is_paired_profile",
    mapValue: yesNoFlag,
    paramKind: "boolean",
    filterValues: yesNoValues,
  },
  {
    id: "skip_shot_blast",
    label: "Пропуск участка",
    headerClassName: "p-0 w-36",
    filterField: "skip_shot_blast",
    sortField: "skip_shot_blast",
    mapValue: yesNoFlag,
    paramKind: "boolean",
    filterValues: yesNoValues,
  },
  {
    id: "is_laminated",
    label: "Ламинируется",
    headerClassName: "p-0 w-40",
    filterField: "is_laminated",
    sortField: "is_laminated",
    mapValue: yesNoFlag,
    paramKind: "boolean",
    filterValues: yesNoValues,
  },
];

/** Параметры запроса, которые дают отфильтрованные колонки сырья. */
export type RawMaterialColumnApiParams = Pick<
  ProductFilters,
  | "sku"
  | "length_from"
  | "length_to"
  | "qty_from"
  | "qty_to"
  | "is_paired_profile"
  | "skip_shot_blast"
  | "is_laminated"
>;

/**
 * Сборщик возвращает значения в том виде, в каком их ждёт контракт:
 * длина и количество — числами, флаги — булевыми. Род объявлен в описании
 * колонки (`paramKind`), приводит общий сборщик, поэтому ни контракт
 * `ProductFilters` не приходится ослаблять до `number | string`, ни колонки
 * приходится перечислять здесь. Перечисления колонок нет — список берётся из
 * описания (ADR-0038).
 */
export function buildRawMaterialColumnApiParams(
  columnFilters: Partial<Record<RawMaterialColumnField, Set<string>>>,
  columnSearchQueries: Partial<Record<RawMaterialColumnField, string>>,
): RawMaterialColumnApiParams {
  return buildTypedColumnApiParams<
    RawMaterialColumnField,
    RawMaterialColumnApiParams,
    RawMaterialColumnField,
    Product
  >(columnFilters, columnSearchQueries, rawMaterialColumns);
}
