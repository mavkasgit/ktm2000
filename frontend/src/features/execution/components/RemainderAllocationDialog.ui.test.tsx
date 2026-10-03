// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import type { StockBalanceEntry } from "@/shared/api/stock";

// Диалог тянет остатки через API-слой: мокаем оба вызова, которые он делает.
vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getProductStockBalances: vi.fn(),
}));

import { getProductStockBalances } from "@/shared/api/stock";
import { RemainderAllocationDialog } from "./RemainderAllocationDialog";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/shared/api/products", () => ({
  listProducts: vi.fn(async () => [{ id: 1, sku: "SKU-1", name: "Тест" }]),
}));

const balance = (over: Partial<StockBalanceEntry>): StockBalanceEntry => ({
  id: 1,
  product_id: 1,
  product_sku: "SKU-1",
  location_id: 1,
  location_name: "Склад сырья",
  quality_state: "GOOD",
  balance_qty: "10",
  completed_operations: [],
  refreshed_at: null,
  ...over,
});

const BALANCES: StockBalanceEntry[] = [
  balance({ id: 11, location_name: "Склад сырья", completed_operations: [], balance_qty: "500" }),
  balance({
    id: 22,
    location_name: "Склад подготовки",
    completed_operations: ["PRESS"],
    balance_qty: "40",
  }),
];

let container: HTMLDivElement;
let root: Root;

async function mount(onConfirm: (a: boolean, alloc: unknown) => void) {
  await act(async () => {
    root.render(
      <RemainderAllocationDialog
        open
        onOpenChange={() => {}}
        positionId={1}
        positionSku="SKU-1"
        positionName="Тест"
        releaseQuantity={40}
        onConfirm={onConfirm as never}
        pending={false}
      />,
    );
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  vi.mocked(getProductStockBalances).mockResolvedValue(BALANCES);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

describe("RemainderAllocationDialog: выбор источника (#314)", () => {
  it("предвыбирает остаток с наибольшим числом операций", async () => {
    const onConfirm = vi.fn();
    await mount(onConfirm);

    // Запрос уходит с порядком кандидатов выдачи, а не с порядком ключа.
    expect(getProductStockBalances).toHaveBeenCalledWith(1, undefined, "operations");

    const checked = [...document.querySelectorAll<HTMLInputElement>(
      'input[name="source-balance"]',
    )].filter((el) => el.checked);
    expect(checked).toHaveLength(1);
    expect(checked[0].getAttribute("aria-label")).toContain("Склад подготовки");
  });

  it("уходит в onConfirm выбранный остаток, а не предвыбранный по умолчанию", async () => {
    const onConfirm = vi.fn();
    await mount(onConfirm);

    const raw = document.querySelector<HTMLInputElement>(
      'input[aria-label="Источник: Склад сырья, операций 0"]',
    );
    expect(raw).not.toBeNull();
    await act(async () => {
      raw!.click();
    });

    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Запустить в работу"),
    );
    expect(button).toBeDefined();
    await act(async () => {
      button!.click();
    });

    expect(onConfirm).toHaveBeenCalledWith(false, [{ balance_id: 11, quantity: 40 }]);
  });

  it("количество источника не превышает остаток на нём", async () => {
    const onConfirm = vi.fn();
    await mount(onConfirm);

    // Сырьё — 500 шт. при плане 40: отдать 500 нельзя, материал возьмут
    // столько, сколько нужно на запуск. Выбор сделан явно, иначе предвыбор
    // был бы подсветкой, а не решением оператора.
    const raw = document.querySelector<HTMLInputElement>(
      'input[aria-label="Источник: Склад сырья, операций 0"]',
    );
    expect(raw).not.toBeNull();
    await act(async () => {
      raw!.click();
    });

    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Запустить в работу"),
    );
    await act(async () => {
      button!.click();
    });
    expect(onConfirm).toHaveBeenCalledWith(false, [{ balance_id: 11, quantity: 40 }]);
  });

  it("предвыбор без явного выбора источника не выдаёт материал заранее", async () => {
    const onConfirm = vi.fn();
    await mount(onConfirm);

    // Решение владельца: предвыбор — подсветка первой строки порядка, а не
    // команда на выдачу. Без явного выбора запускаем без источника, материал
    // уходит обычной передачей — иначе ломается двухшаговый ритуал передачи.
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Запустить в работу"),
    );
    expect(button).toBeDefined();
    await act(async () => {
      button!.click();
    });
    expect(onConfirm).toHaveBeenCalledWith(false, null);
  });
});
