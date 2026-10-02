import { describe, expect, it } from "vitest";

import type { StockBalanceEntry } from "@/shared/api/stock";

import { groupBalances } from "./RemainderAllocationDialog";

const balance = (overrides: Partial<StockBalanceEntry>): StockBalanceEntry => ({
  id: 1,
  product_id: 1,
  product_sku: "SKU-1",
  location_id: 1,
  location_name: "Участок",
  quality_state: "GOOD",
  balance_qty: "10",
  completed_operations: [],
  refreshed_at: null,
  ...overrides,
});

describe("RemainderAllocationDialog: строки выдачи", () => {
  it("`null` и `[]` дают две строки с одной подписью, а не одну", () => {
    // ADR-0055: прочерк в ячейке один у обоих пустых состояний, но списание
    // идёт по операциям — склеить их значило бы обещать материал, которого
    // списать нельзя.
    const rows = groupBalances([
      balance({ id: 1, completed_operations: null }),
      balance({ id: 2, completed_operations: [] }),
    ]);

    expect(rows).toHaveLength(2);
    expect(rows.every((row) => row.ops === "—")).toBe(true);
    expect(new Set(rows.map((row) => row.opsKey))).toEqual(
      new Set(["не зафиксировано", "без операций"]),
    );
  });

  it("одинаковые операции складываются в одну строку", () => {
    const rows = groupBalances([
      balance({ id: 1, completed_operations: ["SAW"], balance_qty: "7" }),
      balance({ id: 2, completed_operations: ["SAW"], balance_qty: "3" }),
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0].qty).toBe(10);
  });

  it("разный габарит не смешивается, даже когда операции одинаковы", () => {
    const rows = groupBalances([
      balance({ id: 1, dimensions: { length_mm: 2700 } }),
      balance({ id: 2, dimensions: { length_mm: 1800 } }),
    ]);

    expect(rows).toHaveLength(2);
  });
});
