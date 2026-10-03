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

  it("порядок источников — по убыванию операций, а не по количеству", () => {
    // #314: предвыбор по completed_operations DESC. Подготовительный склад
    // (2 операции) должен идти ВЫШЕ сырья (0 операций), хотя на сырье лежит
    // больше: сортировка по количеству предлагала бы оператору отстающий
    // материал как первый выбор.
    const rows = groupBalances([
      balance({ id: 1, location_name: "Склад сырья", completed_operations: [], balance_qty: "500" }),
      balance({
        id: 2,
        location_name: "Склад подготовки",
        completed_operations: ["PRESS", "CUT"],
        balance_qty: "5",
      }),
    ]);

    expect(rows.map((row) => row.location)).toEqual(["Склад подготовки", "Склад сырья"]);
    expect(rows[0].opsCount).toBe(2);
    expect(rows[1].opsCount).toBe(0);
  });

  it("при равном числе операций порядок детерминирован", () => {
    // Порядок не должен зависеть от того, в каком порядке пришли строки:
    // предвыбор оператора обязан быть воспроизводимым.
    const input = [
      balance({ id: 1, location_name: "Б", completed_operations: ["SAW"] }),
      balance({ id: 2, location_name: "А", completed_operations: ["PRESS"] }),
    ];
    const forward = groupBalances(input).map((row) => row.location);
    const backward = groupBalances([...input].reverse()).map((row) => row.location);

    expect(forward).toEqual(["А", "Б"]);
    expect(backward).toEqual(forward);
  });

  it("незафиксированное состояние операций считается нулём и уходит вниз", () => {
    const rows = groupBalances([
      balance({ id: 1, location_name: "Сырьё", completed_operations: null }),
      balance({ id: 2, location_name: "Пресс", completed_operations: ["PRESS"] }),
    ]);

    expect(rows.map((row) => row.location)).toEqual(["Пресс", "Сырьё"]);
    expect(rows[1].opsCount).toBe(0);
  });

  it("строка несёт id остатка — по нему выбор уходит в take-to-work", () => {
    // Без `balanceId` выбор оператора нечем адресовать на бэкенде: ключ
    // остатка — это его id (ADR-0055, пять осей).
    const rows = groupBalances([balance({ id: 77, completed_operations: ["SAW"] })]);

    expect(rows[0].balanceId).toBe(77);
  });
});
