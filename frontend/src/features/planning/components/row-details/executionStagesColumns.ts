/**
 * Описание колонок маршрутных этапов — единственное место, где объявляется,
 * что это за колонка, как она фильтруется, сортируется, выровнена и что
 * написано на её подсказке (#198, ADR-0038).
 *
 * Пока шапка собиралась одиннадцатью блоками `<th>` руками, ширина, выравнивание
 * и подсказка «Пришло с предыдущего этапа» жили в разметке, а набор фильтруемых
 * колонок — отдельно в хуке. Добавление фильтра к числовой колонке требовало
 * правки и того, и другого.
 *
 * Таблица целиком клиентская: сервер не знает ни одного её фильтра. Поэтому у
 * каждой фильтруемой колонки проставлен `clientOnly` — иначе объявление
 * выглядело бы как обычная серверная колонка, и добавление серверной выборки
 * молча увезло бы фильтр по участку на сервер под именем колонки.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля фильтра и сортировки этапов: обе связи у колонок совпадают. */
export type StageField = "section" | "status";

export type StageColumn = ColumnSpec<StageField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: ширина и выравнивание. */
  headerClassName?: string;
  /** Подсказка на ячейке шапки. */
  title?: string;
};

/** Поповер фильтра рисует отступы сам, поэтому у колонок с фильтром их нет. */
const filtered = "p-0";

/** Числовые колонки выровнены вправо и не переносятся. */
const num = "text-right whitespace-nowrap";

/**
 * Порядок колонок совпадает с порядком в шапке и в теле таблицы. Служебные
 * колонки (номер этапа, количества, процент) объявлены здесь же, иначе
 * `map` по описанию их потерял бы.
 */
export const stageColumns: StageColumn[] = [
  { id: "stage", label: "Этап", headerClassName: "w-14" },
  {
    id: "section",
    label: "Участок",
    filterField: "section",
    sortField: "section",
    headerClassName: `${filtered} min-w-[140px]`,
    clientOnly: true,
  },
  {
    id: "status",
    label: "Статус этапа",
    filterField: "status",
    sortField: "status",
    headerClassName: `${filtered} min-w-[120px]`,
    clientOnly: true,
  },
  { id: "planned", label: "План", headerClassName: num },
  {
    id: "received",
    label: "Получено",
    headerClassName: num,
    title: "Пришло с предыдущего этапа",
  },
  { id: "good", label: "Годные", headerClassName: num, title: "Годные" },
  { id: "reject", label: "Брак", headerClassName: num, title: "Брак" },
  {
    id: "issued",
    label: "Выдано",
    headerClassName: num,
    title: "Выдано на следующий этап",
  },
  { id: "remaining", label: "Остаток", headerClassName: num },
  {
    id: "percent",
    label: "%",
    headerClassName: num,
    title: "Склад: выдано/план, производство: годные/план",
  },
];
