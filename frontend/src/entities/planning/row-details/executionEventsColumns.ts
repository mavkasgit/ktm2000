/**
 * Описание колонок журнала событий исполнения — единственное место, где
 * объявляется, что это за колонка, как она фильтруется и сортируется
 * (#198, ADR-0038; #322).
 *
 * Пока шапка собиралась семью блоками `<th>` руками, колонка называлась
 * сразу в трёх местах — в разметке, в списке полей сортировки и в списке
 * полей фильтра, — и шестая фильтруемая колонка потребовала бы правки всех
 * троих.
 *
 * Таблица целиком клиентская: сервер не знает ни одного её фильтра. Поэтому у
 * каждой фильтруемой колонки проставлен `clientOnly` — иначе объявление
 * выглядело бы как обычная серверная колонка, и добавление серверной выборки
 * молча увезло бы фильтр по «Дате» на сервер под именем колонки.
 *
 * Тип строки и подпись даты живут здесь же: читатель значения колонки
 * (`cellValue`) печатает дату тем же форматом, что и ячейка, иначе список
 * попапера предлагал бы значение, которого в строке нет (#322).
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля фильтра и сортировки журнала: обе связи у колонок совпадают. */
export type EventField = "date" | "type" | "event" | "from" | "to" | "quantity";

/** Строка журнала: собирается из истории статусов и этапов позиции. */
export type ExecutionEventRow = {
  id: string;
  event_at: string | null;
  event_type: "status" | "operation";
  event_type_label: string;
  label: string;
  from_section_name: string;
  to_section_name: string;
  quantity: string;
  details: string;
};

/** Подпись даты события — и в ячейке, и в списке попапера фильтра. */
export function fmtEventAt(value: string | null | undefined): string {
  if (!value) return "—";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export type EventColumn = ColumnSpec<EventField, EventField, ExecutionEventRow> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: `p-0` у колонок с поповером фильтра. */
  headerClassName?: string;
};

/** Поповер фильтра рисует отступы сам, поэтому у колонок с фильтром их нет. */
const filtered = "p-0";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Служебная
 * колонка «Детали» объявлена здесь же, иначе `map` по описанию её потерял бы.
 */
export const eventColumns: EventColumn[] = [
  {
    id: "date",
    label: "Дата",
    filterField: "date",
    sortField: "date",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => fmtEventAt(row.event_at),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "type",
    label: "Тип",
    filterField: "type",
    sortField: "type",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => row.event_type_label,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "event",
    label: "Событие",
    filterField: "event",
    sortField: "event",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => row.label,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "from",
    label: "Откуда",
    filterField: "from",
    sortField: "from",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => row.from_section_name,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "to",
    label: "Куда",
    filterField: "to",
    sortField: "to",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => row.to_section_name,
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "quantity",
    label: "Кол-во",
    filterField: "quantity",
    sortField: "quantity",
    headerClassName: filtered,
    clientOnly: true,
    cellValue: (row) => row.quantity,
    sortValues: (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
  },
  // Служебная колонка: сортировать «Детали» нечем, и в запрос она не уезжает.
  { id: "details", label: "Детали" },
];
