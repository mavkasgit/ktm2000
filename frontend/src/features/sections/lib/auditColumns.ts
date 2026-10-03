/**
 * Описание колонок журнала аудита — единственное место, где объявляется, что
 * это за колонка, как она фильтруется, сортируется и каким параметром уезжает
 * в запрос (#198, ADR-0038).
 *
 * Пока параметры собирались в `buildAuditColumnApiParams` пятью почти
 * одинаковыми строками, а подпись значения статуса жила в разметке шапки
 * тернарником, колонка называлась в двух местах, и шестая колонка потребовала
 * бы правки сборщика.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

export type AuditFilterField =
  | "createdAt"
  | "status"
  | "sectionName"
  | "productSku"
  | "action"
  | "entityType";

export type AuditColumn = ColumnSpec<AuditFilterField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: ширина колонки. */
  headerClassName?: string;
};

/** Значение «—» — это пусто, а не значение: сервер такого не понимает. */
const dropDash = (value: string) => (value === "—" ? undefined : value);


/**
 * Подписи типов сущностей журнала (`Задание` вместо `work_task`).
 *
 * Перебор живёт в `AuditEntityType` бэкенда и в журнале действий не является
 * частью производственного канона, поэтому словарь — здесь, рядом с
 * описанием колонки, которая его печатает и по нему же фильтрует.
 */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  product: "Артикул",
  section: "Участок",
  route: "Маршрут",
  production_plan: "Производственный план",
  plan_position: "Позиция плана",
  work_task: "Задание",
  rework_task: "Задание на переделку",
  transfer: "Передача",
  transfer_discrepancy: "Расхождение передачи",
  defect: "Брак",
  defect_item: "Запись о браке",
  defect_decision: "Решение по браку",
  import_batch: "Партия импорта",
  user: "Пользователь",
  daily_plan: "Суточный план",
};

/** Подпись типа сущности с номером: «Задание #42». */
export function entityLabel(entityType: string | null | undefined, entityId: number | null | undefined): string {
  if (!entityType) return "—";
  const name = ENTITY_TYPE_LABELS[entityType] ?? entityType;
  return entityId != null ? `${name} #${entityId}` : name;
}

const CODE_BY_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(ENTITY_TYPE_LABELS).map(([code, label]) => [label, code]),
);

/**
 * «Задание #42» — это вид сущности «Задание», а номер серверу не нужен.
 * Сервер фильтрует по коду, поэтому подпись возвращается в код: иначе выбор
 * «Задание» в фильтре ушёл бы запросом словом «Задание» и не нашёл ничего.
 */
const entityTypeOnly = (value: string) => {
  if (value === "—") return undefined;
  const hashIdx = value.indexOf(" #");
  const label = hashIdx >= 0 ? value.slice(0, hashIdx) : value;
  return CODE_BY_LABEL[label] ?? label;
};

const filterable = "p-0 text-left";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Служебные
 * колонки объявлены здесь же, иначе `map` по описанию их потерял бы.
 */
export const auditColumns: AuditColumn[] = [
  {
    id: "status",
    label: "Статус",
    headerClassName: `${filterable} w-[8%]`,
    filterField: "status",
    sortField: "status",
    apiParam: "status",
    // Значения статуса приходят из сервера сырыми («success»), а оператор
    // видит «Успешно»: подпись живёт здесь, а не тернарником в шапке.
    valueLabel: (value) =>
      value === "success" ? "Успешно" : value === "error" ? "Ошибка" : "Информация",
  },
  {
    id: "createdAt",
    label: "Дата и время",
    headerClassName: `${filterable} w-[16%]`,
    sortField: "createdAt",
    // Фильтра нет и не будет: сервер знает только диапазон `date_from` /
    // `date_to`, который уже вынесен в панель фильтров. Попапер выбора
    // одного момента времени не делал ничего — молчащий фильтр хуже его
    // отсутствия.
  },
  {
    id: "sectionName",
    label: "Участок",
    headerClassName: `${filterable} w-[14%]`,
    filterField: "sectionName",
    sortField: "sectionName",
    apiParam: "section_name",
    mapValue: dropDash,
  },
  { id: "task", label: "Задание", headerClassName: "w-[12%]" },
  {
    id: "productSku",
    label: "Артикул",
    headerClassName: `${filterable} w-[12%]`,
    filterField: "productSku",
    sortField: "productSku",
    apiParam: "product_sku",
    mapValue: dropDash,
  },
  {
    id: "action",
    label: "Действие",
    headerClassName: `${filterable} w-[14%]`,
    filterField: "action",
    sortField: "action",
    apiParam: "action",
    mapValue: dropDash,
  },
  {
    id: "entityType",
    label: "Сущность",
    headerClassName: `${filterable} w-[12%]`,
    filterField: "entityType",
    sortField: "entityType",
    apiParam: "entity_type",
    mapValue: entityTypeOnly,
  },
  { id: "details", label: "Подробности", headerClassName: "w-[12%]" },
];
