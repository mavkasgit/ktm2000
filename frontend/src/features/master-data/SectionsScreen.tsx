import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type Section = {
  id?: string | number;
  code: string;
  name: string;
  description?: string | null;
  kind?: string;
};

type SectionCreate = {
  code: string;
  name: string;
  description: string;
};

const KIND_LABELS: Record<string, string> = {
  production: "Производство",
  raw_stock: "Склад сырья",
  wip_stock: "Склад полуфабриката",
  finished_stock: "Склад готовой продукции",
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";
const Table = ui.Table ?? "table";

async function apiListSections(): Promise<Section[]> {
  const api = API as Record<string, any>;
  if (typeof api.listSections === "function") {
    return api.listSections();
  }
  const response = await fetch("/api/master-data/sections");
  if (!response.ok) throw new Error(`Failed to load sections: ${response.status}`);
  return response.json();
}

async function apiCreateSection(payload: SectionCreate): Promise<void> {
  const api = API as Record<string, any>;
  if (typeof api.createSection === "function") {
    await api.createSection(payload);
    return;
  }
  const response = await fetch("/api/master-data/sections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to create section: ${response.status}`);
}

export function SectionsScreen() {
  const [items, setItems] = useState<Section[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [form, setForm] = useState<SectionCreate>({ code: "", name: "", description: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await apiListSections());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canSubmit = useMemo(() => form.code.trim() && form.name.trim(), [form]);

  const onCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    try {
      await apiCreateSection({ ...form, code: form.code.trim(), name: form.name.trim() });
      setForm({ code: "", name: "", description: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    }
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Участки</h2>
      <form onSubmit={onCreate} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(4, minmax(120px, 1fr))" }}>
        <Input value={form.code} placeholder="Код участка" onChange={(e: any) => setForm((s) => ({ ...s, code: e.target.value }))} />
        <Input value={form.name} placeholder="Название" onChange={(e: any) => setForm((s) => ({ ...s, name: e.target.value }))} />
        <Input value={form.description} placeholder="Описание" onChange={(e: any) => setForm((s) => ({ ...s, description: e.target.value }))} />
        <Button type="submit" disabled={!canSubmit}>Создать</Button>
      </form>

      {error ? <div role="alert">{error}</div> : null}
      {loading ? <div>Загрузка...</div> : null}

      <Table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th align="left">ID</th>
            <th align="left">Код</th>
            <th align="left">Название</th>
            <th align="left">Тип</th>
            <th align="left">Описание</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={String(item.id ?? `${item.code}-${i}`)}>
              <td>{item.id ?? "-"}</td>
              <td>{item.code}</td>
              <td>{item.name}</td>
              <td>{KIND_LABELS[item.kind ?? "production"] ?? item.kind ?? "-"}</td>
              <td>{item.description ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}
