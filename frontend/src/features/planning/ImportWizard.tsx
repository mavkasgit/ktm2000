import { useCallback, useEffect, useMemo, useRef, useState, Fragment } from "react"
import { Check, ExternalLink, Upload, ChevronRight, ChevronDown } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { uploadExcel, applyChangeSet, discardImport } from "./api"
import { getExcelSheetNames, previewExcelSheet, type SheetPreviewResponse } from "shared/api/imports"
import { Button, Input, AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel, FiltersPanel, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, type FiltersPanelField } from "shared/ui"
import { buildActiveFilterSummary } from "shared/ui/buildActiveFilterSummary"
import { RouteStepsDisplay } from "shared/ui/RouteStepsDisplay"
import { useQuery } from "@tanstack/react-query"
import { listImportTemplates, type ImportTemplate } from "@/shared/api/importTemplates"
import { getErrorMessage } from "@/shared/api/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "shared/ui"

type SortConfig = { key: string; dir: "asc" | "desc" } | null

const rawHeaders = [
  { key: "source_row_number", label: "Строка" },
  { key: "source_sku", label: "Артикул" },
  { key: "source_name", label: "Наименование" },
  { key: "quantity", label: "Кол-во" },
  { key: "route_name", label: "Маршрут" },
  { key: "status", label: "Статус" },
  { key: "errors", label: "Ошибки" },
  { key: "warnings", label: "Предупр." },
];

const statusLabelsRaw: Record<string, string> = {
  pending: "Ожидает",
  warning: "Предупреждение",
  invalid: "Ошибка",
};

