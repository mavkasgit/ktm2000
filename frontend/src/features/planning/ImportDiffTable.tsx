type UnknownRecord = Record<string, unknown>;

const actionLabels: Record<string, string> = {
  create_position: "Создать",
  update_draft_position: "Обновить",
  ignore_unchanged: "Без изменений",
  cancel_draft_position: "Отменить",
  mark_possible_duplicate: "Возможный дубль",
};

const statusLabels: Record<string, string> = {
  pending: "Ожидает",
  warning: "Предупреждение",
  invalid: "Ошибка",
  applied: "Применено",
};

const errorLabels: Record<string, string> = {
  product_not_found: "Изделие не найдено",
  product_inactive: "Изделие неактивно",
  active_techcard_not_found: "Нет активной техкарты",
  active_techcard_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок в маршруте",
  duplicate_sku_due_date: "Дубликат: такой артикул со сроком уже есть",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает с ожидаемым",
  route_missing_required_step: "Отсутствует обязательный этап в маршруте",
  quantity_must_be_positive: "Количество должно быть > 0",
};

const warningLabels: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль техкарты",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "Период не определён",
};

function translateCodes(codes: string[] | unknown, labels: Record<string, string>): string {
  if (!Array.isArray(codes)) return String(codes ?? "");
  if (codes.length === 0) return "—";
  return codes.map((c) => labels[String(c)] ?? String(c)).join(", ");
}

const headers = [
  { key: "source_row_number", label: "Строка" },
  { key: "change_action", label: "Действие" },
  { key: "source_sku", label: "Артикул" },
  { key: "source_name", label: "Наименование" },
  { key: "quantity", label: "Кол-во" },
  { key: "route", label: "Маршрут" },
  { key: "status", label: "Статус" },
  { key: "errors", label: "Ошибки" },
  { key: "warnings", label: "Предупр." },
  { key: "variant", label: "Вариант" },
  { key: "duplicate_info", label: "Дубликат" },
];

function getString(row: UnknownRecord, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string") return value;
    if (typeof value === "number") return String(value);
    if (Array.isArray(value)) return value.join(", ");
  }
  return "";
}

function getAfter(row: UnknownRecord, key: string): unknown {
  const after = row.after_data;
  if (after && typeof after === "object") {
    return (after as UnknownRecord)[key];
  }
  return row[key];
}

export type ImportDiffTableProps = {
  rows: UnknownRecord[];
  sortConfig?: { key: string; dir: "asc" | "desc" } | null;
  onSort?: (key: string) => void;
};

export function ImportDiffTable({ rows, sortConfig, onSort }: ImportDiffTableProps) {
  return (
    <div style={{ maxHeight: 320, overflow: "auto", fontSize: 12, border: "1px solid #e5e7eb", borderRadius: 6 }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "#f9fafb" }}>
            {headers.map((h) => (
              <th
                key={h.key}
                onClick={() => onSort?.(h.key)}
                style={{
                  textAlign: "left",
                  padding: 8,
                  borderBottom: "1px solid #e5e7eb",
                  cursor: onSort ? "pointer" : "default",
                  userSelect: "none",
                  whiteSpace: "nowrap",
                }}
              >
                {h.label}
                {sortConfig?.key === h.key ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const afterDataRow = row.after_data as Record<string, unknown> | undefined;
            const rowNum = String(row.source_row_number ?? (afterDataRow?.source_row_numbers as number[] | undefined)?.[0] ?? "—");
            const planPosId = row.plan_position_id as number | undefined;
            const action = getString(row, "change_action");
            const status = getString(row, "status");
            const sku = String(getAfter(row, "source_sku") ?? getAfter(row, "sku") ?? "");
            const name = String(getAfter(row, "source_name") ?? getAfter(row, "product_name") ?? getAfter(row, "name") ?? "");
            const qtyRaw = getAfter(row, "quantity");
            const quantity = qtyRaw !== undefined && qtyRaw !== null && qtyRaw !== "" ? String(Number(qtyRaw).toFixed(0)) : "";
            const routeName = String(getAfter(row, "route_name") || "");
            const routeSource = String(getAfter(row, "route_source") || "");
            const routeLabel = routeName
              ? routeName
              : routeSource === "missing"
                ? "Маршрут не найден"
                : "—";
            const routeColor = routeSource === "missing" ? "#dc2626" : routeName ? "#16a34a" : "#6b7280";
            const errors = translateCodes(row.errors, errorLabels);
            const warnings = translateCodes(row.warnings, warningLabels);
            const variantObj = (getAfter(row, "source_payload") as UnknownRecord | undefined)?.techcard_pair as UnknownRecord | undefined;
            const variantLabel = variantObj
              ? (variantObj.resolved ? `${variantObj.pair_name ?? "пара"} (#${variantObj.pair_id ?? "?"})` : "не определен")
              : "—";

            // Build duplicate info message
            let duplicateInfo: string | null = null;
            const afterData = row.after_data as UnknownRecord | undefined;
            if (afterData?.duplicate_type === "within_import") {
              const dupRows = afterData.duplicate_rows as number[] | undefined;
              if (dupRows && dupRows.length > 1) {
                duplicateInfo = `Дубликат строк: ${dupRows.join(", ")}`;
              }
            } else if (afterData?.duplicate_type === "against_existing") {
              const existingId = afterData.duplicate_existing_id;
              const existingRow = afterData.duplicate_existing_row;
              duplicateInfo = `Дубликат позиции БД #${existingId}`;
              if (existingRow) duplicateInfo += ` (строка ${existingRow})`;
            }

            return (
              <tr key={idx} style={{
                background: row.status === "invalid" ? "#fef2f2" : row.status === "warning" ? "#fffbeb" : undefined,
              }}>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {planPosId ? (
                    <span title={`Позиция БД: #${planPosId}`}>
                      #{rowNum}
                      <span style={{ fontSize: 10, color: "#6b7280", display: "block" }}>БД #{planPosId}</span>
                    </span>
                  ) : (
                    `#${rowNum}`
                  )}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>
                  {actionLabels[action] ?? action}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{sku}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{name}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{quantity}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, color: routeColor, fontWeight: routeName ? 500 : 400 }}>
                  {routeLabel}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>
                  {statusLabels[status] ?? status}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, color: "#dc2626" }}>{errors}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, color: "#d97706" }}>{warnings}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{variantLabel}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, fontSize: 11, color: duplicateInfo ? "#dc2626" : undefined }}>
                  {duplicateInfo || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
