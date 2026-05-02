import { useState } from "react";

const defaultFields: Record<string, string> = {
  sku: "Артикул",
  product_name: "Наименование",
  quantity: "Количество",
  due_date: "Срок",
  customer: "Заказчик",
  priority: "Приоритет",
  order_ref: "Заказ",
};

export type ColumnMappingDialogProps = {
  open: boolean;
  onClose: () => void;
  onApply: (mapping: Record<string, string>) => void;
};

export function ColumnMappingDialog({ open, onClose, onApply }: ColumnMappingDialogProps) {
  const [mapping, setMapping] = useState<Record<string, string>>(defaultFields);

  if (!open) return null;

  function updateField(key: string, value: string) {
    setMapping((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        style={{ background: "#fff", borderRadius: 8, padding: 20, width: 420, maxWidth: "90vw" }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 12px" }}>Сопоставление колонок</h3>
        <div style={{ display: "grid", gap: 8 }}>
          {Object.entries(defaultFields).map(([key, defaultValue]) => (
            <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
              <span style={{ fontWeight: 600 }}>{key}</span>
              <input
                type="text"
                value={mapping[key] ?? defaultValue}
                onChange={(e) => updateField(key, e.target.value)}
                style={{
                  padding: "6px 8px",
                  borderRadius: 4,
                  border: "1px solid #d1d5db",
                  fontSize: 13,
                }}
              />
            </label>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button
            onClick={onClose}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "1px solid #d1d5db",
              background: "#f9fafb",
              cursor: "pointer",
            }}
          >
            Отмена
          </button>
          <button
            onClick={() => {
              onApply(mapping);
              onClose();
            }}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "1px solid #2563eb",
              background: "#2563eb",
              color: "#fff",
              cursor: "pointer",
            }}
          >
            Применить
          </button>
        </div>
      </div>
    </div>
  );
}
