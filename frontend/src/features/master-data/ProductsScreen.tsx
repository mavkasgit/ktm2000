import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

type Product = {
  id?: string | number;
  sku: string;
  name: string;
  type: string;
  unit?: string;
};

type ProductCreate = {
  sku: string;
  name: string;
  type: string;
  unit: string;
};

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";
const Select = ui.Select ?? "select";
const Table = ui.Table ?? "table";

async function apiListProducts(): Promise<Product[]> {
  const api = API as Record<string, any>;
  if (typeof api.listProducts === "function") {
    return api.listProducts();
  }
  const response = await fetch("/api/master-data/products");
  if (!response.ok) throw new Error(`Failed to load products: ${response.status}`);
  return response.json();
}

async function apiCreateProduct(payload: ProductCreate): Promise<void> {
  const api = API as Record<string, any>;
  if (typeof api.createProduct === "function") {
    await api.createProduct(payload);
    return;
  }
  const response = await fetch("/api/master-data/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to create product: ${response.status}`);
}

export function ProductsScreen() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const [form, setForm] = useState<ProductCreate>({
    sku: "",
    name: "",
    type: "finished_good",
    unit: "pcs",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await apiListProducts());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canSubmit = useMemo(() => form.sku.trim() && form.name.trim(), [form]);

  const onCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setError("");
    try {
      await apiCreateProduct({ ...form, sku: form.sku.trim(), name: form.name.trim() });
      setForm({ sku: "", name: "", type: "finished_good", unit: "pcs" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    }
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Изделия</h2>
      <form onSubmit={onCreate} style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(5, minmax(120px, 1fr))" }}>
        <Input value={form.sku} placeholder="Артикул / SKU" onChange={(e: any) => setForm((s) => ({ ...s, sku: e.target.value }))} />
        <Input value={form.name} placeholder="Наименование" onChange={(e: any) => setForm((s) => ({ ...s, name: e.target.value }))} />
        <Select
          value={form.type}
          options={[
            { label: "Готовая продукция", value: "finished_good" },
            { label: "Полуфабрикат", value: "semi_finished" },
            { label: "Компонент", value: "component" },
            { label: "Материал", value: "material" },
          ]}
          onChange={(e: any) => setForm((s) => ({ ...s, type: e.target.value }))}
        />
        <Input value={form.unit} placeholder="Ед. изм." onChange={(e: any) => setForm((s) => ({ ...s, unit: e.target.value }))} />
        <Button type="submit" disabled={!canSubmit}>Создать</Button>
      </form>

      {error ? <div role="alert">{error}</div> : null}
      {loading ? <div>Загрузка...</div> : null}

      <Table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th align="left">ID</th>
            <th align="left">Артикул</th>
            <th align="left">Наименование</th>
            <th align="left">Тип</th>
            <th align="left">Ед. изм.</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={String(item.id ?? `${item.sku}-${i}`)}>
              <td>{item.id ?? "-"}</td>
              <td>{item.sku}</td>
              <td>{item.name}</td>
              <td>{item.type}</td>
              <td>{item.unit ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </section>
  );
}
