import { Fragment } from "react";

import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { QuantityRangeCell, TableCornerResetCell, TableCornerResetHeader } from "@/shared/ui";

import {
  ImportRawRows,
  extractPlanImportRawRows,
  type ImportRowExpansion,
} from "@/shared/ui/import-utils";

import { errorLabels as PLAN_IMPORT_ERROR_LABELS, warningLabels } from "@/shared/lib/generated-labels";
export { PLAN_IMPORT_ERROR_LABELS };

/** Подсветка артикула по источнику количества на подвес (after_data.hanger_source): цвет текста + обводка. */
const HANGER_SOURCE_CELL_CLASS: Record<string, string> = {
  missing_product: "text-red-700 border-red-300",
  auto: "text-green-700 border-green-300",
  manual: "text-yellow-700 border-yellow-300",
  none: "text-orange-700 border-orange-300",
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
      const label = labels[code] ?? code;
      const [, ...rest] = String(c).split(":");
      return rest.length > 0 ? `${label}: ${rest.join(":")}` : label;
    })
    .join(", ");
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
          const warnings = translateLabels(row.warnings as string[] | undefined, warningLabels);
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
          const displaySku = String(afterData.source_sku ?? row.source_sku ?? "");
          const hangerTone = displaySku
            ? HANGER_SOURCE_CELL_CLASS[String(afterData.hanger_source ?? "")]
            : undefined;
          const quantity = (afterData.quantity ?? row.quantity ?? "") as string | number;
          const inputQuantity = (afterData.input_quantity ?? null) as string | number | null;
          const originalQuantity = (afterData.original_quantity ?? null) as string | number | null;
          const quantityPerHanger = afterData.quantity_per_hanger as number | null | undefined;

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
                <td className="p-2">
                  {hangerTone ? (
                    <span className={`inline-block rounded border px-1 font-semibold ${hangerTone}`}>{displaySku}</span>
                  ) : (
                    displaySku
                  )}
                </td>
                <td className="p-2">
                  <QuantityRangeCell
                    quantity={quantity}
                    inputQuantity={inputQuantity}
                    originalQuantity={originalQuantity}
                    quantityPerHanger={quantityPerHanger}
                  />
                </td>
                <td className="p-2 max-w-[350px] truncate whitespace-nowrap" title={displayName}>
                  {displayName}
                </td>
                <td className="p-2 text-xs whitespace-nowrap" colSpan={routeColSpan}>
                  {displayRouteName ? (
                    <div className="truncate" title={displayRouteName}>
                      <span className="font-medium">{displayRouteName}</span>
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