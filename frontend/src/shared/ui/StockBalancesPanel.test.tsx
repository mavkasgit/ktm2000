import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  type StockBalanceItem,
} from "@/shared/api/stock";
import { buildColumnApiParams, buildColumnFilterValues } from "@/shared/lib/columnSpecs";
import { stockBalanceColumns } from "@/shared/lib/stockBalanceColumns";
import { StockBalancesPanel } from "./StockBalancesPanel";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function item(balanceId: number, overrides: Partial<StockBalanceItem> = {}): StockBalanceItem {
  return {
    balance_id: balanceId,
    product_id: balanceId,
    sku: `SKU-${balanceId}`,
    quantity: "10",
    ...overrides,
  };
}

/**
 * Строка ответа сервера: группа эквивалентов на осях участок/качество/размер/
 * операции. Одиночная куча — группа из одного SKU, `items` из одной строки.
 */
function entry(id: number, overrides: Partial<StockBalanceEntry> = {}): StockBalanceEntry {
  const productSku = overrides.product_sku ?? `SKU-${id}`;
  const rows =
    overrides.items ?? [item(id, { product_id: overrides.product_id ?? id, sku: productSku })];
  return {
    id,
    product_id: id,
    product_sku: productSku,
    location_id: 1,
    location_name: "Участок",
    quality_state: "GOOD",
    balance_qty: "10",
    completed_operations: [],
    refreshed_at: null,
    alias_group_key: id,
    alias_group_skus: rows.map((row) => row.sku ?? `#${row.product_id}`),
    items: rows,
    ...overrides,
  };
}

function offsetsRequested(): number[] {
  return vi.mocked(getStockBalances).mock.calls.map(([params]) => params?.offset ?? -1);
}

function lastOffset(): number {
  const offsets = offsetsRequested();
  return offsets[offsets.length - 1] ?? -1;
}

function sortRequested(): string | undefined {
  const calls = vi.mocked(getStockBalances).mock.calls;
  return calls[calls.length - 1]?.[0]?.sort;
}

function renderPanel(locationIds: number[], handlers: {
  onSelectProduct?: (productId: number) => void;
  onShowHistory?: (productId: number, productSku?: string | null) => void;
} = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StockBalancesPanel
        locationIds={locationIds}
        onSelectProduct={handlers.onSelectProduct ?? vi.fn()}
        onShowHistory={handlers.onShowHistory ?? vi.fn()}
      />
    </QueryClientProvider>,
  );
}

/** Панель вкладки участка: серверный дефолт — количество по убыванию (#346). */
function renderSectionPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StockBalancesPanel
        locationId={1}
        defaultSort="quantity:desc"
        onSelectProduct={vi.fn()}
        onShowHistory={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

function articleOrder(): string[] {
  return [...document.querySelectorAll("tbody tr")]
    .map((row) => {
      const cell = row.querySelector("td");
      const article = cell?.querySelector("span") ?? cell;
      return article?.textContent?.trim() ?? "";
    })
    .filter(Boolean);
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

describe("StockBalancesPanel: группы эквивалентов приходят с сервера", () => {
  /** Куча A+B: сумма 1555, две фактические SKU-строки. */
  const pair = entry(1, {
    product_id: 1,
    product_sku: "SKU-A",
    balance_qty: "1555",
    alias_group_key: 1,
    alias_group_skus: ["SKU-A", "SKU-B"],
    items: [
      item(1, { product_id: 1, sku: "SKU-A", quantity: "1159" }),
      item(2, { product_id: 2, sku: "SKU-B", quantity: "396" }),
    ],
  });

  const solo = entry(3, {
    product_sku: "SKU-SOLO",
    balance_qty: "10",
    alias_group_skus: ["SKU-SOLO"],
    items: [item(3, { sku: "SKU-SOLO", quantity: "10" })],
  });

  beforeEach(() => {
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: [pair, solo],
      total: 2,
      limit: 50,
      offset: 0,
    });
  });

  it("рисует группу одной строкой-итогом, а одиночный SKU — обычной строкой", async () => {
    renderPanel([1]);
    const summary = await screen.findByText("SKU-A, SKU-B (эквиваленты)");

    // Итог: серверная сумма кучи и число фактических SKU.
    expect(summary.closest("tr")?.textContent).toContain("1555");
    expect(summary.closest("tr")?.textContent).toContain("×2");
    // Раскрытие свёрнуто: строк кучи не видно.
    expect(screen.queryByText("1159")).toBeNull();
    expect(screen.queryByText("396")).toBeNull();

    // Одиночная куча — без шапки-раскрытия и без пометки «эквиваленты».
    const soloRow = screen.getByText("SKU-SOLO").closest("tr");
    expect(soloRow?.textContent).toContain("10");
    expect(screen.getAllByText(/эквиваленты/)).toHaveLength(1);
  });

  it("раскрывает группу до фактических SKU с их количествами", async () => {
    renderPanel([1]);
    fireEvent.click(await screen.findByText("SKU-A, SKU-B (эквиваленты)"));

    await waitFor(() => expect(screen.getByText("1159")).toBeTruthy());
    expect(screen.getByText("396")).toBeTruthy();
    expect(screen.getByText("SKU-A")).toBeTruthy();
    expect(screen.getByText("SKU-B")).toBeTruthy();
  });

  it("«История» и детализация раскрытой SKU-строки — по её product_id", async () => {
    const onSelectProduct = vi.fn();
    const onShowHistory = vi.fn();
    renderPanel([1], { onSelectProduct, onShowHistory });
    fireEvent.click(await screen.findByText("SKU-A, SKU-B (эквиваленты)"));
    await waitFor(() => expect(screen.getByText("SKU-B")).toBeTruthy());

    const itemRow = screen.getByText("SKU-B").closest("tr")!;
    fireEvent.click(within(itemRow).getByText("История"));
    expect(onShowHistory).toHaveBeenCalledWith(2, "SKU-B");

    fireEvent.click(screen.getByText("SKU-B"));
    expect(onSelectProduct).toHaveBeenCalledWith(2);
  });

  it("куча из одного SKU без раскрытия показывает артикул-представитель", async () => {
    // Группа эквивалентов из двух артикулов, но на этих осях лежит только A:
    // раскрывать нечего, и шапки «(эквиваленты)» быть не должно.
    const single = entry(5, {
      product_id: 5,
      product_sku: "SKU-ONLY-A",
      balance_qty: "7",
      alias_group_skus: ["SKU-ONLY-A", "SKU-ONLY-B"],
      items: [item(5, { product_id: 5, sku: "SKU-ONLY-A", quantity: "7" })],
    });
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: [single],
      total: 1,
      limit: 50,
      offset: 0,
    });

    renderPanel([1]);
    await screen.findByText("SKU-ONLY-A");
    expect(screen.queryByText(/эквиваленты/)).toBeNull();
    expect(screen.queryByText("×1")).toBeNull();
  });

  it("список фильтра «Артикул» — отдельные SKU группы, а не склеенная подпись", async () => {
    const rows = [pair, solo];
    expect(buildColumnFilterValues(rows, stockBalanceColumns).sku).toEqual([
      "SKU-A",
      "SKU-B",
      "SKU-SOLO",
    ]);
    // В запрос уходит член группы: сервер ищет `?sku=` по строкам кучи.
    expect(buildColumnApiParams({ sku: new Set(["SKU-B"]) }, {}, stockBalanceColumns)).toEqual({
      sku: "SKU-B",
    });
  });
});

