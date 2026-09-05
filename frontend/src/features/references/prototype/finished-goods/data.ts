// ПРОТОТИП #143 (throwaway) — слой данных для вариантов страницы «Продукты».
// Список ГП и маршруты — реальный API; состав (BoM на Product) ещё не существует —
// детерминированный мок из реального сырья. Read-only.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as API from "@/shared/api/products";
import type { Product, ProductRouteStageOut } from "@/shared/api/products";
import type { RouteStepsDisplayProps } from "@/shared/ui/RouteStepsDisplay";

export function useFinishedGoods() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    API.fetchAllProducts({ type: "finished_good" })
      .then((data) => { if (!cancelled) setItems(data); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  return { items, loading, error };
}

export function useRawMaterialsForMock() {
  const [items, setItems] = useState<Product[]>([]);
  useEffect(() => {
    let cancelled = false;
    API.fetchAllProducts({ type: "component" })
      .then((data) => { if (!cancelled) setItems(data); })
      .catch(() => { /* прототип: без сырья состав просто пуст */ });
    return () => { cancelled = true; };
  }, []);
  return items;
}

export function useRouteStages(productId: number | null) {
  return useQuery({
    queryKey: ["prototype-finished-goods", "route-stages", productId],
    queryFn: () => API.getProductRouteStages(productId!),
    enabled: productId != null,
  });
}

/** ProductRouteStageOut[] (секции с операциями) → плоские шаги для RouteStepsDisplay. */
export function stagesToSteps(stages: ProductRouteStageOut[]): RouteStepsDisplayProps["steps"] {
  return stages.flatMap((stage) =>
    stage.operations.length === 0
      ? [{
          sequence: stage.sequence,
          section_code: stage.section_code,
          section_name: stage.section_name,
          is_significant: stage.is_significant,
          operation_code: null,
          operation_name: "",
        }]
      : stage.operations.map((op) => ({
          sequence: stage.sequence,
          section_code: stage.section_code,
          section_name: stage.section_name,
          is_significant: stage.is_significant,
          operation_code: op.operation_code,
          operation_name: op.operation_name,
        })),
  );
}

export type MockCompositionLine = {
  sku: string;
  name: string;
  qty: number;
  unit: string;
  photo_thumb: string | null;
};

function hashSku(sku: string): number {
  let h = 2166136261;
  for (let i = 0; i < sku.length; i++) {
    h ^= sku.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/** Детерминированный мок состава: 1–2 компонента из реального сырья, количество 1–4. */
export function mockComposition(sku: string, rawMaterials: Product[]): MockCompositionLine[] {
  if (rawMaterials.length === 0) return [];
  const h = hashSku(sku);
  const count = h % 2 === 0 ? 1 : 2;
  const lines: MockCompositionLine[] = [];
  for (let i = 0; i < count; i++) {
    const material = rawMaterials[(h + i * 7919) % rawMaterials.length];
    if (lines.some((l) => l.sku === material.sku)) continue;
    lines.push({
      sku: material.sku,
      name: material.name,
      qty: 1 + ((h >> (i * 4 + 3)) % 4),
      unit: material.unit || "шт",
      photo_thumb: material.photo_thumb,
    });
  }
  return lines;
}
