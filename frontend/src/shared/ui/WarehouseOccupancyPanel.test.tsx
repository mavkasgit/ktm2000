import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getWarehouseOccupancy: vi.fn(),
}));

import {
  getWarehouseOccupancy,
  type WarehouseOccupancyResponse,
} from "@/shared/api/stock";
import { WarehouseOccupancyPanel } from "./WarehouseOccupancyPanel";

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WarehouseOccupancyPanel />
    </QueryClientProvider>,
  );
}

function payload(
  overrides: Partial<WarehouseOccupancyResponse> = {},
): WarehouseOccupancyResponse {
  return {
    warehouses: [
      {
        warehouse_id: 1,
        warehouse: "Склад сырья",
        warehouse_code: "RAW_STOCK",
        in_work: 50,
        free: 70,
        total: 120,
      },
      {
        warehouse_id: 2,
        warehouse: "Склад подготовки",
        warehouse_code: "PREP_STOCK",
        in_work: 0,
        free: 30,
        total: 30,
      },
      {
        warehouse_id: 3,
        warehouse: "Пустой склад",
        warehouse_code: "EMPTY_STOCK",
        in_work: 0,
        free: 0,
        total: 0,
      },
    ],
    totals: { in_work: 50, free: 100, total: 150 },
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getWarehouseOccupancy).mockResolvedValue(payload());
});

describe("WarehouseOccupancyPanel: занятость по складам (#350)", () => {
  it("показывает по каждому складу три числа в штуках и общий итог", async () => {
    renderPanel();

    const raw = (await screen.findByText("Склад сырья")).closest("li");
    expect(raw).toBeTruthy();
    expect(raw?.textContent).toContain("50 шт");
    expect(raw?.textContent).toContain("70 шт");
    expect(raw?.textContent).toContain("120 шт");

    const prep = screen.getByText("Склад подготовки").closest("li");
    expect(prep?.textContent).toContain("0 шт");
    expect(prep?.textContent).toContain("30 шт");

    const totals = screen.getByText("Итого по складам").closest("li");
    expect(totals?.textContent).toContain("50 шт");
    expect(totals?.textContent).toContain("100 шт");
    expect(totals?.textContent).toContain("150 шт");
  });

  it("пустой склад остаётся нулевой строкой, а не исчезает", async () => {
    renderPanel();

    const empty = (await screen.findByText("Пустой склад")).closest("li");
    expect(empty).toBeTruthy();
    expect(empty?.textContent).toContain("0 шт");
  });

  it("без складов объясняет пустоту, а не рисует пустую сетку", async () => {
    vi.mocked(getWarehouseOccupancy).mockResolvedValue({
      warehouses: [],
      totals: { in_work: 0, free: 0, total: 0 },
    });

    renderPanel();

    expect(await screen.findByText(/Складов-хранилищ нет/)).toBeTruthy();
    expect(screen.queryByText("Итого по складам")).toBeNull();
  });

  it("ошибка запроса показывается текстом, а не нулями", async () => {
    vi.mocked(getWarehouseOccupancy).mockRejectedValue(new Error("boom"));

    renderPanel();

    expect(
      await screen.findByText("Не удалось загрузить занятость складов"),
    ).toBeTruthy();
  });
});