const errorLabelsRaw: Record<string, string> = {
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

function translateLabels(codes: string[] | unknown, labels: Record<string, string>, afterData?: Record<string, unknown>): string {
  if (!Array.isArray(codes)) return String(codes ?? "");
  if (codes.length === 0) return "—";
  return codes.map((c) => {
    // Handle codes with prefix like "paired_row_auto_included:12,13"
    const [code] = String(c).split(":");
    // Special handling for duplicate error - show specific row numbers
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
  }).join(", ");
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

type RawPreviewTableProps = {
  rows: Record<string, unknown>[];
  sortConfig?: { key: string; dir: "asc" | "desc" } | null;
  onSort?: (key: string) => void;
  expanded?: boolean;
};

function RawPreviewTable({ rows, sortConfig, onSort, expanded }: RawPreviewTableProps) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const toggleRow = useCallback((idx: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }, []);

  return (
    <table className="w-full text-xs">
      <thead className="border-b bg-muted/50">
        <tr>
          <th className="text-left p-2 w-10"></th>
          <th className="text-left p-2 w-20 whitespace-nowrap">Id</th>
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
        </tr>
      </thead>
      <tbody>
        {rows.map((row, idx) => {
          const afterData = (row.after_data as Record<string, unknown> | undefined) ?? {};
          const status = String(row.status ?? "");
          const errors = translateLabels(row.errors as string[] | undefined, errorLabelsRaw, afterData);
          const warnings = translateLabels(row.warnings as string[] | undefined, warningLabelsRaw);
          const noErrors = errors === "—";
          const noWarnings = warnings === "—";
          const routeColSpan = noErrors && noWarnings ? 3 : noWarnings ? 2 : 1;
          const rowNumbers = ((row.payload as any)?.row_numbers as number[] | undefined) ?? (afterData.source_row_numbers as number[] | undefined);
          const uniqueRowNumbers = Array.isArray(rowNumbers)
            ? Array.from(new Set(rowNumbers.filter((n): n is number => Number.isFinite(n))))
            : [];
          const rowNumDisplay = uniqueRowNumbers.length > 1
            ? uniqueRowNumbers.map((n) => `#${n}`).join(", ")
            : `#${row.source_row_number ?? uniqueRowNumbers[0] ?? "—"}`;
          const rawRow = (row.payload as any)?.raw_excel_row as Record<string, string> | undefined;
          const rawColumns = (row.payload as any)?.raw_columns as Record<string, string> | undefined;
          const rawColumnsByRow = (row.payload as any)?.raw_columns_by_row as Record<string, Record<string, string>> | undefined;

          // Build raw rows preferring raw_columns (header order) over raw_excel_row (column_map order)
          const buildRawRowsFromColumns = (
            columnsByRow: Record<string, Record<string, string>> | undefined,
            singleColumns: Record<string, string> | undefined,
            singleRawRow: Record<string, string> | undefined,
            fallbackRowNum: string,
          ): { rowNumber: string; data: Record<string, string> }[] => {
            if (columnsByRow && Object.keys(columnsByRow).length > 0) {
              return Object.entries(columnsByRow)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([num, data]) => ({ rowNumber: num, data }));
            }
            if (singleColumns && Object.keys(singleColumns).length > 0) {
              return [{ rowNumber: fallbackRowNum, data: singleColumns }];
            }
            if (singleRawRow) {
              return [{ rowNumber: fallbackRowNum, data: singleRawRow }];
            }
            return [];
          };

          const allRawRows = buildRawRowsFromColumns(
            rawColumnsByRow, rawColumns, rawRow, String(row.source_row_number ?? ""),
          );

          // Also check after_data.source_payload for server-side items
          const sourcePayload = (afterData.source_payload as Record<string, unknown> | undefined) ?? {};
          const serverRawColumns = sourcePayload.raw_columns as Record<string, string> | undefined;
          const serverRawColumnsByRow = sourcePayload.raw_columns_by_row as Record<string, Record<string, string>> | undefined;
          const serverRawRow = sourcePayload.raw_excel_row as Record<string, string> | undefined;
          const serverRawRows = buildRawRowsFromColumns(
            serverRawColumnsByRow as any, serverRawColumns, serverRawRow as any,
            String((sourcePayload.row_numbers as number[] | undefined)?.[0] ?? row.source_row_number ?? ""),
          );

          // For against_existing duplicates, get the existing DB row raw data
          // Reorder duplicate columns to match the Excel row column order for easy comparison
          const duplicateType = String(afterData.duplicate_type ?? "");
          const dupExistingPayload = (afterData.duplicate_existing_payload as Record<string, unknown> | undefined) ?? {};
          const dupExistingRawColumns = dupExistingPayload.raw_columns as Record<string, string> | undefined;
          const dupExistingRawColumnsByRow = dupExistingPayload.raw_columns_by_row as Record<string, Record<string, string>> | undefined;
          const dupExistingRawRow = dupExistingPayload.raw_excel_row as Record<string, string> | undefined;
          const dupExistingRawRowsUnordered = buildRawRowsFromColumns(
            dupExistingRawColumnsByRow as any, dupExistingRawColumns, dupExistingRawRow as any,
            String((dupExistingPayload.row_numbers as number[] | undefined)?.[0] ?? afterData.duplicate_existing_row ?? ""),
          );

          const effectiveRawRows = allRawRows.length > 0 ? allRawRows : serverRawRows;
          const hasRawData = effectiveRawRows.length > 0 || dupExistingRawRowsUnordered.length > 0;

          // Reorder duplicate columns to match first available Excel row column order
          const refColumnOrder = effectiveRawRows.length > 0
            ? Object.keys(effectiveRawRows[0].data)
            : (serverRawRows.length > 0 ? Object.keys(serverRawRows[0].data) : []);
          const reorderColumns = (data: Record<string, string>, order: string[]): Record<string, string> => {
            if (order.length === 0) return data;
            const result: Record<string, string> = {};
            for (const key of order) {
              if (key in data) result[key] = data[key];
            }
            for (const key of Object.keys(data)) {
              if (!(key in result)) result[key] = data[key];
            }
            return result;
          };
          const dupExistingRawRows = dupExistingRawRowsUnordered.map(r => ({
            ...r,
            data: reorderColumns(r.data, refColumnOrder),
            isDuplicate: true,
          }));
          const routeMeta = buildRouteMetaLabel({ ...(row as Record<string, unknown>), ...afterData });
          const displaySku = String(afterData.source_sku ?? row.source_sku ?? "");
          const rawQty = afterData.quantity ?? row.quantity ?? "";
          const originalQty = afterData.original_quantity;
          const numQty = Number(rawQty);
          // Normalize: remove .0 for whole numbers
          const displayQty = Number.isFinite(numQty) ? (numQty % 1 === 0 ? String(Math.trunc(numQty)) : String(numQty)) : String(rawQty);
          const normalizedOriginal = originalQty ? (() => {
            const n = Number(originalQty);
            return Number.isFinite(n) ? (n % 1 === 0 ? String(Math.trunc(n)) : String(n)) : String(originalQty);
          })() : null;
          const qtyAdjusted = normalizedOriginal && normalizedOriginal !== displayQty;

          // Get route steps from after_data
          const routeSteps = afterData.route_steps as Array<{
            sequence: number
            section_code: string
            section_name: string
            operation_code: string | null
            operation_name: string
            is_significant: boolean
            combined_op_group: string | null
          }> | undefined;

          // Get hanger count from after_data (backend calculates it)
          const hangerCountRaw = afterData.hanger_count as number | null | undefined;
          const hangerCountDisplay = hangerCountRaw != null
            ? (Number.isInteger(hangerCountRaw) ? String(hangerCountRaw) : hangerCountRaw.toFixed(1))
            : null;
          const displayName = String(afterData.source_name ?? row.source_name ?? "");
          const displayRouteName = String(afterData.route_name ?? row.route_name ?? "");
          const expectedId = afterData.expected_id as number | undefined;
          const planPosId = row.plan_position_id as number | undefined;
          const duplicateExistingId = afterData.duplicate_existing_id as number | undefined;

          // ID display: expected_id for new, existing_id for duplicates
          const newId = expectedId ?? "—";
          const idDisplay = planPosId != null ? `#${planPosId}` : `#${newId}`;
          const idDisplayWithDuplicate = duplicateExistingId != null
            ? `${idDisplay} / #${duplicateExistingId}`
            : idDisplay;
          const isExpanded = expanded || expandedRows.has(idx);
          return (
            <Fragment key={idx}>
            <tr
              className="border-b cursor-pointer"
              style={{
                background: status === "invalid" ? "#fef2f2" : status === "warning" ? "#fffbeb" : undefined,
              }}
              onClick={() => hasRawData && toggleRow(idx)}
            >
              <td className="p-2">
                {isExpanded && hasRawData ? (
                  <ChevronDown className="h-3 w-3 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-3 w-3 text-muted-foreground" />
                )}
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
                      {displayQty}{hangerCountDisplay != null ? ` (${hangerCountDisplay}П)` : ''}
                    </span>
                  </span>
                ) : (
                  <span>
                    {displayQty}{hangerCountDisplay != null ? ` (${hangerCountDisplay}П)` : ''}
                  </span>
                )}
              </td>
              <td className="p-2 max-w-[350px] truncate whitespace-nowrap" title={displayName}>{displayName}</td>
              <td className="p-2 text-xs whitespace-nowrap" colSpan={routeColSpan}>
                {displayRouteName ? (
                  <div className="truncate" title={`${displayRouteName} ${routeMeta ? `(${routeMeta})` : ''}`}>
                    <span className="font-medium">
                      {displayRouteName}
                    </span>
                    {routeMeta && (
                      <span className="text-muted-foreground ml-1">
                        ({routeMeta})
                      </span>
                    )}
                  </div>
                ) : routeSteps && routeSteps.length > 0 ? (
                  <div className="truncate whitespace-nowrap">
                    <RouteStepsDisplay steps={routeSteps} compact />
                  </div>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              {noErrors ? null : <td className="p-2 text-red-600">{errors}</td>}
              {noWarnings ? null : <td className="p-2 text-amber-600">{warnings}</td>}
            </tr>
            {isExpanded && (effectiveRawRows.length > 0 || dupExistingRawRows.length > 0) && (
              <>
                {effectiveRawRows.length > 0 && (
                  <>
                    {effectiveRawRows.map((r, rowIdx) => {
                      return (
                      <tr key={`raw-${rowIdx}`} className="border-b bg-muted/30">
                        <td colSpan={9 - (noErrors ? 1 : 0) - (noWarnings ? 1 : 0)} className="p-2 pl-6 text-[11px] leading-relaxed font-mono">
                          <div className="flex items-start gap-2">
                            <span className="font-bold text-muted-foreground shrink-0">
                              {planPosId != null ? `(#${planPosId}) ` : ""}
                              {duplicateExistingId != null ? `(#${duplicateExistingId}) ` : ""}
                              #{r.rowNumber}:
                            </span>
                            <span>{Object.values(r.data).filter(Boolean).join(" | ")}</span>
                          </div>
                        </td>
                      </tr>
                      );
                    })}
                  </>
                )}
                {dupExistingRawRows.length > 0 && (
                  <>
                    {dupExistingRawRows.map((r, rowIdx) => {
                      const dupId = afterData.duplicate_existing_id as number | undefined;
                      return (
                      <tr key={`dup-${rowIdx}`} className="border-b bg-red-50/50">
                        <td colSpan={9 - (noErrors ? 1 : 0) - (noWarnings ? 1 : 0)} className="p-2 pl-6 text-[11px] leading-relaxed font-mono">
                          <div className="flex items-start gap-2">
                            <span className="font-bold text-red-600 shrink-0">
                              {dupId ? `(#${dupId}) ` : ""}#{r.rowNumber} (дубликат):
                            </span>
                            <span>{Object.values(r.data).filter(Boolean).join(" | ")}</span>
                          </div>
                        </td>
                      </tr>
                      );
                    })}
                  </>
                )}
              </>
            )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

type SheetPreviewCache = Record<string, SheetPreviewResponse>

function buildPreviewCacheKey(sheetIdx: number, templateId: number | null, rowSelection: string, normalizeHanger: boolean): string {
  const selection = rowSelection.trim();
  const templatePart = templateId == null ? "none" : String(templateId);
  return `${sheetIdx}:${templatePart}:${selection}:${normalizeHanger ? "h" : "n"}`;
}

export function ImportWizard(props: {
  open: boolean
  onClose: () => void
  onSuccess: (planId: string, changeSetId: string) => void
  productionPlanId?: number
  templateId?: number
}) {
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload")
  const [file, setFile] = useState<File | null>(null)
  const [sheets, setSheets] = useState<string[]>([])
  const [selectedSheet, setSelectedSheet] = useState(0)
  const [sheetPreviews, setSheetPreviews] = useState<SheetPreviewCache>({})
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({})
  const [sortConfig, setSortConfig] = useState<SortConfig>(null)
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid" | "warning">("all")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [planMonth, setPlanMonth] = useState("")
  const [planVersion, setPlanVersion] = useState("")
  const [rowSelection, setRowSelection] = useState("")
  const [pendingChangeSet, setPendingChangeSet] = useState<{ planId: string; changeSetId: string } | null>(null)
  const [showApplyConfirm, setShowApplyConfirm] = useState(false)
  const [showCloseConfirm, setShowCloseConfirm] = useState(false)
  const [showRawRows, setShowRawRows] = useState(false)
  const [activeTemplateId, setActiveTemplateId] = useState<number | null>(props.templateId ?? null)
  const [normalizeHangerQuantity, setNormalizeHangerQuantity] = useState(true)
  const [loadingStartTime, setLoadingStartTime] = useState<number | null>(null)
  const [loadingElapsed, setLoadingElapsed] = useState(0)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { data: templates } = useQuery<ImportTemplate[]>({
    queryKey: ["import-templates", "import-modal"],
    queryFn: listImportTemplates,
    enabled: props.open,
  })

  useEffect(() => {
    if (!props.open) return
    setActiveTemplateId(props.templateId ?? null)
  }, [props.open, props.templateId])

  const activeTemplates = useMemo(
    () => (templates ?? []).filter((template) => template.is_active).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
    [templates],
  )
  const selectedTemplate = useMemo(
    () => activeTemplates.find((template) => template.id === activeTemplateId) ?? null,
    [activeTemplates, activeTemplateId],
  )

  useEffect(() => {
    if (step !== "preview" || !file) return
    setSheetPreviews({})
    setPreviewLoading({})
    setPendingChangeSet(null)
    loadSheetPreview(file, selectedSheet, rowSelection)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTemplateId, rowSelection])

  // Preview for the currently selected sheet
  const currentPreviewKey = useMemo(
    () => buildPreviewCacheKey(selectedSheet, activeTemplateId, rowSelection, normalizeHangerQuantity),
    [selectedSheet, activeTemplateId, rowSelection, normalizeHangerQuantity],
  )
  const currentPreview = sheetPreviews[currentPreviewKey] ?? null

  // Timer for loading progress
  useEffect(() => {
    if (previewLoading[currentPreviewKey] && !loadingStartTime) {
      setLoadingStartTime(Date.now())
    } else if (!previewLoading[currentPreviewKey] && loadingStartTime) {
      setLoadingStartTime(null)
      setLoadingElapsed(0)
    }
  }, [previewLoading, currentPreviewKey, loadingStartTime])

  useEffect(() => {
    if (!loadingStartTime) return
    const interval = setInterval(() => {
      setLoadingElapsed(Math.floor((Date.now() - loadingStartTime) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [loadingStartTime])

  const allRows = useMemo(() => {
    const base = (currentPreview?.items as Record<string, unknown>[]) ?? []
    // Compute predicted DB IDs: for rows without persisted plan_position_id,
    // assign sequential IDs starting from max visible DB id.
    let maxId = 0
    for (const r of base) {
      const pid = r.plan_position_id as number | undefined
      if (pid != null && pid > maxId) maxId = pid
      const dupId = (r.after_data as Record<string, unknown> | undefined)?.duplicate_existing_id
      if (typeof dupId === "number" && dupId > maxId) maxId = dupId
    }
    let nextId = maxId + 1
    return base.map((r) => {
      const pid = r.plan_position_id as number | undefined
      if (pid == null) {
        return { ...r, _predicted_id: nextId++ }
      }
      return r
    })
  }, [currentPreview])

  const filteredRows = useMemo(() => {
    let rows = allRows
    // Client-side row number filter
    if (rowSelection.trim() && rows.length > 0) {
      try {
        const allowed = new Set<number>()
        for (const token of rowSelection.split(",")) {
          const part = token.trim()
          if (!part) continue
          if (part.includes("-")) {
            const bounds = part.split("-").map((s) => s.trim())
            const s = Number(bounds[0])
            const e = Number(bounds[1])
            if (Number.isFinite(s) && Number.isFinite(e) && s > 0 && e > 0) {
              for (let i = Math.min(s, e); i <= Math.max(s, e); i++) allowed.add(i)
            }
          } else if (/^\d+$/.test(part)) {
            const n = Number(part)
            if (Number.isFinite(n) && n > 0) allowed.add(n)
          }
        }
        if (allowed.size > 0) {
          rows = rows.filter((r) => {
            const rowNum = r.source_row_number ?? (r.after_data as any)?.source_row_numbers?.[0]
            return rowNum != null && allowed.has(Number(rowNum))
          })
        }
      } catch {
        // ignore invalid rowSelection
      }
    }
    if (filterStatus !== "all") {
      rows = rows.filter((r) => r.status === filterStatus)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      rows = rows.filter((r) => {
        const rowNum = String(r.source_row_number ?? (r.after_data as any)?.source_row_numbers?.[0] ?? "")
        const planPosId = String(r.plan_position_id ?? "")
        const after = (r.after_data as Record<string, unknown>) || {}
        const sku = String(after.source_sku ?? r.source_sku ?? "")
        const name = String(after.source_name ?? r.source_name ?? "")
        return rowNum.includes(q) || planPosId.includes(q) || sku.toLowerCase().includes(q) || name.toLowerCase().includes(q)
      })
    }
    if (!sortConfig) return rows
    return [...rows].sort((a, b) => {
      let aVal: string
      let bVal: string
      if (sortConfig.key === "change_action" || sortConfig.key === "status") {
        aVal = String(a[sortConfig.key] ?? "")
        bVal = String(b[sortConfig.key] ?? "")
      } else {
        const aAfter = (a.after_data as Record<string, unknown>) || {}
        const bAfter = (b.after_data as Record<string, unknown>) || {}
        aVal = String(aAfter[sortConfig.key] ?? a[sortConfig.key] ?? "")
        bVal = String(bAfter[sortConfig.key] ?? b[sortConfig.key] ?? "")
      }
      if (aVal < bVal) return sortConfig.dir === "asc" ? -1 : 1
      if (aVal > bVal) return sortConfig.dir === "asc" ? 1 : -1
      return 0
    })
  }, [allRows, filterStatus, sortConfig, rowSelection, searchQuery])

  const summary = useMemo(() => {
    const total = allRows.length
    const invalid = allRows.filter((r) => r.status === "invalid").length
    const warning = allRows.filter((r) => r.status === "warning").length
    return { total, invalid, warning }
  }, [allRows])
  const previewActiveFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary(
        { status: filterStatus },
        searchQuery,
        sortConfig ? 1 : 0,
      ),
    [filterStatus, searchQuery, sortConfig],
  )
  const resetPreviewFilters = useCallback(() => {
    setSearchQuery("")
    setFilterStatus("all")
    setSortConfig(null)
  }, [])
  const previewFilterFields = useMemo<FiltersPanelField[]>(
    () => [
      {
        kind: "search" as const,
        key: "search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Поиск: строка, ID, артикул...",
      },
      {
        kind: "select" as const,
        key: "status",
        value: filterStatus,
        onChange: (value: string) => setFilterStatus(value as "all" | "invalid" | "warning"),
        placeholder: "Статус строк",
        options: [
          { value: "all", label: "Все" },
          { value: "invalid", label: "Ошибки" },
          { value: "warning", label: "Предупр." },
        ],
      },
    ],
    [filterStatus, searchQuery],
  )

  const applyStats = useMemo(() => {
    const total = summary.total
    const invalid = summary.invalid
    const warning = summary.warning
    return {
      total,
      invalid,
      warning,
      normal: Math.max(total - invalid - warning, 0),
      uploadAll: total,
      uploadSkipInvalid: Math.max(total - invalid, 0),
    }
  }, [summary])

  const errorBreakdown = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const row of allRows) {
      const errs = row.errors as string[] | undefined
      if (Array.isArray(errs)) {
        for (const e of errs) {
          counts[e] = (counts[e] || 0) + 1
        }
      }
    }
    return counts
  }, [allRows])

  const errorBreakdownEntries = useMemo(() => {
    return Object.entries(errorBreakdown).sort((a, b) => b[1] - a[1])
  }, [errorBreakdown])

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const sheetNames = await getExcelSheetNames(f)
      setSheets(sheetNames)
      setSelectedSheet(0)
      setSheetPreviews({})
      setPreviewLoading({})
      setPendingChangeSet(null)
      setStep("preview")
      // Auto-load preview for first sheet
      loadSheetPreview(f, 0, rowSelection)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  // Refetch preview when hanger quantity toggle changes
  useEffect(() => {
    if (!file) return
    // Invalidate old cache entries that had different normalizeHangerQuantity value
    setSheetPreviews((prev) => {
      const next: Record<string, SheetPreviewResponse> = {}
      for (const [key, value] of Object.entries(prev)) {
        // Keep entries that match current normalizeHangerQuantity
        if (key.endsWith(normalizeHangerQuantity ? ":h" : ":n")) {
          next[key] = value
        }
      }
      return next
    })
    loadSheetPreview(file, selectedSheet)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizeHangerQuantity])

  async function loadSheetPreview(f: File, sheetIdx: number, selection: string = rowSelection) {
    const cacheKey = buildPreviewCacheKey(sheetIdx, activeTemplateId, selection, normalizeHangerQuantity)
    if (previewLoading[cacheKey] || sheetPreviews[cacheKey]) return
    setPreviewLoading((prev) => ({ ...prev, [cacheKey]: true }))
    try {
      const data = await previewExcelSheet(f, {
        sheet_index: sheetIdx,
        row_selection: selection.trim() || undefined,
        template_id: activeTemplateId ?? undefined,
        mode: props.productionPlanId ? "append_to_plan" : "create_plan",
        production_plan_id: props.productionPlanId,
        normalize_hanger_quantity: normalizeHangerQuantity,
      })
      setSheetPreviews((prev) => ({ ...prev, [cacheKey]: data }))
    } catch {
      // ignore — user will see empty table
    } finally {
      setPreviewLoading((prev) => ({ ...prev, [cacheKey]: false }))
    }
  }

  async function handleApplyConfirmed(skipInvalid: boolean) {
    if (!file) return
    if (!activeTemplateId) {
      setError("Выберите шаблон импорта перед применением")
      return
    }

    setShowApplyConfirm(false)
    setLoading(true)
    setError(null)
    let changeSet = pendingChangeSet
    let createdNow = false
    try {
      if (!changeSet) {
        const uploaded = await uploadExcel(file, {
          templateId: activeTemplateId,
          productionPlanId: props.productionPlanId,
          planMonth: planMonth || undefined,
          planVersion: planVersion || undefined,
          rowSelection: rowSelection || undefined,
          sheetIndex: selectedSheet,
          normalizeHangerQuantity: normalizeHangerQuantity,
        })
        const planId = String(uploaded.planId ?? uploaded.production_plan_id ?? "")
        const changeSetId = String(uploaded.changeSetId ?? uploaded.change_set_id ?? "")
        if (!planId || !changeSetId) {
          throw new Error("Не найден planId или changeSetId")
        }
        changeSet = { planId, changeSetId }
        createdNow = true
        setPendingChangeSet(changeSet)
      }

      const data = await applyChangeSet(changeSet.planId, changeSet.changeSetId, { skipInvalid })
      setResult(data)
      setPendingChangeSet(null)
      setStep("result")
      props.onSuccess(changeSet.planId, changeSet.changeSetId)
    } catch (e) {
      // If apply failed right after creating a change set, cleanup immediately.
      if (createdNow && changeSet) {
        discardImport(changeSet.planId, changeSet.changeSetId).catch(() => {})
        setPendingChangeSet(null)
      }
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function handleApply() {
    if (!file) return
    if (!activeTemplateId) {
      setError("Выберите шаблон импорта перед применением")
      return
    }
    setShowApplyConfirm(true)
  }

  function toggleSort(key: string) {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" }
      if (prev.dir === "asc") return { key, dir: "desc" }
      return null
    })
  }

  function reset() {
    // Discard any pending change set on reset
    if (pendingChangeSet) {
      discardImport(pendingChangeSet.planId, pendingChangeSet.changeSetId).catch(() => {})
    }
    setStep("upload")
    setFile(null)
    setSheets([])
    setSelectedSheet(0)
    setSheetPreviews({})
    setPreviewLoading({})
    setResult(null)
    setError(null)
    setSortConfig(null)
    setFilterStatus("all")
    setSearchQuery("")
    setPlanMonth("")
    setPlanVersion("")
    setRowSelection("")
    setPendingChangeSet(null)
    setShowRawRows(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  function handleClose() {
    if (pendingChangeSet && step !== "result") {
      setShowCloseConfirm(true)
      return
    }
    reset()
    props.onClose()
  }

  function handleForceClose() {
    setShowCloseConfirm(false)
    reset()
    props.onClose()
  }

  return (
    <>
      <Dialog open={props.open} onOpenChange={(open) => { if (!open) handleClose() }}>
      <DialogContent className={`w-full max-h-[95vh] overflow-hidden flex flex-col ${step === "preview" ? "max-w-[95vw]" : "max-w-2xl"}`}>
        <DialogHeader>
          <DialogTitle>Импорт производственного плана</DialogTitle>
          <DialogDescription>
            Загрузите файл Excel, выберите лист и строки, затем примените
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {step === "upload" && (
          <div className="space-y-4">
              {activeTemplates.length > 0 && (
                <div className="grid grid-cols-1 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground">Шаблон импорта</label>
                    <div className="w-[300px]">
                      <Select value={activeTemplateId != null ? String(activeTemplateId) : "none"} onValueChange={(v) => setActiveTemplateId(v === "none" ? null : Number(v))}>
                        <SelectTrigger className="h-10">
                          <SelectValue placeholder="Без шаблона (только глобальные правила)" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">Без шаблона (только глобальные правила)</SelectItem>
                          {activeTemplates.map((template) => (
                            <SelectItem key={template.id} value={String(template.id)}>
                              {template.button_label || template.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              )}
              {!props.productionPlanId && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground">Месяц плана</label>
                    <Input
                      value={planMonth}
                      onChange={(e) => setPlanMonth(e.target.value)}
                      placeholder="Месяц"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Версия плана</label>
                    <Input
                      value={planVersion}
                      onChange={(e) => setPlanVersion(e.target.value)}
                      placeholder="Версия"
                    />
                  </div>
                </div>
              )}
              <div
                className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:bg-accent/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-sm text-muted-foreground">
                  {loading ? "Загрузка…" : "Нажмите или перетащите заполненный файл Excel"}
                </p>
                <p className="text-xs text-muted-foreground mt-2">
                  Поддерживаются .xlsx, .xls, .xlsm, .xlsb, .ods
                </p>
                {file && !loading && (
                  <p className="text-xs text-blue-600 mt-2 font-medium">{file.name}</p>
                )}
              </div>
          </div>
        )}

        {step === "preview" && file && sheets.length > 0 && (
          <div className="flex-1 overflow-hidden flex flex-col space-y-3">
            {/* Loading state: spinner + progress bar */}
            {previewLoading[currentPreviewKey] && (
              <div className="flex-1 flex flex-col items-center justify-center p-8">
                <div className="w-full max-w-md space-y-6">
                  {/* Spinner */}
                  <div className="flex justify-center">
                    <div className="relative">
                      <div className="w-12 h-12 border-4 border-muted rounded-full" />
                      <div className="absolute inset-0 w-12 h-12 border-4 border-primary rounded-full border-t-transparent animate-spin" />
                    </div>
                  </div>

                  {/* Progress bar with time */}
                  <div className="space-y-2">
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all duration-1000 ease-linear"
                        style={{ width: `${Math.min(95, 10 + (loadingElapsed / 6) * 85)}%` }}
                      />
                    </div>
                    <div className="text-center text-xs text-muted-foreground">
                      Загружено {loadingElapsed}с...
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Compact horizontal controls */}
            {currentPreview && (
              <>
                {/* Row 1: Sheet tabs / File / Rows / Template / References */}
                <div className="flex flex-wrap items-center gap-3 shrink-0">
                  {/* Sheet tabs as buttons */}
                  <div className="flex gap-1 flex-wrap shrink-0">
                    {sheets.map((name, idx) => (
                      <button
                        key={idx}
                        onClick={() => {
                          setSelectedSheet(idx)
                          loadSheetPreview(file, idx, rowSelection)
                        }}
                        className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                          selectedSheet === idx
                            ? "bg-primary text-primary-foreground border-primary"
                            : "bg-background hover:bg-accent border-input"
                        }`}
                      >
                        {name}
                      </button>
                    ))}
                  </div>

                  <span className="text-xs text-muted-foreground">
                    {currentPreview.total_rows} строк
                  </span>

                  <span className="text-xs text-muted-foreground font-medium">Строки:</span>
                  <Input
                    value={rowSelection}
                    onChange={(e) => setRowSelection(e.target.value)}
                    placeholder="5,7,12-15"
                    className="h-7 w-32 text-xs"
                  />

                  <label className="flex items-center gap-1.5 text-xs cursor-pointer shrink-0">
                    <input
                      type="checkbox"
                      checked={normalizeHangerQuantity}
                      onChange={(e) => setNormalizeHangerQuantity(e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-muted-foreground font-medium">Округлять до кратности подвеса</span>
                  </label>

                  {activeTemplates.length > 0 && (
                    <>
                      <span className="text-xs text-muted-foreground font-medium">Шаблон:</span>
                      <div className="w-[300px] flex-shrink-0">
                        <Select value={activeTemplateId != null ? String(activeTemplateId) : "none"} onValueChange={(v) => setActiveTemplateId(v === "none" ? null : Number(v))}>
                          <SelectTrigger className="h-7 text-xs">
                            <SelectValue placeholder="Без шаблона" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">Без шаблона</SelectItem>
                            {activeTemplates.map((template) => (
                              <SelectItem key={template.id} value={String(template.id)}>
                                {template.button_label || template.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                </div>

                {/* Row 2: Summary + Error chips */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm shrink-0">
                  <span><strong>Всего:</strong> {summary.total}</span>
                  {(() => {
                    const qtyTotalRaw = (currentPreview.summary as Record<string, unknown>)?.quantity_total as string | undefined;
                    const qtyAdjustedTotalRaw = (currentPreview.summary as Record<string, unknown>)?.quantity_adjusted_total as string | undefined;
                    const normalizeQty = (qty: string) => {
                      const n = Number(qty);
                      return Number.isFinite(n) ? (n % 1 === 0 ? String(Math.trunc(n)) : String(n)) : qty;
                    };
                    const qtyTotal = qtyTotalRaw ? normalizeQty(qtyTotalRaw) : undefined;
                    const qtyAdjustedTotal = qtyAdjustedTotalRaw ? normalizeQty(qtyAdjustedTotalRaw) : undefined;
                    if (qtyTotal && qtyAdjustedTotal && qtyTotal !== qtyAdjustedTotal) {
                      return (
                        <span>
                          <strong>Кол-во:</strong>{" "}
                          <span className="text-muted-foreground">{qtyTotal}</span>
                          <span className="mx-1 text-muted-foreground">→</span>
                          <span className="font-medium text-amber-600">{qtyAdjustedTotal}</span>
                        </span>
                      );
                    }
                    if (qtyTotal) {
                      return <span><strong>Кол-во:</strong> {qtyTotal}</span>;
                    }
                    return null;
                  })()}
                  <span>
                    <strong>Период:</strong>{" "}
                    {String(((currentPreview.summary as Record<string, unknown>)?.period_label ?? "не определен"))}
                  </span>
                  {summary.invalid > 0 && <span className="text-red-600"><strong>Ошибок:</strong> {summary.invalid}</span>}
                  {summary.warning > 0 && <span className="text-amber-600"><strong>Предупр.:</strong> {summary.warning}</span>}
                  {summary.invalid === 0 && summary.warning === 0 && <span className="text-green-600 text-xs">Без ошибок</span>}
                  {errorBreakdown["product_not_found"] > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs gap-1 shrink-0"
                      onClick={() => window.open("/references/raw-materials", "_blank")}
                    >
                      <ExternalLink className="h-3 w-3" />
                      Открыть справочники
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1 shrink-0"
                    onClick={() => window.open("/planning", "_blank")}
                  >
                    <ExternalLink className="h-3 w-3" />
                    Открыть план
                  </Button>
                </div>

                {Object.keys(errorBreakdown).length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-xs shrink-0">
                    {Object.entries(errorBreakdown).map(([code, count]) => (
                      <span key={code} className="bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100">
                        {errorLabelsRaw[code] ?? code}: {count}
                      </span>
                    ))}
                  </div>
                )}

                {/* Row 3: Filters */}
                <FiltersPanel
                  compact
                  fields={previewFilterFields}
                  onReset={resetPreviewFilters}
                  hasActiveFilters={previewActiveFilterSummary.count > 0}
                  activeSummary={previewActiveFilterSummary}
                  className="p-3"
                  actions={(
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant={showRawRows ? "default" : "outline"}
                        className="h-8 text-sm"
                        onClick={() => setShowRawRows(!showRawRows)}
                      >
                        {showRawRows ? <ChevronDown className="h-3.5 w-3.5 mr-1" /> : <ChevronRight className="h-3.5 w-3.5 mr-1" />}
                        Сырые строки
                      </Button>
                    </div>
                  )}
                />

                <div className="flex-1 overflow-auto border rounded-lg">
                  {previewLoading[currentPreviewKey] ? (
                    <div className="p-4 space-y-3">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="flex items-center gap-3 animate-pulse">
                          <div className="w-6 h-4 bg-muted rounded" />
                          <div className="w-12 h-4 bg-muted rounded" />
                          <div className="w-8 h-4 bg-muted rounded" />
                          <div className="w-20 h-4 bg-muted rounded" />
                          <div className="w-10 h-4 bg-muted rounded" />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "300px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "250px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "120px" }} />
                          <div className="flex-1 h-4 bg-muted rounded" style={{ maxWidth: "180px" }} />
                        </div>
                      ))}
                    </div>
                  ) : allRows.length === 0 ? (
                    <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">Нет данных для отображения</div>
                  ) : (
                    <RawPreviewTable rows={filteredRows} sortConfig={sortConfig} onSort={toggleSort} expanded={showRawRows} />
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {step === "result" && result && (
          <div className="text-center py-6">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-4">
                  <Check className="h-8 w-8 text-green-600" />
                </div>
                <h3 className="text-lg font-medium mb-4">Изменения применены</h3>
                <div className="flex justify-center gap-6 text-sm">
                  <div>
                    <div className="font-semibold">{(result as any).created_positions ?? 0}</div>
                    <div className="text-muted-foreground">Создано</div>
                  </div>
                  <div>
                    <div className="font-semibold">{(result as any).updated_positions ?? 0}</div>
                    <div className="text-muted-foreground">Обновлено</div>
                  </div>
                </div>
          </div>
        )}

        <DialogFooter className="shrink-0">
          {step === "preview" && (
            <>
              <Button variant="outline" onClick={reset} disabled={loading}>
                Назад
              </Button>
              <Button onClick={handleApply} disabled={loading || !currentPreview}>
                {loading ? "Проверка…" : "Применить изменения"}
              </Button>
            </>
          )}
          {step === "result" && (
            <Button onClick={handleClose}>Закрыть</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <AlertDialog open={showCloseConfirm} onOpenChange={setShowCloseConfirm}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Выйти без применения?</AlertDialogTitle>
          <AlertDialogDescription>
            Загруженные изменения будут отменены и удалены. Вы уверены?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setShowCloseConfirm(false)}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={handleForceClose}>Выйти</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog open={showApplyConfirm} onOpenChange={setShowApplyConfirm}>
      <AlertDialogContent className="max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>Подтвердите применение</AlertDialogTitle>
          <div className="mt-2 space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border p-2">
                <div className="text-muted-foreground">Всего строк</div>
                <div className="font-semibold">{applyStats.total}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">Новые</div>
                <div className="font-semibold text-green-700">{applyStats.normal}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">С предупреждениями</div>
                <div className="font-semibold text-amber-700">{applyStats.warning}</div>
              </div>
              <div className="rounded border p-2">
                <div className="text-muted-foreground">С ошибками</div>
                <div className="font-semibold text-red-700">{applyStats.invalid}</div>
              </div>
            </div>
            <div className="rounded border p-2">
              <div className="text-muted-foreground">Файл</div>
              <div className="font-medium break-all">{file?.name || "—"}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                Лист: {sheets[selectedSheet] ?? currentPreview?.sheet_name ?? "—"}; Строки: {rowSelection.trim() || "все"}
              </div>
            </div>
            {applyStats.invalid > 0 && (
              <div className="rounded border border-red-200 bg-red-50 p-3">
                <div className="font-medium text-red-900 mb-2">
                  Ошибки в {applyStats.invalid} строках:
                </div>
                <div className="space-y-1 max-h-40 overflow-y-auto text-xs">
                  {errorBreakdownEntries.map(([error, count]) => (
                    <div key={error} className="flex items-start gap-2 text-red-800">
                      <span className="text-red-600 mt-0.5">•</span>
                      <span className="font-medium">{error}</span>
                      <span className="text-red-600 ml-auto">{count} строк</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 pt-2 border-t border-red-200">
                  <AlertDialogDescription className="text-red-700">
                    Режим "Пропустить ошибки" загрузит только строки без ошибок.
                  </AlertDialogDescription>
                </div>
              </div>
            )}
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => setShowApplyConfirm(false)}>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => void handleApplyConfirmed(false)} disabled={loading}>
            Загрузить с ошибками ({applyStats.uploadAll} строк)
          </AlertDialogAction>
          {applyStats.invalid > 0 && (
            <Button onClick={() => void handleApplyConfirmed(true)} disabled={loading}>
              Загрузить ({applyStats.uploadSkipInvalid} строк)
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  )
}
