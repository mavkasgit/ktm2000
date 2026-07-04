import { Fragment } from "react";

import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { TableCornerResetCell, TableCornerResetHeader } from "@/shared/ui";

import {
  ImportRawRows,
  extractPlanImportRawRows,
  type ImportRowExpansion,
} from "@/shared/ui/import-utils";

export const PLAN_IMPORT_ERROR_LABELS: Record<string, string> = {
  product_not_found: "Изделие не найдено",
  product_inactive: "Изделие неактивно",
  active_techcard_not_found: "Нет активной техкарты",
  active_techcard_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок",
  duplicate_sku_due_date: "Дубликат строки",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает",
  route_missing_required_step: "Отсутствует обязательный этап",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
  quantity_must_be_positive: "Количество должно быть > 0",
};

const warningLabelsRaw: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "не определен",
  row_selection_applied: "Применён фильтр строк",
  row_selection_auto_included: "Автодобавлены парные строки",
  paired_row_auto_included: "Автодобавлена парная строка",
  route_auto_fallback: "Маршрут скорректирован автоматически — проверьте корректность",
  paired_hanger_adjusted: "Округлено для компонента парной техкарты",
  paired_hanger_mismatch: "Разное кол-во на подвес у компонентов парной техкарты",
  hanger_quantity_not_set: "quantity_per_hanger не задан — количество не округлено",
};

function translateLabels(
  codes: string[] | unknown,
  labels: Record<string, string>,
  afterData?: Record<string, unknown>,
): string {
  if (!Array.isArray(codes)) return String(codes ?? "");
  if (codes.length === 0) return "—";
  return codes
    .map((c) => {
      const [code] = String(c).split(":");
      if (code === "duplicate_sku_due_date" && afterData) {
        const duplicateRows = afterData.duplicate_rows as number[] | undefined;
        const duplicateType = String(afterData.duplicate_type ?? "");
        if (duplicateType === "within_import" && Array.isArray(duplicateRows) && duplicateRows.length > 0) {
          const rowsList = duplicateRows.map((n) => `#${n}`).join(", ");
          return `Дубликат строк ${rowsList}`;
        }
        if (duplicateType === "against_existing") {
          const existingRow = afterData.duplicate_existing_row as number | undefined;
          const existingId = afterData.duplicate_existing_id as number | undefined;
          if (existingRow != null) {
            const rowPart = `#${existingRow}`;
            const idPart = existingId != null ? ` / #${existingId}` : "";
            return `Дубликат строки ${rowPart}${idPart} из плана`;
          }
        }
      }
      return labels[code] ?? String(c);
    })
    .join(", ");
}