describe("StockBalancesPanel: порядок по умолчанию", () => {
  /** Сервер отдал порядок, который клиент НЕ должен переставлять. */
  const serverRows: StockBalanceEntry[] = [
    entry(1, { product_sku: "SKU-BIG", balance_qty: "396" }),
    entry(2, { product_sku: "SKU-SMALL", balance_qty: "10" }),
    entry(3, { product_sku: "SKU-MID", balance_qty: "800" }),
  ];

  beforeEach(() => {
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: serverRows,
      total: 3,
      limit: 50,
      offset: 0,
    });
  });

  it("строки идут в серверном порядке: клиент группы не сортирует", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-BIG");

    // Количества намеренно не по убыванию: клиентская пересортировка
    // переставила бы строки и разошлась бы с `total`/страницами сервера.
    expect(articleOrder()).toEqual(["SKU-BIG", "SKU-SMALL", "SKU-MID"]);
    expect(sortRequested()).toBe("sku:asc");
  });

  it("панель участка просит серверные остатки по количеству убыв.", async () => {
    renderSectionPanel();
    await screen.findByText("SKU-BIG");

    expect(sortRequested()).toBe("quantity:desc");
  });

  it("без переданного дефолта панель остаётся при артикуле по возрастанию", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-BIG");

    expect(sortRequested()).toBe("sku:asc");
  });

  it("ручная сортировка по колонке уходит на сервер и не переставляет строки на клиенте", async () => {
    renderSectionPanel();
    await screen.findByText("SKU-BIG");

    const button = document.querySelector<HTMLButtonElement>('button[data-sort-field="quantity"]');
    expect(button).toBeTruthy();
    fireEvent.click(button!);
    await waitFor(() => expect(sortRequested()).toBe("quantity:desc"));

    // Порядок берётся из ответа сервера, своя раскладка по сумме групп
    // больше не накладывается.
    expect(articleOrder()).toEqual(["SKU-BIG", "SKU-SMALL", "SKU-MID"]);
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
        entry(1, { product_sku: "SKU-SOLO", completed_operations: [] }),
        entry(2, {
          product_sku: "SKU-MIX",
          completed_operations: ["op_drill"],
          completed_stages: [stage("Сверловка")],
          alias_group_skus: ["SKU-MIX", "SKU-MIX-2"],
          items: [
            item(2, { sku: "SKU-MIX", quantity: "4" }),
            item(3, { sku: "SKU-MIX-2", quantity: "6" }),
          ],
          balance_qty: "10",
        }),
        entry(4, { product_sku: "SKU-NUL", completed_operations: null }),
      ],
      total: 3,
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

  it("итог группы печатает прочерк для пустого состояния оси", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-NUL");

    expect(operationsCell("SKU-NUL").textContent).toBe("—");
  });

  it("итог группы называет операции, когда они есть", async () => {
    renderPanel([1]);
    await screen.findByText("SKU-MIX, SKU-MIX-2 (эквиваленты)");

    const text = operationsCell("SKU-MIX, SKU-MIX-2 (эквиваленты)").textContent ?? "";
    expect(text).toContain("Сверловка");
    expect(text).not.toContain("—");
    expect(text).not.toContain(OPERATIONS_EMPTY_LABEL);
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
