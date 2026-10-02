import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getStockBalances: vi.fn(),
}));

import {
  getStockBalances,
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
  type ImportOperationStep,
  type StockBalanceEntry,
} from "@/shared/api/stock";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { stockBalanceColumns } from "@/shared/lib/stockBalanceColumns";
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

describe("StockBalancesPanel: подписи операций", () => {
  /** Этап оси операций в формате справочника. */
  const stage = (name: string): ImportOperationStep => ({
    sequence: 10,
    section_code: "SEC",
    section_name: "Участок",
    operation_code: "OP_CODE",
    operation_name: name,
    is_significant: true,
  });

  /** Ячейка «Операций» строки с данным артикулом (колонка четвёртая). */
  function operationsCell(sku: string): HTMLElement {
    const row = screen.getByText(sku).closest("tr");
    expect(row).toBeTruthy();
    return Array.from(row!.querySelectorAll("td"))[3];
  }

  beforeEach(() => {
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: [
        { ...entry(1), product_sku: "SKU-SOLO", completed_operations: [] },
        { ...entry(2), product_sku: "SKU-EMPTY", completed_operations: [] },
        { ...entry(3), product_sku: "SKU-EMPTY", completed_operations: [] },
        { ...entry(4), product_sku: "SKU-MIX", completed_operations: [] },
        { ...entry(5), product_sku: "SKU-MIX", completed_operations: ["op_drill"], completed_stages: [stage("Сверловка")] },
        { ...entry(6), product_sku: "SKU-NUL", completed_operations: null },
      ],
      total: 6,
      limit: 50,
      offset: 0,
    });
  });

  it("строка без операций печатает прочерк, а не «без операций»", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-SOLO");

    expect(operationsCell("SKU-SOLO").textContent).toBe("—");
    expect(screen.queryByText(OPERATIONS_EMPTY_LABEL)).toBeNull();
  });

  it("итог группы из одних пустых строк — прочерк", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-EMPTY");

    expect(operationsCell("SKU-EMPTY").textContent).toBe("—");
  });

  it("итог группы с другими операциями не несёт прочерка", async () => {
    renderPanel([1]);
    const summary = await screen.findByText("SKU-MIX");

    const text = operationsCell("SKU-MIX").textContent ?? "";
    expect(text).toContain("Сверловка");
    expect(text).not.toContain("—");
    expect(text).not.toContain(OPERATIONS_EMPTY_LABEL);
    expect(summary).toBeTruthy();
  });

  it("ячейка печатает прочерк, а список фильтра — серверные подписи", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-SOLO");

    // Оба пустых состояния в ячейке — прочерк.
    expect(operationsCell("SKU-SOLO").textContent).toBe("—");
    expect(operationsCell("SKU-NUL").textContent).toBe("—");

    // Список фильтра — подписи, которые понимает сервер: двумя прочерками
    // выбрать разные группы нельзя, а `_balance_operations_filter` прочерка
    // не знает (ADR-0055 п.5).
    fireEvent.click(screen.getByText("Операции"));
    expect(await screen.findByText(OPERATIONS_EMPTY_LABEL)).toBeTruthy();
    expect(screen.getByText(OPERATIONS_NOT_RECORDED_LABEL)).toBeTruthy();

    expect(
      buildColumnApiParams(
        { operations: new Set([OPERATIONS_NOT_RECORDED_LABEL]) },
        {},
        stockBalanceColumns,
      ),
    ).toEqual({ operations: OPERATIONS_NOT_RECORDED_LABEL });
    expect(
      buildColumnApiParams(
        { operations: new Set([OPERATIONS_EMPTY_LABEL]) },
        {},
        stockBalanceColumns,
      ),
    ).toEqual({ operations: OPERATIONS_EMPTY_LABEL });
  });
});
