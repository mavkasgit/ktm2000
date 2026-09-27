/**
 * Описание колонок журнала событий исполнения — единственное место, где
 * объявляется, что это за колонка, как она фильтруется и сортируется
 * (#198, ADR-0038).
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
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля фильтра и сортировки журнала: обе связи у колонок совпадают. */
export type EventField = "date" | "type" | "event" | "from" | "to" | "quantity";

export type EventColumn = ColumnSpec<EventField> & {
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
  { id: "date", label: "Дата", filterField: "date", sortField: "date", headerClassName: filtered, clientOnly: true },
  { id: "type", label: "Тип", filterField: "type", sortField: "type", headerClassName: filtered, clientOnly: true },
  { id: "event", label: "Событие", filterField: "event", sortField: "event", headerClassName: filtered, clientOnly: true },
  { id: "from", label: "Откуда", filterField: "from", sortField: "from", headerClassName: filtered, clientOnly: true },
  { id: "to", label: "Куда", filterField: "to", sortField: "to", headerClassName: filtered, clientOnly: true },
  {
    id: "quantity",
    label: "Кол-во",
    filterField: "quantity",
    sortField: "quantity",
    headerClassName: filtered,
    clientOnly: true,
  },
  // Служебная колонка: сортировать «Детали» нечем, и в запрос она не уезжает.
  { id: "details", label: "Детали" },
];
