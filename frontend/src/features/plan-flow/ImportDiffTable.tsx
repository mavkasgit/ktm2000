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
  active_bom_not_found: "Нет активной техкарты",
  active_bom_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок в маршруте",
  duplicate_sku_due_date: "Дубль артикул + срок",
  quantity_must_be_positive: "Количество должно быть > 0",
};

const warningLabels: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "Период не определён",
};

function translateCodes(codes: string[] | unknown, labels: Record<string, string>): string {
  if (!Array.isArray(codes)) return String(codes ?? "");
  if (codes.length === 0) return "—";
  return codes.map((c) => labels[String(c)] ?? String(c)).join(", ");
}

const headers = [
  { key: "change_action", label: "Действие" },
  { key: "source_sku", label: "Артикул" },
  { key: "source_name", label: "Наименование" },
  { key: "quantity", label: "Кол-во" },
  { key: "status", label: "Статус" },
  { key: "errors", label: "Ошибки" },
  { key: "warnings", label: "Предупр." },
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
            const action = getString(row, "change_action");
            const status = getString(row, "status");
            const sku = String(getAfter(row, "source_sku") ?? getAfter(row, "sku") ?? "");
            const name = String(getAfter(row, "source_name") ?? getAfter(row, "product_name") ?? getAfter(row, "name") ?? "");
            const qtyRaw = getAfter(row, "quantity");
            const quantity = qtyRaw !== undefined && qtyRaw !== null && qtyRaw !== "" ? String(Number(qtyRaw).toFixed(0)) : "";
            const errors = translateCodes(row.errors, errorLabels);
            const warnings = translateCodes(row.warnings, warningLabels);

            return (
              <tr key={idx}>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>
                  {actionLabels[action] ?? action}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{sku}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{name}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{quantity}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>
                  {statusLabels[status] ?? status}
                </td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, color: "#dc2626" }}>{errors}</td>
                <td style={{ borderBottom: "1px solid #f3f4f6", padding: 8, color: "#d97706" }}>{warnings}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
