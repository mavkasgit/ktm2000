import React, { useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type RouteStep = {
  seq: string;
  sectionId: string;
  setupMinutes: string;
  runMinutesPerUnit: string;
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

async function apiCreateRoute(payload: { productId: string; routeCode: string; revision: string; steps: RouteStep[] }) {
  const api = API as Record<string, any>;
  if (typeof api.createRoute === "function") {
    const route = await api.createRoute({
      product_id: Number(payload.productId),
      name: payload.routeCode,
      version: payload.revision,
      is_active: true,
    });
    if (typeof api.createRouteStep === "function") {
      for (const [index, step] of payload.steps.entries()) {
        await api.createRouteStep(Number(route.id), {
          sequence: Number(step.seq) || index + 1,
          section_id: Number(step.sectionId),
          operation_name: `Step ${step.seq}`,
          norm_time_minutes: Number(step.runMinutesPerUnit) || null,
          is_final: index === payload.steps.length - 1,
        });
      }
    }
    return;
  }
  const response = await fetch("/api/master-data/routes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to create route: ${response.status}`);
}

export function RoutesScreen() {
  const [productId, setProductId] = useState("");
  const [routeCode, setRouteCode] = useState("MAIN");
  const [revision, setRevision] = useState("A");
  const [steps, setSteps] = useState<RouteStep[]>([{ seq: "10", sectionId: "", setupMinutes: "0", runMinutesPerUnit: "1" }]);
  const [status, setStatus] = useState("");

  const canSubmit = useMemo(() => {
    return productId.trim() && routeCode.trim() && revision.trim() && steps.every((s) => s.sectionId.trim() && Number(s.runMinutesPerUnit) >= 0);
  }, [productId, routeCode, revision, steps]);

  const updateStep = (index: number, patch: Partial<RouteStep>) => {
    setSteps((prev) => prev.map((step, i) => (i === index ? { ...step, ...patch } : step)));
  };

  const addStep = () => {
    const nextSeq = (steps.length + 1) * 10;
    setSteps((prev) => [...prev, { seq: String(nextSeq), sectionId: "", setupMinutes: "0", runMinutesPerUnit: "1" }]);
  };

  const removeStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index));
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setStatus("Сохранение...");
    try {
      await apiCreateRoute({ productId: productId.trim(), routeCode: routeCode.trim(), revision: revision.trim(), steps });
      setStatus("Маршрут создан");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Unknown error");
    }
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Маршруты</h2>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: 8 }}>
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(3, minmax(140px, 1fr))" }}>
          <Input value={productId} placeholder="ID изделия" onChange={(e: any) => setProductId(e.target.value)} />
          <Input value={routeCode} placeholder="Код маршрута" onChange={(e: any) => setRouteCode(e.target.value)} />
          <Input value={revision} placeholder="Версия" onChange={(e: any) => setRevision(e.target.value)} />
        </div>

        {steps.map((step, index) => (
          <div key={index} style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 2fr 1fr 1fr auto" }}>
            <Input value={step.seq} placeholder="Порядок" onChange={(e: any) => updateStep(index, { seq: e.target.value })} />
            <Input value={step.sectionId} placeholder="ID участка" onChange={(e: any) => updateStep(index, { sectionId: e.target.value })} />
            <Input type="number" min="0" step="1" value={step.setupMinutes} onChange={(e: any) => updateStep(index, { setupMinutes: e.target.value })} />
            <Input type="number" min="0" step="0.0001" value={step.runMinutesPerUnit} onChange={(e: any) => updateStep(index, { runMinutesPerUnit: e.target.value })} />
            <Button type="button" variant="outline" onClick={() => removeStep(index)} disabled={steps.length === 1}>Удалить</Button>
          </div>
        ))}

        <div style={{ display: "flex", gap: 8 }}>
          <Button type="button" variant="outline" onClick={addStep}>Добавить этап</Button>
          <Button type="submit" disabled={!canSubmit}>Создать маршрут</Button>
        </div>
      </form>

      {status ? <div>{status}</div> : null}
    </section>
  );
}
