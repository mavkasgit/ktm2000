import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Мокаем слой API: список групп диалог читает из существующего эндпоинта
// балансов, а отправка идёт через postStockAdjustment — оба должны быть
// под наблюдением теста.
vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));
vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  listProducts: vi.fn(),
}));
vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getStockBalances: vi.fn(),
  postStockAdjustment: vi.fn(),
}));

import { listSections } from "@/shared/api/sections";
import type { Section } from "@/shared/api/sections";
import { listProducts } from "@/shared/api/products";
import type { Product } from "@/shared/api/products";
import { getStockBalances, postStockAdjustment } from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { StockAdjustmentDialog } from "./StockAdjustmentDialog";

const makeSection = (overrides: Partial<Section>): Section => ({
  id: 7,
  code: "STOCK-1",
  name: "Склад",
  description: null,
  sort_order: 0,
  is_active: true,
  type: "raw_stock",
  icon: null,
  icon_color: null,
  ...overrides,
});

const makeProduct = (overrides: Partial<Product>): Product =>
  ({
    id: 1,
    sku: "PR-1",
    name: "Профиль 40x40",
    ...overrides,
  }) as Product;

const makeBalance = (
  overrides: Partial<StockBalanceEntry> & Pick<StockBalanceEntry, "id">,
): StockBalanceEntry => ({
  product_id: 1,
  location_id: 7,
  quality_state: "GOOD",
  balance_qty: "10",
  dimensions: null,
  dimensions_label: "—",
  completed_operations: null,
  completed_stages: [],
  refreshed_at: null,
  ...overrides,
  // Обязательные поля: spread из Partial мог обнулить их до undefined.
  product_sku: overrides.product_sku ?? null,
  location_name: overrides.location_name ?? null,
});

/** Группы одного артикула: «не зафиксировано», именованная и «без операций». */
const BALANCES: StockBalanceEntry[] = [
  makeBalance({ id: 11, balance_qty: "100" }),
  makeBalance({
    id: 12,
    balance_qty: "40",
    completed_operations: ["SAW"],
    completed_stages: [
      {
        sequence: 1,
        section_code: "SAW-S",
        section_name: "Пила",
        operation_code: "SAW",
        operation_name: "Резка по пиле",
        is_significant: true,
      },
    ],
  }),
  makeBalance({ id: 13, balance_qty: "7", completed_operations: [] }),
];

const renderDialog = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <StockAdjustmentDialog open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
};

/** Выбор в Radix Select: триггер открывается по click, пункт — по pointerup. */
const openSelect = async (triggerText: string) => {
  const trigger = (await screen.findByText(triggerText)).closest(
    "button",
  ) as HTMLElement;
  fireEvent.click(trigger);
};

const chooseOption = async (name: RegExp | string) => {
  const option = await screen.findByRole("option", { name });
  fireEvent.pointerUp(option);
  fireEvent.click(option);
};

const selectProductAndSection = async () => {
  fireEvent.click(await screen.findByText("PR-1"));
  await openSelect("Выберите участок");
  await chooseOption(/Склад \(STOCK-1\)/);
};

