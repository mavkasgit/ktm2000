import { type PlanPositionOut, type ProductionPlanningRowDetail, type ProductionPlanningStage } from "@/shared/api/productionPlans"
import { type RowDetailsData } from "./types"

// ─── Label maps ──────────────────────────────────────────────────────────────

const routeErrorLabels: Record<string, string> = {
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
  active_route_not_found: "Активный маршрут не найден",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Маршрут содержит неактивный участок",
  route_not_matching_import_signature: "Маршрут не совпадает с импортом",
  route_missing_required_step: "Отсутствует обязательный этап",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  manual_route_not_found: "Ручной маршрут не найден",
  manual_route_inactive: "Ручной маршрут неактивен",
  auto_fallback: "Маршрут скорректирован автоматически — проверьте",
}

const errorLabelsRaw: Record<string, string> = {
  product_not_found: "Изделие не найдено",
  product_inactive: "Изделие неактивно",
  active_techcard_not_found: "Нет активной техкарты",
  active_techcard_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок в маршруте",
  duplicate_sku_due_date: "Дубликат строки Excel: такая же строка уже есть",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает с ожидаемым",
  route_missing_required_step: "Отсутствует обязательный этап в маршруте",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  quantity_must_be_positive: "Количество должно быть > 0",
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
}

const warningLabelsRaw: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль техкарты",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "не определен",
  route_auto_fallback: "Маршрут скорректирован автоматически — проверьте корректность",
  row_selection_applied: "Применён фильтр строк",
  row_selection_auto_included: "Автодобавлены парные строки",
  paired_row_auto_included: "Автодобавлена парная строка",
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "дата неизвестна"
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function buildRouteMetaLabel(params: {
  route_source: string | null
  route_origin: string | null
  route_match_quality: string | null
  route_assigned_at: string | null
}): string {
  const assignedAt = formatRouteAssignedAt(params.route_assigned_at)
  if (params.route_origin === "manual_confirmed" || params.route_source === "manual") {
    return `вручную • ${assignedAt}`
  }
  if (params.route_origin === "auto" || params.route_source === "auto") {
    const quality = params.route_match_quality === "exact" ? "полное" : "скорректирован"
    return `автомаппинг (${quality}) • ${assignedAt}`
  }
  if (params.route_origin === "legacy" || params.route_source === "legacy") {
    return "legacy • дата неизвестна"
  }
  if (params.route_source === "missing") {
    return "не найден"
  }
  return "—"
}

function translateLabel(code: string, labels: Record<string, string>): string {
  const [base] = String(code).split(":")
  return labels[base] ?? code
}

function translateLabels(codes: string[], labels: Record<string, string>): string[] {
  return codes.map((c) => translateLabel(c, labels))
}

function buildRawExcelRows(
  rawExcelRow: Record<string, unknown> | null | undefined,
  payload: Record<string, unknown> | null | undefined,
): { rowNumber: string; text: string }[] | undefined {
  const rawColumnsByRow = payload?.raw_columns_by_row as Record<string, Record<string, unknown>> | undefined
  if (rawColumnsByRow && Object.keys(rawColumnsByRow).length > 0) {
    return Object.entries(rawColumnsByRow)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([num, data]) => ({
        rowNumber: num,
        text: Object.values(data).filter(Boolean).map(String).join(" | "),
      }))
  }
  if (rawExcelRow && Object.keys(rawExcelRow).length > 0) {
    const rowNum = String((payload?.row_numbers as number[] | undefined)?.[0] ?? "")
    return [{
      rowNumber: rowNum,
      text: Object.values(rawExcelRow).filter(Boolean).map(String).join(" | "),
    }]
  }
  return undefined
}

// ─── Adapters ────────────────────────────────────────────────────────────────

export function adaptPlanPositionOut(pos: PlanPositionOut): RowDetailsData {
  return {
    id: pos.id,
    sourceRowNumber: pos.source_row_number,
    sku: pos.source_sku,
    name: pos.source_name,
    quantity: pos.quantity,
    status: pos.status,
    routeName: pos.route_name,
    routeError: pos.route_error ? translateLabel(pos.route_error, routeErrorLabels) : null,
    routeMeta: buildRouteMetaLabel({
      route_source: pos.route_source,
      route_origin: pos.route_origin,
      route_match_quality: pos.route_match_quality,
      route_assigned_at: pos.route_assigned_at,
    }),
    errors: translateLabels(pos.errors, errorLabelsRaw),
    warnings: translateLabels(pos.warnings, warningLabelsRaw),
    productionPlanId: pos.production_plan_id,
    routeCheckIssues: [],
    rawExcelRows: buildRawExcelRows(pos.raw_excel_row, pos.payload),
  }
}

export function adaptExecutionDetail(detail: ProductionPlanningRowDetail): RowDetailsData {
  return {
    id: detail.plan_position_id,
    sourceRowNumber: detail.source_row_number,
    sku: detail.source_sku,
    name: detail.source_name,
    quantity: detail.quantity,
    status: detail.position_status,
    routeName: detail.route_name,
    routeError: detail.route_error,
    routeMeta: buildRouteMetaLabel({
      route_source: detail.route_source,
      route_origin: detail.route_origin,
      route_match_quality: detail.route_match_quality,
      route_assigned_at: detail.route_assigned_at,
    }),
    errors: [],
    warnings: [],
    productionPlanId: detail.production_plan_id,
    stages: detail.stages,
    rawExcelRows: buildRawExcelRows(detail.raw_excel_row, detail.payload),
    currentStageSectionId: (detail as any).current_stage_section_id,
    currentStageSectionName: (detail as any).current_stage_section_name,
    currentStageSectionCode: (detail as any).current_stage_section_code,
    currentStageSequence: (detail as any).current_stage_sequence,
    currentStageOperation: (detail as any).current_stage_operation,
    currentStageTaskStatus: (detail as any).current_stage_task_status,
  }
}

export function adaptRawImportRow(row: Record<string, unknown>): RowDetailsData {
  const afterData = (row.after_data as Record<string, unknown>) || {}
  const sourceRowNumber = (row.source_row_number as number) ?? null
  const sku = (afterData.source_sku ?? row.source_sku ?? "") as string
  const name = (afterData.source_name ?? row.source_name ?? null) as string | null
  const quantity = (row.quantity ?? "") as string | number
  const status = (row.status ?? "") as string
  const routeName = (row.route_name ?? null) as string | null

  const rawErrors = (row.errors as string[] | undefined) ?? []
  const rawWarnings = (row.warnings as string[] | undefined) ?? []

  const payload = (row.payload as Record<string, unknown> | undefined) ?? {}
  const rawExcelRows = buildRawExcelRows(
    payload.raw_excel_row as Record<string, unknown> | undefined,
    payload,
  )

  return {
    id: sourceRowNumber ?? (payload.row_numbers as number[] | undefined)?.[0] ?? 0,
    sourceRowNumber,
    sku,
    name,
    quantity,
    status,
    routeName,
    routeError: null,
    routeMeta: buildRouteMetaLabel({
      route_source: (row.route_source as string | null) ?? null,
      route_origin: (row.route_origin as string | null) ?? null,
      route_match_quality: (row.route_match_quality as string | null) ?? null,
      route_assigned_at: (row.route_assigned_at as string | null) ?? null,
    }),
    errors: translateLabels(rawErrors, errorLabelsRaw),
    warnings: translateLabels(rawWarnings, warningLabelsRaw),
    productionPlanId: 0,
    rawExcelRows,
  }
}
