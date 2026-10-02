import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getStockBalances: vi.fn(),
}));

import { getStockBalances, type StockBalanceEntry } from "@/shared/api/stock";
import { StockBalancesPanel } from "./StockBalancesPanel";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const entry = (id: number): StockBalanceEntry => ({
  id,
  product_id: id,
  product_sku: `SKU-${id}`,
  location_id: 1,
  location_name: "Участок",
  quality_state: "GOOD",
  balance_qty: "10",
  completed_operations: [],
  refreshed_at: null,
});

function offsetsRequested(): number[] {
  return vi.mocked(getStockBalances).mock.calls.map(([params]) => params?.offset ?? -1);
}

function lastOffset(): number {
  const offsets = offsetsRequested();
  return offsets[offsets.length - 1] ?? -1;
}

function renderPanel(locationIds: number[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StockBalancesPanel
        locationIds={locationIds}
        onSelectProduct={vi.fn()}
        onShowHistory={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getStockBalances).mockResolvedValue({
    balances: Array.from({ length: 50 }, (_, i) => entry(i + 1)),
    total: 120,
    limit: 50,
    offset: 0,
  });
});

describe("StockBalancesPanel: страница и набор складов", () => {
  it("не возвращает на первую страницу, когда родитель отдал новый массив с тем же набором", async () => {
    const { rerender } = renderPanel([1, 2]);
    await screen.findByText("SKU-1");

    fireEvent.click(screen.getByLabelText("Следующая страница"));
    await waitFor(() => expect(offsetsRequested()).toContain(50));

    // Новый массив — тот же набор складов: refetch списка складов у родителя
    // пересоздаёт ссылку, но фильтр не менялся (ADR-0060 п.4).
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    rerender(
      <QueryClientProvider client={client}>
        <StockBalancesPanel locationIds={[2, 1]} onSelectProduct={vi.fn()} onShowHistory={vi.fn()} />
      </QueryClientProvider>,
    );
    await delay(50);

    expect(lastOffset()).toBe(50);
  });
});

describe("StockBalancesPanel: группы по артикулу", () => {
  const groupRows = (): StockBalanceEntry[] => [
    { ...entry(1), product_sku: "SKU-G", balance_qty: "1159" },
    { ...entry(2), product_sku: "SKU-SOLO", balance_qty: "10" },
    {
      ...entry(3),
      product_sku: "SKU-G",
      balance_qty: "396",
      quality_state: "SCRAP",
      completed_operations: [],
    },
  ];

  beforeEach(() => {
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: groupRows(),
      total: 3,
      limit: 50,
      offset: 0,
    });
  });

  it("сворачивает артикул с несколькими строками в итог и раскрывает его по клику", async () => {
    renderPanel([1]);
    const summary = await screen.findByText("SKU-G");

    // Итог: сумма количеств строк артикула и их число.
    expect(summary.closest("tr")?.textContent).toContain("1555");
    expect(summary.closest("tr")?.textContent).toContain("×2");
    // Раскладка качества: свёрнутая группа не прячет брак.
    expect(summary.closest("tr")?.textContent).toContain("Годный 1 · Брак 1");
    // …и называет его цветом: в свёрнутой строке это единственный признак брака.
    const qualityCell = Array.from(summary.closest("tr")!.querySelectorAll("td")).find((cell) =>
      cell.textContent?.includes("Брак"),
    );
    expect(qualityCell?.className).toContain("text-red-600");
    // Строки артикула спрятаны, одиночный артикул — как был.
    expect(screen.queryByText("1159")).toBeNull();
    expect(screen.getByText("SKU-SOLO")).toBeTruthy();

    fireEvent.click(summary);
    await waitFor(() => expect(screen.getByText("1159")).toBeTruthy());
    expect(screen.getByText("396")).toBeTruthy();
  });
});
