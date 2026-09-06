// Тесты страницы «Продукты» (#152): таблица с чипами состава, карточка-модалка,
// права (operator видит без правки), сохранение состава.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  fetchAllProducts: vi.fn(),
  replaceProductComposition: vi.fn(),
}));

vi.mock("@/features/auth/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({
  toast: vi.fn(),
}));

import {
  fetchAllProducts,
  replaceProductComposition,
  type CompositionItem,
  type Product,
} from "@/shared/api/products";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { toast } from "@/shared/ui/use-toast";
import { ProductsPage } from "./ProductsPage";

const makeProduct = (overrides: Partial<Product> = {}): Product => ({
  id: 1,
  sku: "FG-001",
  code: null,
  name: "Ручка двери",
  type: "finished_good",
  unit: "pcs",
  is_active: true,
  notes: null,
  profile_type: null,
  alloy: null,
  color: "Чёрный",
  anod_type: null,
  length_mm: 1200,
  weight_per_meter: null,
  perimeter_mm: null,
  mount_width_mm: null,
  quantity_per_hanger: null,
  hanger_mode: "auto",
  cross_section: null,
  photo_thumb: null,
  photo_full: null,
  source: null,
  is_catalog_item: true,
  is_paired_profile: false,
  dimension_state: "length",
  primary_length_mm: 1200,
  skip_shot_blast: false,
  aliases: [],
  lengths_mm: [800, 1200],
  processing_flags: [],
  is_laminated: false,
  composition: [],
  ...overrides,
});

const makeComposition = (overrides: Partial<CompositionItem> = {}): CompositionItem => ({
  component_product_id: 10,
  sku: "RAW-01",
  name: "Профиль А",
  is_active: true,
  quantity: 2.5,
  unit: "pcs",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePermission).mockReturnValue({
    canEditReferences: true,
    canEditSettings: false,
  });
  vi.mocked(fetchAllProducts).mockResolvedValue([
    makeProduct({ composition: [makeComposition()] }),
    makeProduct({
      id: 2,
      sku: "FG-002",
      name: "Ручка белая",
      color: "Белый",
      lengths_mm: [],
      composition: [],
    }),
  ]);
});

describe("ProductsPage", () => {
  it("загружает только ГП с составом и рисует чипы «SKU ×N»", async () => {
    render(<ProductsPage />);

    await screen.findByTestId("product-row-FG-001");
    expect(fetchAllProducts).toHaveBeenCalledWith(
      expect.objectContaining({ type: "finished_good", include_composition: true }),
    );
    expect(screen.getByText("RAW-01 ×2.5")).toBeTruthy();
    expect(screen.getByText("800, 1200 мм")).toBeTruthy();
    expect(screen.getByText("Чёрный")).toBeTruthy();
  });

  it("открывает карточку по клику на строку: состав и характеристики", async () => {
    render(<ProductsPage />);

    fireEvent.click(await screen.findByTestId("product-row-FG-001"));

    expect(await screen.findByText("Характеристики")).toBeTruthy();
    // Состав карточки — из элемента списка
    expect(screen.getByText(/×2.5 pcs/)).toBeTruthy();
  });

  it("operator (без editReferences) не видит правку состава", async () => {
    vi.mocked(usePermission).mockReturnValue({
      canEditReferences: false,
      canEditSettings: false,
    });
    render(<ProductsPage />);

    fireEvent.click(await screen.findByTestId("product-row-FG-001"));

    await waitFor(() => expect(screen.getByText("Характеристики")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Изменить/ })).toBeNull();
  });

  it("сохраняет изменённый состав и обновляет чипы в таблице", async () => {
    const updated = [makeComposition({ quantity: 4 })];
    vi.mocked(replaceProductComposition).mockResolvedValue(updated);
    render(<ProductsPage />);

    fireEvent.click(await screen.findByTestId("product-row-FG-001"));
    fireEvent.click(await screen.findByRole("button", { name: /Изменить/ }));

    const qtyInput = screen.getByLabelText("Количество RAW-01");
    fireEvent.change(qtyInput, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(replaceProductComposition).toHaveBeenCalledWith(1, [
        { component_product_id: 10, quantity: 4, unit: "pcs" },
      ]),
    );
    await waitFor(() => expect(toast).toHaveBeenCalled());
    // Чип в таблице перерисовался новым количеством
    await waitFor(() => expect(screen.getByText("RAW-01 ×4")).toBeTruthy());
  });

  it("фильтрует по поисковому запросу (q с debounce)", async () => {
    vi.mocked(fetchAllProducts).mockClear();
    render(<ProductsPage />);

    await screen.findByTestId("product-row-FG-001");
    fireEvent.change(screen.getByTestId("products-search"), { target: { value: "ручка" } });

    await waitFor(
      () =>
        expect(fetchAllProducts).toHaveBeenLastCalledWith(
          expect.objectContaining({ q: "ручка", type: "finished_good", include_composition: true }),
        ),
      { timeout: 1500 },
    );
  });
});
