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
 */
import type { ProductFilters } from "@/shared/api/products";
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
 * фильтр есть, и `values` для попапера берутся из списка по этому же имени.
 */
export type RawMaterialColumnId = RawMaterialColumnField;

export type RawMaterialColumn = ColumnSpec<RawMaterialColumnField> & {
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
  },
  {
    id: "quantity_per_hanger",
    label: "Кол-во на подвесе",
    headerClassName: "p-0 w-48",
    filterField: "quantity_per_hanger",
    sortField: "quantity_per_hanger",
    toParams: qtyRange,
    paramKind: "number",
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
  },
  {
    id: "is_paired_profile",
    label: "Парный",
    headerClassName: "p-0 w-36",
    filterField: "is_paired_profile",
    sortField: "is_paired_profile",
    mapValue: yesNoFlag,
    paramKind: "boolean",
  },
  {
    id: "skip_shot_blast",
    label: "Пропуск участка",
    headerClassName: "p-0 w-36",
    filterField: "skip_shot_blast",
    sortField: "skip_shot_blast",
    mapValue: yesNoFlag,
    paramKind: "boolean",
  },
  {
    id: "is_laminated",
    label: "Ламинируется",
    headerClassName: "p-0 w-40",
    filterField: "is_laminated",
    sortField: "is_laminated",
    mapValue: yesNoFlag,
    paramKind: "boolean",
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
    RawMaterialColumnApiParams
  >(columnFilters, columnSearchQueries, rawMaterialColumns);
}