function formatRouteAssignedAt(value: unknown): string {
  if (!value || typeof value !== "string") return "дата неизвестна";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "дата неизвестна";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function buildRouteMetaLabel(row: Record<string, unknown>): string {
  const routeSource = String(row.route_source ?? "");
  const routeOrigin = String(row.route_origin ?? "");
  const matchQuality = String(row.route_match_quality ?? "");
  const assignedAt = formatRouteAssignedAt(row.route_assigned_at);

  if (routeOrigin === "manual_confirmed" || routeSource === "manual") {
    return `вручную • ${assignedAt}`;
  }
  if (routeOrigin === "auto" || routeSource === "auto") {
    const quality = matchQuality === "exact" ? "полное" : "скорректирован";
    return `автомаппинг (${quality}) • ${assignedAt}`;
  }
  if (routeOrigin === "legacy" || routeSource === "legacy") {
    return `legacy • ${assignedAt}`;
  }
  if (routeSource === "missing") {
    return "не найден";
  }
  return "";
}

export type PlanImportPreviewTableProps = {
  rows: Record<string, unknown>[];
  sortConfig?: { key: string; dir: "asc" | "desc" } | null;
  onSort?: (key: string) => void;
  expansion: ImportRowExpansion;
  hasActiveFilters: boolean;
  onReset: () => void;
};

export function PlanImportPreviewTable({
  rows,
  sortConfig,
  onSort,
  expansion,
  hasActiveFilters,
  onReset,
}: PlanImportPreviewTableProps) {
  const { isRowExpanded, toggleRow } = expansion;

  return (
    <table className="w-full text-xs">
      <thead className="border-b bg-muted/50">
        <tr>
          <th className="text-left p-2 w-10" />
          <th className="text-left p-2 w-20 whitespace-nowrap">ID</th>
          <th
            onClick={() => onSort?.("source_row_number")}
            className="text-left p-2 w-10 cursor-pointer select-none whitespace-nowrap"
          >
            Строка
            {sortConfig?.key === "source_row_number" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("source_sku")}
            className="text-left p-2 w-[100px] cursor-pointer select-none whitespace-nowrap"
          >
            Артикул
            {sortConfig?.key === "source_sku" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("quantity")}
            className="text-left p-2 w-10 cursor-pointer select-none whitespace-nowrap"
          >
            Кол-во
            {sortConfig?.key === "quantity" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("source_name")}
            className="text-left p-2 w-[350px] cursor-pointer select-none whitespace-nowrap"
          >
            Наименование
            {sortConfig?.key === "source_name" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("route_name")}
            className="text-left p-2 w-[280px] cursor-pointer select-none whitespace-nowrap"
          >
            Маршрут
            {sortConfig?.key === "route_name" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("errors")}
            className="text-left p-2 w-[150px] cursor-pointer select-none whitespace-nowrap"
          >
            Ошибки
            {sortConfig?.key === "errors" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <th
            onClick={() => onSort?.("warnings")}
            className="text-left p-2 w-[250px] cursor-pointer select-none whitespace-nowrap"
          >
            Предупр.
            {sortConfig?.key === "warnings" ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
          </th>
          <TableCornerResetHeader
            hasActiveFilters={hasActiveFilters}
            onReset={onReset}
          />
        </tr>
      </thead>
      <tbody>
        {rows.map((row, idx) => {
          const afterData = (row.after_data as Record<string, unknown> | undefined) ?? {};
          const status = String(row.status ?? "");
          const errors = translateLabels(row.errors as string[] | undefined, PLAN_IMPORT_ERROR_LABELS, afterData);
          const warnings = translateLabels(row.warnings as string[] | undefined, warningLabelsRaw);
          const noErrors = errors === "—";
          const noWarnings = warnings === "—";
          const routeColSpan = noErrors && noWarnings ? 3 : noWarnings ? 2 : 1;
          const rowNumbers =
            ((row.payload as Record<string, unknown> | undefined)?.row_numbers as number[] | undefined) ??
            (afterData.source_row_numbers as number[] | undefined);
          const uniqueRowNumbers = Array.isArray(rowNumbers)
            ? Array.from(new Set(rowNumbers.filter((n): n is number => Number.isFinite(n))))
            : [];
          const rowNumDisplay =
            uniqueRowNumbers.length > 1
              ? uniqueRowNumbers.map((n) => `#${n}`).join(", ")
              : `#${row.source_row_number ?? uniqueRowNumbers[0] ?? "—"}`;

          const { segments, hasRawData } = extractPlanImportRawRows(row);
          const routeMeta = buildRouteMetaLabel({ ...(row as Record<string, unknown>), ...afterData });
          const displaySku = String(afterData.source_sku ?? row.source_sku ?? "");
          const rawQty = afterData.quantity ?? row.quantity ?? "";
          const originalQty = afterData.original_quantity;
          const numQty = Number(rawQty);
          const displayQty = Number.isFinite(numQty)
            ? numQty % 1 === 0
              ? String(Math.trunc(numQty))
              : String(numQty)
            : String(rawQty);
          const normalizedOriginal = originalQty
            ? (() => {
                const n = Number(originalQty);
                return Number.isFinite(n)
                  ? n % 1 === 0
                    ? String(Math.trunc(n))
                    : String(n)
                  : String(originalQty);
              })()
            : null;
          const qtyAdjusted = normalizedOriginal && normalizedOriginal !== displayQty;

          const routeSteps = afterData.route_steps as
            | Array<{
                sequence: number;
                section_code: string;
                section_name: string;
                operation_code: string | null;
                operation_name: string;
                is_significant: boolean;
                combined_op_group: string | null;
              }>
            | undefined;

          const hangerCountRaw = afterData.hanger_count as number | null | undefined;
          const hangerCountDisplay =
            hangerCountRaw != null
              ? Number.isInteger(hangerCountRaw)
                ? String(hangerCountRaw)
                : hangerCountRaw.toFixed(1)
              : null;
          const displayName = String(afterData.source_name ?? row.source_name ?? "");
          const displayRouteName = String(afterData.route_name ?? row.route_name ?? "");
          const expectedId = afterData.expected_id as number | undefined;
          const planPosId = row.plan_position_id as number | undefined;
          const duplicateExistingId = afterData.duplicate_existing_id as number | undefined;

          const newId = expectedId ?? "—";
          const idDisplay = planPosId != null ? `#${planPosId}` : `#${newId}`;
          const idDisplayWithDuplicate =
            duplicateExistingId != null ? `${idDisplay} / #${duplicateExistingId}` : idDisplay;
          const isExpanded = isRowExpanded(idx);
          const detailColSpan = 10 - (noErrors ? 1 : 0) - (noWarnings ? 1 : 0);

          return (
            <Fragment key={idx}>
              <tr
                className="border-b cursor-pointer"
                style={{
                  background:
                    status === "invalid" ? "#fef2f2" : status === "warning" ? "#fffbeb" : undefined,
                }}
                onClick={() => hasRawData && toggleRow(idx)}
              >
                <td className="p-2">
                  <ImportRawRows.Chevron
                    expanded={isExpanded}
                    hasContent={hasRawData}
                    className="h-3 w-3 text-muted-foreground"
                  />
                </td>
                <td className="p-2 font-semibold whitespace-nowrap">{idDisplayWithDuplicate}</td>
                <td className="p-2 font-semibold whitespace-nowrap">{rowNumDisplay}</td>
                <td className="p-2">{displaySku}</td>
                <td className="p-2 whitespace-nowrap">
                  {qtyAdjusted ? (
                    <span>
                      <span className="text-muted-foreground">{normalizedOriginal}</span>
                      <span className="mx-1 text-muted-foreground">→</span>
                      <span className="font-medium text-amber-600">
                        {displayQty}
                        {hangerCountDisplay != null ? ` (${hangerCountDisplay}П)` : ""}
                      </span>
                    </span>
                  ) : (
                    <span>
                      {displayQty}
                      {hangerCountDisplay != null ? ` (${hangerCountDisplay}П)` : ""}
                    </span>
                  )}
                </td>
                <td className="p-2 max-w-[350px] truncate whitespace-nowrap" title={displayName}>
                  {displayName}
                </td>
                <td className="p-2 text-xs whitespace-nowrap" colSpan={routeColSpan}>
                  {displayRouteName ? (
                    <div
                      className="truncate"
                      title={`${displayRouteName} ${routeMeta ? `(${routeMeta})` : ""}`}
                    >
                      <span className="font-medium">{displayRouteName}</span>
                      {routeMeta ? <span className="text-muted-foreground ml-1">({routeMeta})</span> : null}
                    </div>
                  ) : routeSteps && routeSteps.length > 0 ? (
                    <RouteStepsDisplay steps={routeSteps} compact size="sm" />
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                {noErrors ? null : <td className="p-2 text-red-600">{errors}</td>}
                {noWarnings ? null : <td className="p-2 text-amber-600">{warnings}</td>}
                <TableCornerResetCell />
              </tr>
              {isExpanded && hasRawData ? (
                <ImportRawRows.Detail
                  colSpan={detailColSpan}
                  segments={segments}
                  displayMode="inline"
                />
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}