import React, { useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type BomLine = {
  componentProductId: string;
  quantityPer: string;
  scrapRate: string;
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

async function apiCreateBom(payload: { productId: string; revision: string; effectiveFrom: string; lines: BomLine[] }) {
  const api = API as Record<string, any>;
  if (typeof api.createBom === "function") {
    const bom = await api.createBom({
      product_id: Number(payload.productId),
      version: payload.revision,
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
  if (!response.ok) throw new Error(`Failed to create BOM: ${response.status}`);
}

export function BOMsScreen() {
  const [productId, setProductId] = useState("");
  const [revision, setRevision] = useState("A");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [lines, setLines] = useState<BomLine[]>([{ componentProductId: "", quantityPer: "1", scrapRate: "0" }]);
  const [status, setStatus] = useState("");

  const canSubmit = useMemo(() => productId.trim() && revision.trim() && lines.every((l) => l.componentProductId && Number(l.quantityPer) > 0), [lines, productId, revision]);

  const updateLine = (index: number, patch: Partial<BomLine>) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const addLine = () => setLines((prev) => [...prev, { componentProductId: "", quantityPer: "1", scrapRate: "0" }]);

  const removeLine = (index: number) => setLines((prev) => prev.filter((_, i) => i !== index));

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setStatus("Сохранение...");
    try {
      await apiCreateBom({ productId: productId.trim(), revision: revision.trim(), effectiveFrom, lines });
      setStatus("BOM создан");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Unknown error");
    }
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Состав изделия (BOM)</h2>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: 8 }}>
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(3, minmax(140px, 1fr))" }}>
          <Input value={productId} placeholder="ID изделия" onChange={(e: any) => setProductId(e.target.value)} />
          <Input value={revision} placeholder="Версия" onChange={(e: any) => setRevision(e.target.value)} />
          <Input type="date" value={effectiveFrom} onChange={(e: any) => setEffectiveFrom(e.target.value)} />
        </div>

        {lines.map((line, index) => (
          <div key={index} style={{ display: "grid", gap: 8, gridTemplateColumns: "2fr 1fr 1fr auto" }}>
            <Input value={line.componentProductId} placeholder="ID компонента" onChange={(e: any) => updateLine(index, { componentProductId: e.target.value })} />
            <Input type="number" min="0.0001" step="0.0001" value={line.quantityPer} onChange={(e: any) => updateLine(index, { quantityPer: e.target.value })} />
            <Input type="number" min="0" step="0.0001" value={line.scrapRate} onChange={(e: any) => updateLine(index, { scrapRate: e.target.value })} />
            <Button type="button" variant="outline" onClick={() => removeLine(index)} disabled={lines.length === 1}>Удалить</Button>
          </div>
        ))}

        <div style={{ display: "flex", gap: 8 }}>
          <Button type="button" variant="outline" onClick={addLine}>Добавить строку</Button>
          <Button type="submit" disabled={!canSubmit}>Создать BOM</Button>
        </div>
      </form>

      {status ? <div>{status}</div> : null}
    </section>
  );
}
