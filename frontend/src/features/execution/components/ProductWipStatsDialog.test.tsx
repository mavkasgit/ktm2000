// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import type { ProductWipStats } from "@/shared/api/productionPlans";

// Мокаем API-слой: диалог обязан показывать размер каждой строки из ответа.
vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  getProductWipStats: vi.fn(),
}));

import { getProductWipStats } from "@/shared/api/productionPlans";
import { ProductWipStatsDialog } from "./ProductWipStatsDialog";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const stats: ProductWipStats = {
  sku: "TEST-SKU",
  product_name: "Тестовое изделие",
  product_id: 1,
  remainders: [
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      completed_ops: "Сверловка",
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 2000 },
      dimensions_label: "2 м",
      quantity: 10,
      max_completed_seq: 0,
      stages_with_icons: [],
    },
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      completed_ops: "Сверловка",
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 3000 },
      dimensions_label: "3 м",
      quantity: 4,
      max_completed_seq: 0,
      stages_with_icons: [],
    },
  ],
  in_work: [
    {
      section_id: 21,
      section_code: "PROD",
      section_name: "Участок",
      operation_name: "Сверлить",
      section_icon: null,
      section_icon_color: null,
      dimensions: { length_mm: 2000 },
      dimensions_label: "2 м",
      planned_qty: 100,
      completed_qty: 20,
      issued_qty: 100,
      active_tasks_count: 1,
    },
    {
      section_id: 21,
      section_code: "PROD",
      section_name: "Участок",
      operation_name: "Сверлить",
      section_icon: null,
      section_icon_color: null,
      dimensions: null,
      dimensions_label: "—",
      planned_qty: 50,
      completed_qty: 0,
      issued_qty: 50,
      active_tasks_count: 2,
    },
  ],
};

function mountDialog() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);

  act(() => {
    root.render(
      <ProductWipStatsDialog sku="TEST-SKU" open onOpenChange={vi.fn()} />,
    );
  });

  return {
    cleanup: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ProductWipStatsDialog", () => {
  it("shows the size of each remainder and in-work task row", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(stats);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Тестовое изделие");
      });
      const text = document.body.textContent ?? "";

      // Остатки: каждая строка несёт свою подпись размера.
      expect(text).toContain("2 м");
      expect(text).toContain("3 м");
      expect(text).toContain("10");
      expect(text).toContain("4");

      // Задачи в работе: размеры из ответа, включая безразмерную строку.
      expect(text).toContain("Сверлить");
      expect(text).toContain("—");
    } finally {
      cleanup();
    }
  });

  it("shows an explicit error when the stats fail to load", async () => {
    vi.mocked(getProductWipStats).mockRejectedValue(new Error("network down"));

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("network down");
      });
    } finally {
      cleanup();
    }
  });
});
