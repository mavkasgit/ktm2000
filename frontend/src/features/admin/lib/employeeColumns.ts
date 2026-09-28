/**
 * Описание колонок списка сотрудников — единственное место, где объявляется,
 * что это за колонка, как она фильтруется, сортируется и каким параметром
 * уезжает в запрос (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока в компоненте стояло пять почти одинаковых блоков `<th>` с
 * `SortableFilterHeader`, а параметры собирались отдельной функцией с ручным
 * `pickColumnApiValue(…, "department", …)` и подстановкой `?sort=`, колонка
 * называлась в двух местах, и шестая потребовала бы правки обоих.
 *
 * **Фильтрует сервер только «Подразделение».** `list_employees`
 * (`backend/app/services/hrms_employees.py`) принимает `department`, `search`
 * и `sort` — и всё. У остальных четырёх колонок попапер был, а параметра у
 * него не было: значение уходило в состояние таблицы, зажигало кнопку сброса
 * и молча не сужало выборку. Объявить их с `filterField` нельзя (в запрос
 * уехал бы параметр, которого сервер не понимает), а `clientOnly` — тем
 * более: клиентской фильтрации на экране нет, строки приходят постранично с
 * сервера, и «фильтр» по текущей странице был бы ложью. Поэтому по ADR-0038
 * (§4, «Молчащий фильтр хуже его отсутствия») эти четыре колонки объявлены
 * без `filterField`, и шапка рисует подпись с кнопкой сортировки.
 *
 * Сортирует сервер все пять: `_SORT_COLUMNS` в том же модуле содержит
 * `hrms_id`, `name`, `tab_number`, `position`, `department`, а неизвестное
 * поле сортировки `apply_sort` отвергает. `sortField` поэтому объявляет поле
 * **колонки** (`hrmsId`, `tabNumber`), а серверное имя лежит в
 * `EMPLOYEE_SORT_FIELD_TO_API` — так же, как в
 * `features/execution/lib/executionSortMapping.ts`. Объявить `sortField`
 * сразу серверным именем нельзя: `DataTableColumnHeader` отдаёт в сортировку
 * `filterField ?? sortField`, и колонка, у которой `filterField` отличается
 * от `sortField`, искала бы в `currentSorts` имя, которого там нет, — значок
 * сортировки и бейдж приоритета не рисовались бы никогда.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля колонок: так их зовёт шапка и так их зовёт состояние таблицы. */
export type EmployeeSortField = "hrmsId" | "name" | "tabNumber" | "position" | "department";

/** Поля сортировки, которые принимает `GET /employees`. */
export type EmployeeSortApiField =
  | "hrms_id"
  | "name"
  | "tab_number"
  | "position"
  | "department";

/**
 * Поле колонки → поле в `?sort=`. Список серверных полей — `_SORT_COLUMNS`
 * в `backend/app/services/hrms_employees.py`; `apply_sort` отвечает 400 на
 * поле, которого в нём нет, поэтому колонка сортируется только тем, что
 * здесь объявлено.
 */
export const EMPLOYEE_SORT_FIELD_TO_API: Record<EmployeeSortField, EmployeeSortApiField> = {
  hrmsId: "hrms_id",
  name: "name",
  tabNumber: "tab_number",
  position: "position",
  department: "department",
};

export type EmployeeColumn = ColumnSpec<EmployeeSortField> & {
  /**
   * Совпадает с полем колонки: по нему берутся значения поповера, и совпадение
   * проверяется тестом — иначе `map` по шапке потерял бы колонку молча.
   */
  id: EmployeeSortField;
  label: string;
  /** Класс `<th>` сверх общего: ширина колонки. */
  headerClassName?: string;
};

/** Значение «—» — это отсутствие подразделения, а не его имя. */
const dropDash = (value: string) => (value === "—" ? undefined : value);

/** Отступы шапки общие: попапер фильтра занимает ячейку целиком. */
const headerBase = "p-0 px-4 text-left";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы: `map` по
 * описанию иначе разъехался бы с `<td>`.
 */
export const employeeColumns: EmployeeColumn[] = [
  { id: "hrmsId", label: "HRMS ID", sortField: "hrmsId", headerClassName: `${headerBase} w-24` },
  { id: "name", label: "ФИО", sortField: "name", headerClassName: headerBase },
  { id: "tabNumber", label: "Таб. №", sortField: "tabNumber", headerClassName: `${headerBase} w-28` },
  { id: "position", label: "Должность", sortField: "position", headerClassName: headerBase },
  {
    id: "department",
    label: "Подразделение",
    filterField: "department",
    sortField: "department",
    mapValue: dropDash,
    headerClassName: headerBase,
  },
];
