import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type Section = {
  id: number;
  code: string;
  name: string;
  kind: string;
};

type RouteStep = {
  seq: string;
  sectionId: string;
  operationCode: string;
  operationName: string;
  runMinutesPerUnit: string;
};

type RouteTemplate = {
  label: string;
  codes: Array<{ sectionCode: string; operationCode: string; operationName: string }>;
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

const KIND_LABELS: Record<string, string> = {
  production: "Производство",
  raw_stock: "Склад сырья",
  wip_stock: "Склад полуфабриката",
  finished_stock: "Склад готовой продукции",
};

const KIND_DOT: Record<string, string> = {
  production: "#3b82f6",
  raw_stock: "#10b981",
  wip_stock: "#f59e0b",
  finished_stock: "#8b5cf6",
};

const OPERATION_LABELS: Record<string, string> = {
  ISSUE_RAW: "Выдача сырья",
  DRILL: "Сверловка",
  PRESS_WINDOW: "Пресс окно",
  PRESS_COMB: "Пресс гребенка",
  SHOT: "Дробеструйная обработка",
  ANOD: "Анодирование",
  MOVE_TO_WIP: "Передача на склад полуфабриката",
  SAW: "Пила",
  PACK: "Упаковка",
  PACK_GLUE: "Упаковка с клеевой операцией",
  PACK_DIFFUSER: "Упаковка с рассеивателем",
  PACK_CUSTOM: "Дополнительная упаковочная операция",
  ACCEPT_FINISHED: "Приемка готовой продукции",
};

const ROUTE_TEMPLATES: RouteTemplate[] = [
  {
    label: "Полный через склад П/Ф",
    codes: [
      { sectionCode: "WH", operationCode: "ISSUE_RAW", operationName: "Выдача сырья" },
      { sectionCode: "PRESS", operationCode: "PRESS_WINDOW", operationName: "Пресс окно" },
      { sectionCode: "SHOT", operationCode: "SHOT", operationName: "Дробеструйная обработка" },
      { sectionCode: "ANOD", operationCode: "ANOD", operationName: "Анодирование" },
      { sectionCode: "WIP_WH", operationCode: "MOVE_TO_WIP", operationName: "Передача на склад полуфабриката" },
      { sectionCode: "SAW", operationCode: "SAW", operationName: "Пила" },
      { sectionCode: "PACK", operationCode: "PACK", operationName: "Упаковка" },
      { sectionCode: "FG_WH", operationCode: "ACCEPT_FINISHED", operationName: "Приемка готовой продукции" },
    ],
  },
  {
    label: "После анодирования сразу ГП",
    codes: [
      { sectionCode: "WH", operationCode: "ISSUE_RAW", operationName: "Выдача сырья" },
      { sectionCode: "PRESS", operationCode: "PRESS_COMB", operationName: "Пресс гребенка" },
      { sectionCode: "SHOT", operationCode: "SHOT", operationName: "Дробеструйная обработка" },
      { sectionCode: "ANOD", operationCode: "ANOD", operationName: "Анодирование" },
      { sectionCode: "FG_WH", operationCode: "ACCEPT_FINISHED", operationName: "Приемка готовой продукции" },
    ],
  },
  {
    label: "Без первичной операции",
    codes: [
      { sectionCode: "WH", operationCode: "ISSUE_RAW", operationName: "Выдача сырья" },
      { sectionCode: "SHOT", operationCode: "SHOT", operationName: "Дробеструйная обработка" },
      { sectionCode: "ANOD", operationCode: "ANOD", operationName: "Анодирование" },
      { sectionCode: "FG_WH", operationCode: "ACCEPT_FINISHED", operationName: "Приемка готовой продукции" },
    ],
  },
];

const emptyStep = (seq: number): RouteStep => ({
  seq: String(seq),
  sectionId: "",
  operationCode: "",
  operationName: "",
  runMinutesPerUnit: "1",
});

async function apiListSections(): Promise<Section[]> {
  const api = API as Record<string, any>;
  if (typeof api.listSections === "function") {
    return api.listSections();
  }
  const response = await fetch("/api/sections");
  if (!response.ok) throw new Error(`Failed to load sections: ${response.status}`);
  return response.json();
}

async function apiCreateRoute(payload: { productId: string; routeCode: string; revision: string; steps: RouteStep[] }) {
  const api = API as Record<string, any>;
  if (typeof api.createRoute === "function" && typeof api.createRouteStep === "function") {
    const route = await api.createRoute({
      product_id: Number(payload.productId),
      name: payload.routeCode,
      version: payload.revision,
      is_active: true,
    });
    for (const [index, step] of payload.steps.entries()) {
      await api.createRouteStep(Number(route.id), {
        sequence: Number(step.seq) || (index + 1) * 10,
        section_id: Number(step.sectionId),
        operation_code: step.operationCode || null,
        operation_name: step.operationName || OPERATION_LABELS[step.operationCode] || `Этап ${step.seq}`,
        norm_time_minutes: Number(step.runMinutesPerUnit) || null,
        is_final: index === payload.steps.length - 1,
      });
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
  const [steps, setSteps] = useState<RouteStep[]>([emptyStep(10)]);
  const [status, setStatus] = useState("");
  const [sections, setSections] = useState<Section[]>([]);

  const loadSections = useCallback(async () => {
    try {
      setSections(await apiListSections());
    } catch {
      // The form can still render; the user will see empty section selects.
    }
  }, []);

  useEffect(() => {
    void loadSections();
  }, [loadSections]);

  const sectionMap = useMemo(() => {
    const map: Record<string, Section> = {};
    for (const section of sections) map[String(section.id)] = section;
    return map;
  }, [sections]);

  const sectionByCode = useMemo(() => {
    const map: Record<string, Section> = {};
    for (const section of sections) map[section.code] = section;
    return map;
  }, [sections]);

  const canSubmit = useMemo(() => {
    return (
      productId.trim() &&
      routeCode.trim() &&
      revision.trim() &&
      steps.every((step) => step.sectionId.trim() && Number(step.runMinutesPerUnit) >= 0)
    );
  }, [productId, routeCode, revision, steps]);

  const updateStep = (index: number, patch: Partial<RouteStep>) => {
    setSteps((prev) => prev.map((step, i) => (i === index ? { ...step, ...patch } : step)));
  };

  const addStep = () => {
    const nextSeq = (steps.length + 1) * 10;
    setSteps((prev) => [...prev, emptyStep(nextSeq)]);
  };

  const removeStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index));
  };

  const applyTemplate = (template: RouteTemplate) => {
    const nextSteps = template.codes
      .map((item, index) => {
        const section = sectionByCode[item.sectionCode];
        return {
          seq: String((index + 1) * 10),
          sectionId: section ? String(section.id) : "",
          operationCode: item.operationCode,
          operationName: item.operationName,
          runMinutesPerUnit: "1",
        };
      })
      .filter((step) => step.sectionId);
    if (nextSteps.length) setSteps(nextSteps);
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setStatus("Сохранение...");
    try {
      await apiCreateRoute({ productId: productId.trim(), routeCode: routeCode.trim(), revision: revision.trim(), steps });
      setStatus("Маршрут создан");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Не удалось создать маршрут");
    }
  };

  const firstKind = sectionMap[steps[0]?.sectionId]?.kind;
  const lastKind = sectionMap[steps[steps.length - 1]?.sectionId]?.kind;

  return (
    <section style={{ display: "grid", gap: 16 }}>
      <h2 className="text-lg font-semibold">Маршруты</h2>

      <div style={{ display: "grid", gap: 8 }}>
        <div style={{ color: "#4b5563", fontSize: 14 }}>
          Типовая схема: WH → [DRILL | PRESS_WINDOW | PRESS_COMB | пропуск] → [SHOT | пропуск] → ANOD → [FG_WH | WIP_WH → SAW → PACK → FG_WH].
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {ROUTE_TEMPLATES.map((template) => (
            <Button key={template.label} type="button" variant="outline" onClick={() => applyTemplate(template)}>
              {template.label}
            </Button>
          ))}
        </div>
      </div>

      <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>ID изделия</label>
            <Input value={productId} placeholder="Например, 1" onChange={(e: any) => setProductId(e.target.value)} />
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Код маршрута</label>
            <Input value={routeCode} placeholder="Например, MAIN" onChange={(e: any) => setRouteCode(e.target.value)} />
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Версия</label>
            <Input value={revision} placeholder="Например, A" onChange={(e: any) => setRevision(e.target.value)} />
          </div>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          {steps.map((step, index) => {
            const section = sectionMap[step.sectionId];
            return (
              <div
                key={index}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  padding: 16,
                  background: "#fafafa",
                  display: "grid",
                  gap: 12,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: 600, fontSize: 14, color: "#111827" }}>Этап {index + 1}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <label style={{ fontSize: 12, color: "#6b7280" }}>Порядок:</label>
                    <Input
                      value={step.seq}
                      onChange={(e: any) => updateStep(index, { seq: e.target.value })}
                      style={{ width: 72, textAlign: "center" }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => removeStep(index)}
                      disabled={steps.length === 1}
                      style={{ padding: "4px 10px", fontSize: 12 }}
                    >
                      Удалить
                    </Button>
                  </div>
                </div>

                <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                  <div style={{ display: "grid", gap: 4 }}>
                    <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Участок</label>
                    <select
                      value={step.sectionId}
                      onChange={(e) => updateStep(index, { sectionId: e.target.value })}
                      style={{
                        padding: "8px 12px",
                        borderRadius: 6,
                        border: "1px solid #d1d5db",
                        fontSize: 14,
                        background: "#fff",
                        width: "100%",
                      }}
                    >
                      <option value="">Выберите участок</option>
                      {sections.map((sectionItem) => (
                        <option key={sectionItem.id} value={String(sectionItem.id)}>
                          {sectionItem.code} · {sectionItem.name}
                        </option>
                      ))}
                    </select>
                    {section && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#6b7280" }}>
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: "50%",
                            background: KIND_DOT[section.kind] ?? "#9ca3af",
                            display: "inline-block",
                          }}
                        />
                        {KIND_LABELS[section.kind] ?? section.kind}
                      </div>
                    )}
                  </div>

                  <div style={{ display: "grid", gap: 4 }}>
                    <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Код операции</label>
                    <select
                      value={step.operationCode}
                      onChange={(e) => updateStep(index, { operationCode: e.target.value, operationName: OPERATION_LABELS[e.target.value] ?? step.operationName })}
                      style={{
                        padding: "8px 12px",
                        borderRadius: 6,
                        border: "1px solid #d1d5db",
                        fontSize: 14,
                        background: "#fff",
                        width: "100%",
                      }}
                    >
                      <option value="">Без кода</option>
                      {Object.entries(OPERATION_LABELS).map(([code, label]) => (
                        <option key={code} value={code}>
                          {code} · {label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div style={{ display: "grid", gap: 4 }}>
                    <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Название операции</label>
                    <Input
                      value={step.operationName}
                      placeholder="Например, Пресс окно"
                      onChange={(e: any) => updateStep(index, { operationName: e.target.value })}
                    />
                  </div>

                  <div style={{ display: "grid", gap: 4 }}>
                    <label style={{ fontSize: 13, fontWeight: 500, color: "#374151" }}>Норма, мин/шт</label>
                    <Input
                      type="number"
                      min="0"
                      step="0.0001"
                      value={step.runMinutesPerUnit}
                      onChange={(e: any) => updateStep(index, { runMinutesPerUnit: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <Button type="button" variant="outline" onClick={addStep}>
            + Добавить этап
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            Создать маршрут
          </Button>
          {firstKind && firstKind !== "raw_stock" && (
            <span style={{ color: "#c0392b", fontSize: 13 }}>Рекомендуемый первый этап: WH, склад сырья</span>
          )}
          {lastKind && lastKind !== "finished_stock" && (
            <span style={{ color: "#c0392b", fontSize: 13 }}>Рекомендуемый последний этап: FG_WH, склад готовой продукции</span>
          )}
        </div>
      </form>

      {status ? (
        <div
          style={{
            padding: 12,
            borderRadius: 6,
            background: status === "Маршрут создан" ? "#d1fae5" : "#fee2e2",
            color: status === "Маршрут создан" ? "#065f46" : "#991b1b",
            fontSize: 14,
          }}
        >
          {status}
        </div>
      ) : null}
    </section>
  );
}
