/**
 * Описание колонок маршрутных этапов — единственное место, где объявляется,
 * что это за колонка, как она фильтруется, сортируется, выровнена и что
 * написано на её подсказке (#198, ADR-0038; #322).
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
 *
 * Читатели значения колонок («Участок», «Статус этапа») живут здесь же: и
 * клиентский фильтр, и список попапера берут ту же подпись, что печатает
 * ячейка, — иначе выбор значения не находил бы напечатанную строку (#322).
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import type { ProductionPlanningStage } from "@/shared/api/productionPlans";
import { stageStatusLabels } from "@/shared/lib/generated-labels";

/** Поля фильтра и сортировки этапов: обе связи у колонок совпадают. */
export type StageField = "section" | "status";

/**
 * Строка таблицы этапов: этап и признак «последний в маршруте». Остальные
 * поля строки (текущий этап, тон) нужны только разметке и в значение не входят.
 */
export interface StageTableRow {
  stage: ProductionPlanningStage;
  isFinalStage: boolean;
}

/** Подпись участка этапа — та же, что печатает ячейка. */
export function getStageSectionLabel(stage: ProductionPlanningStage): string {
  return stage.section_name || stage.section_code || "—";
}

/** Подпись статуса этапа — с пометкой у финального этапа. */
export function getStageStatusLabel(stage: ProductionPlanningStage, isFinalStage: boolean): string {
  const base = stageStatusLabels[stage.task_status] || stage.task_status;
  return isFinalStage ? `${base} (финальный этап)` : base;
}

export type StageColumn = ColumnSpec<StageField, StageField, StageTableRow> & {
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
    cellValue: (row) => getStageSectionLabel(row.stage),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
  },
  {
    id: "status",
    label: "Статус этапа",
    filterField: "status",
    sortField: "status",
    headerClassName: `${filtered} min-w-[120px]`,
    clientOnly: true,
    cellValue: (row) => getStageStatusLabel(row.stage, row.isFinalStage),
    sortValues: (a, b) => a.localeCompare(b, "ru"),
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
