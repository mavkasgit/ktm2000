/**
 * Описание колонок исполнения — единственное место, где объявляется, как
 * колонка фильтруется, сортируется и каким именем уезжает в запрос
 * (#197, ADR-0037; #198, ADR-0038).
 *
 * Пока перекодировки жили в `buildExecutionColumnApiParams`, а шапка
 * выбирала между попапером фильтра и текстом тернарником, каждая из десяти
 * колонок называлась дважды: в разметке и в сборке параметров. Имя параметра
 * запроса и правило «это значение серверу не показывать» были написаны руками
 * и разошлись с описанием: колонка «Размер» умела точный фильтр, а её
 * параметр добавлялся отдельным `Object.assign`.
 */

import type { ExecutionSortableField } from "../lib/executionSortMapping";
import { formatDimensionsFilterValue } from "@/shared/api/stock";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { positionStatusLabels, type ExecutionSortField } from "./execution-utils";

export type ExecutionColumnId = ExecutionSortField | "actions";

export interface ExecutionTableColumn extends ColumnSpec<ExecutionSortField, ExecutionSortableField> {
  id: ExecutionColumnId;
  label: string;
  width: string;
  colClassName?: string;
  headerClassName?: string;
  cellClassName?: string;
}

const serviceColClass = "hidden min-[1400px]:table-column";
const serviceCellClass = "hidden min-[1400px]:table-cell";
/**
 * «Не назначен» — это отсутствие маршрута, а не его имя: сервер такого
 * значения не знает, и отправлять его молча значит вернуть пустой список.
 */
const dropUnassigned = (value: string) => (value === "Не назначен" ? undefined : value);

/** У позиции без участка нет названия этапа — вместо него рисуется прочерк. */
const dropDash = (value: string) => (value === "—" ? undefined : value);


export const executionTableColumns: ExecutionTableColumn[] = [
  {
    id: "id",
    label: "ID",
    width: "64px",
    filterField: "id",
    // Поле позиции плана называется в запросе иначе, чем в таблице.
    apiParam: "plan_position_id",
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: `${serviceCellClass} font-mono text-muted-foreground`,
  },
  {
    id: "row",
    label: "№ / План",
    width: "110px",
    filterField: "row",
    sortField: "row",
    apiParam: "source_row_number",
    colClassName: serviceColClass,
    headerClassName: serviceCellClass,
    cellClassName: serviceCellClass,
  },
  {
    id: "sku",
    label: "Артикул",
    width: "minmax(120px, 1fr)",
    filterField: "sku",
    sortField: "sku",
    // `source_sku` — алиас того же фильтра; каноническое имя в API другое.
    apiParam: "product_sku",
    cellClassName: "font-mono",
  },
  {
    id: "qty",
    label: "Кол-во",
    width: "var(--execution-col-qty)",
    filterField: "qty",
    sortField: "qty",
    apiParam: "quantity",
  },
  {
    id: "dimensions",
    label: "Размер",
    width: "110px",
    filterField: "dimensions",
    sortField: "dimensions",
    // «Размер» — выбор габарита из списка, а не поиск подстроки в подписи.
    exactMatch: true,
    valueLabel: formatDimensionsFilterValue,
    colClassName: "hidden min-[600px]:table-column",
    headerClassName: "hidden min-[600px]:table-cell",
    cellClassName: "hidden min-[600px]:table-cell",
  },
  {
    id: "name",
    label: "Наименование",
    width: "auto",
    filterField: "name",
    apiParam: "source_name",
  },
  {
    id: "route",
    label: "Маршрут",
    width: "minmax(160px, 1.2fr)",
    filterField: "route",
    apiParam: "route_name",
    mapValue: dropUnassigned,
    colClassName: "hidden min-[820px]:table-column",
    headerClassName: "hidden min-[820px]:table-cell",
    cellClassName: "hidden min-[820px]:table-cell",
  },
  {
    id: "status",
    label: "Статус",
    width: "var(--execution-col-status)",
    filterField: "status",
    sortField: "status",
    valueLabel: (value: string) => positionStatusLabels[value] ?? value,
  },
  {
    id: "stage",
    label: "Этап",
    width: "var(--execution-col-stage)",
    filterField: "stage",
    sortField: "stage",
    apiParam: "current_stage_section_name",
    mapValue: dropDash,
    colClassName: "hidden min-[700px]:table-column",
    headerClassName: "hidden min-[700px]:table-cell",
    cellClassName: "hidden min-[700px]:table-cell",
  },
  {
    id: "actions",
    label: "Действия",
    width: "var(--execution-col-actions)",
  },
];

export function getExecutionTableColumns() {
  return executionTableColumns;
}
