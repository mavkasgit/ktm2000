import React, { useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type BomLine = {
  componentProductId: string;
  quantityPer: string;
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

async function apiCreateBom(payload: {
  productId: string;
  revision: string;
  processingType: "standart_processing" | "paired_processing";
  lines: BomLine[];
}) {
  const api = API as Record<string, any>;
  if (typeof api.createBom === "function") {
    const bom = await api.createBom({
      product_id: Number(payload.productId),
      version: payload.revision,
      processing_type: payload.processingType,
      is_active: true,
    });
    if (typeof api.createBomLine === "function") {
      for (const line of payload.lines) {
        await api.createBomLine(Number(bom.id), {
          component_product_id: Number(line.componentProductId),
          quantity: Number(line.quantityPer),
          unit: "pcs",
        });
      }
    }
    return;
  }
  const response = await fetch("/api/master-data/boms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Не удалось создать техкарту: ${response.status}`);
}

export function BOMsScreen() {
  const [productId, setProductId] = useState("");
  const [revision, setRevision] = useState("A");
  const [processingType, setProcessingType] = useState<"standart_processing" | "paired_processing">("standart_processing");
  const [lines, setLines] = useState<BomLine[]>([{ componentProductId: "", quantityPer: "1" }]);
  const [techcards, setTechcards] = useState<any[]>([]);
  const [status, setStatus] = useState("");

  const canSubmit = useMemo(() => productId.trim() && revision.trim() && lines.every((l) => l.componentProductId && Number(l.quantityPer) > 0), [lines, productId, revision]);

  const updateLine = (index: number, patch: Partial<BomLine>) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const addLine = () => setLines((prev) => [...prev, { componentProductId: "", quantityPer: "1" }]);

  const removeLine = (index: number) => setLines((prev) => prev.filter((_, i) => i !== index));

  const loadTechcards = async () => {
    const api = API as Record<string, any>;
    if (typeof api.listBoms === "function") {
      const rows = await api.listBoms();
      setTechcards(rows);
    }
  };

  React.useEffect(() => {
    loadTechcards().catch(() => setTechcards([]));
  }, []);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setStatus("Сохранение...");
    try {
      await apiCreateBom({
        productId: productId.trim(),
        revision: revision.trim(),
        processingType,
        lines,
      });
      setStatus("Техкарта создана");
      await loadTechcards();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Unknown error");
    }
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Техкарта изделия</h2>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: 8 }}>
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(3, minmax(140px, 1fr))" }}>
          <Input value={productId} placeholder="ID артикула" onChange={(e: any) => setProductId(e.target.value)} />
          <Input value={revision} placeholder="Версия" onChange={(e: any) => setRevision(e.target.value)} />
          <select value={processingType} onChange={(e: any) => setProcessingType(e.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
            <option value="standart_processing">standart_processing</option>
            <option value="paired_processing">paired_processing</option>
          </select>
        </div>

        {lines.map((line, index) => (
          <div key={index} style={{ display: "grid", gap: 8, gridTemplateColumns: "2fr 1fr 1fr auto" }}>
            <Input value={line.componentProductId} placeholder="ID компонента" onChange={(e: any) => updateLine(index, { componentProductId: e.target.value })} />
            <Input type="number" min="0.0001" step="0.0001" value={line.quantityPer} onChange={(e: any) => updateLine(index, { quantityPer: e.target.value })} />
            <div />
            <Button type="button" variant="outline" onClick={() => removeLine(index)} disabled={lines.length === 1}>Удалить</Button>
          </div>
        ))}

        <div style={{ display: "flex", gap: 8 }}>
          <Button type="button" variant="outline" onClick={addLine}>Добавить строку</Button>
          <Button type="submit" disabled={!canSubmit}>Создать техкарту</Button>
        </div>
      </form>

      {status ? <div>{status}</div> : null}

      <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f9fafb" }}>
              <th style={{ textAlign: "left", padding: 8 }}>ID</th>
              <th style={{ textAlign: "left", padding: 8 }}>ID артикула</th>
              <th style={{ textAlign: "left", padding: 8 }}>Версия</th>
              <th style={{ textAlign: "left", padding: 8 }}>Тип</th>
              <th style={{ textAlign: "left", padding: 8 }}>Активна</th>
            </tr>
          </thead>
          <tbody>
            {techcards.map((card) => (
              <tr key={card.id}>
                <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.id}</td>
                <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.product_id}</td>
                <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.version}</td>
                <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.processing_type}</td>
                <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.is_active ? "Да" : "Нет"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
