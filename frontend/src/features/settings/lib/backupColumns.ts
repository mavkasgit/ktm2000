/**
 * Описание колонок списка бэкапов — единственное место, где объявляется, что
 * это за колонка, как она фильтруется, сортируется, подписывается и каким
 * параметром уезжает в запрос (#198, ADR-0038).
 *
 * Пока шапка собиралась шестью блоками `<th>` с `SortableFilterHeader`, а
 * `buildBackupsQueryParams` перечислял те же шесть колонок вызовами
 * `pickColumnApiValue`, колонка называлась в двух местах, а перекодировки
 * («—» в комментарии, строка размера вместо числа) жили в сборщике. Седьмая
 * колонка потребовала бы правки обоих мест.
 *
 * Перекодировки живут здесь, потому что это свойство колонки, а не экрана:
 * сервер понимает не то, что видит оператор в поповере фильтра.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { backupTypeLabels } from "@/shared/lib/generated-labels";

/**
 * Колонки списка бэкапов: их все умеет сортировать и фильтровать сервер — у
 * каждой есть параметр в `ListBackupsParams`. Клиентских колонок на этом
 * экране нет (страница не фильтрует строки сама, `buildColumnFilterPredicate`
 * не зовётся), поэтому `clientOnly` здесь не встречается: фильтр колонки,
 * который сервер не понимает, уехал бы в запрос и сузил список до пустого.
 */
export type BackupSortField =
  | "filename"
  | "db_name"
  | "backup_type"
  | "size"
  | "created_at"
  | "comment";

export type BackupColumn = ColumnSpec<BackupSortField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: поповер фильтра рисует отступы сам. */
  headerClassName?: string;
};

/** Поповер фильтра занимает ячейку целиком, поэтому у колонок с фильтром `p-0`. */
const filtered = "p-0";

/** «—» в комментарии — это пусто, а не значение: сервер такого не понимает. */
const dropDash = (value: string) => (value === "—" ? undefined : value);

/**
 * Размер приходит значением колонки строкой, а сервер ждёт число. Нечисловое
 * значение (опечатка в поповере) уходить не должно — иначе запрос молча
 * вернул бы список, отфильтрованный не по тому, что выбрал оператор.
 */
const sizeBytes = (value: string) => {
  const bytes = Number.parseInt(value, 10);
  return Number.isFinite(bytes) ? String(bytes) : undefined;
};

/** Размер бэкапа в том виде, в каком его видит оператор. */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

/** Дата бэкапа в локализованном виде — и в таблице, и в поповере фильтра. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU");
}

/**
 * Порядок строк до первого клика по шапке: свежие бэкапы сверху. Он не
 * считается активными фильтрами, и сброс возвращает его, а не пустоту.
 */
export const backupsDefaultSort: ReadonlyArray<{
  field: BackupSortField;
  order: "asc" | "desc";
}> = [{ field: "created_at", order: "desc" }];

/**
 * Тот же порядок строкой `поле:порядок`: так его ждёт API. Объявлен рядом с
 * `backupsDefaultSort`, чтобы «по умолчанию свежие сверху» не расходилось на
 * две формулировки — таблица и запросы мимо неё (удаление старых копий).
 */
export const backupsDefaultSortParam = "created_at:desc";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Служебные
 * колонки (галочка выбора и «Действия») остались в разметке: они не имеют ни
 * фильтра, ни сортировки, и в описание им нечего объявлять.
 */
export const backupColumns: BackupColumn[] = [
  {
    id: "filename",
    label: "Имя файла",
    filterField: "filename",
    sortField: "filename",
    headerClassName: filtered,
  },
  {
    id: "db_name",
    label: "База данных",
    filterField: "db_name",
    sortField: "db_name",
    headerClassName: filtered,
  },
  {
    id: "backup_type",
    label: "Тип",
    filterField: "backup_type",
    sortField: "backup_type",
    headerClassName: filtered,
    // видит «Ежемесячный», а сервер ждёт код `monthly`
    valueLabel: (value) => backupTypeLabels[value] || value,
  },
  {
    id: "size",
    label: "Размер",
    filterField: "size",
    sortField: "size",
    headerClassName: filtered,
    mapValue: sizeBytes,
    valueLabel: (value) => formatBytes(Number(value)),
  },
  {
    id: "created_at",
    label: "Дата создания",
    filterField: "created_at",
    sortField: "created_at",
    headerClassName: filtered,
    valueLabel: formatDate,
  },
  {
    id: "comment",
    label: "Комментарий",
    filterField: "comment",
    sortField: "comment",
    headerClassName: filtered,
    mapValue: dropDash,
  },
];