const setQuantity = (value: string) => {
  fireEvent.change(screen.getByPlaceholderText("Введите количество..."), {
    target: { value },
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  // Radix Select обращается к pointer-capture API, которого нет в happy-dom.
  window.HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
  window.HTMLElement.prototype.setPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();

  vi.mocked(listSections).mockResolvedValue([makeSection({})]);
  vi.mocked(listProducts).mockResolvedValue([makeProduct({})]);
  vi.mocked(getStockBalances).mockResolvedValue({
    balances: BALANCES,
    total: BALANCES.length,
    limit: 500,
    offset: 0,
  });
  vi.mocked(postStockAdjustment).mockResolvedValue({
    id: 1,
    reason: "manual_in",
    quantity: "5",
    created_at: null,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("StockAdjustmentDialog: группы операций (ADR-0055)", () => {
  it("показывает группы артикула с количеством и подписью, пустые состояния различимы", async () => {
    renderDialog();
    await selectProductAndSection();

    await waitFor(() =>
      expect(vi.mocked(getStockBalances).mock.calls[0][0]).toMatchObject({
        product_id: 1,
        location_id: 7,
        quality_state: "GOOD",
      }),
    );

    await screen.findByRole("radiogroup", { name: "Группа операций" });
    const text = document.body.textContent ?? "";
    // Подписи трёх групп: не зафиксировано / именованная / без операций.
    expect(text).toContain("не зафиксировано");
    expect(text).toContain("без операций");
    expect(text).toContain("Резка по пиле");
    // Количество каждой группы.
    expect(text).toContain("100 шт");
    expect(text).toContain("40 шт");
    expect(text).toContain("7 шт");
    // Для прихода синтетических пунктов два — «не зафиксировано» и «без
    // операций» (это выбор: серверные подписи). Строки остатка печатают
    // прочерк и слов не дублируют.
    expect(screen.getAllByRole("radio")).toHaveLength(BALANCES.length + 2);
  });

  it("приход без выбора группы уходит с completed_operations: null", async () => {
    renderDialog();
    await selectProductAndSection();
    setQuantity("5");

    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    await waitFor(() =>
      expect(postStockAdjustment).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(postStockAdjustment).mock.calls[0][0]).toMatchObject({
      product_id: 1,
      location_id: 7,
      reason: "manual_in",
      completed_operations: null,
    });
  });

  it("расход без выбранной группы отклоняется локально, запрос не уходит", async () => {
    renderDialog();
    await selectProductAndSection();
    await openSelect("Приход (manual_in)");
    await chooseOption(/Расход \(manual_out\)/);
    setQuantity("10");

    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    expect(
      await screen.findByText("Для списания выберите группу операций"),
    ).toBeTruthy();
    expect(postStockAdjustment).not.toHaveBeenCalled();
  });

  it("расход из выбранной группы передаёт её признак в payload", async () => {
    renderDialog();
    await selectProductAndSection();
    await openSelect("Приход (manual_in)");
    await chooseOption(/Расход \(manual_out\)/);
    setQuantity("10");

    fireEvent.click(screen.getByRole("radio", { name: /Резка по пиле/ }));
    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    await waitFor(() =>
      expect(postStockAdjustment).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(postStockAdjustment).mock.calls[0][0]).toMatchObject({
      reason: "manual_out",
      quantity: 10,
      completed_operations: ["SAW"],
    });
  });

  it("приход в группу «без операций» передаёт пустой список", async () => {
    renderDialog();
    await selectProductAndSection();
    setQuantity("5");

    fireEvent.click(screen.getByTestId("stock-adjustment-empty-ops"));
    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    await waitFor(() =>
      expect(postStockAdjustment).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(postStockAdjustment).mock.calls[0][0]).toMatchObject({
      reason: "manual_in",
      completed_operations: [],
    });
  });

  it("«без операций» доступна и когда строк остатка нет", async () => {
    // Свежий участок: строк этого артикула нет вовсе. Раньше радиогруппа не
    // рендерилась совсем, и приход можно было завести только в NULL-группу, из
    // которой маршрут материал не берёт (тикет #266).
    vi.mocked(getStockBalances).mockResolvedValue({
      balances: [],
      total: 0,
      limit: 500,
      offset: 0,
    });
    renderDialog();
    await selectProductAndSection();
    setQuantity("5");

    fireEvent.click(await screen.findByTestId("stock-adjustment-empty-ops"));
    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    await waitFor(() =>
      expect(postStockAdjustment).toHaveBeenCalledTimes(1),
    );
    expect(vi.mocked(postStockAdjustment).mock.calls[0][0]).toMatchObject({
      reason: "manual_in",
      completed_operations: [],
    });
  });

  it("переключение на расход снимает «без операций»", async () => {
    renderDialog();
    await selectProductAndSection();
    setQuantity("5");
    fireEvent.click(screen.getByTestId("stock-adjustment-empty-ops"));

    await openSelect("Приход (manual_in)");
    await chooseOption(/Расход \(manual_out\)/);
    fireEvent.click(screen.getByRole("button", { name: "Выполнить" }));

    // Расход без выбранной строки остатка отклоняется локально: группа для
    // списания обязательна, и выбор прихода туда не переезжает.
    expect(await screen.findByText("Для списания выберите группу операций")).toBeTruthy();
    expect(postStockAdjustment).not.toHaveBeenCalled();
  });
});
