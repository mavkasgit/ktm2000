// Карточка артикула: норма подвеса под длиной, которой нет в реестре (ADR-0047, #217).
// Поведение формы: предупреждение видно, снятие значения уходит в PATCH явным null —
// только так сервер снимает блокировку карточки.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/references/api", () => ({
  listDimensionTypes: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  listProductPairs: vi.fn().mockResolvedValue([]),
  searchProductsForAlias: vi.fn().mockResolvedValue([]),
  uploadProductPhoto: vi.fn(),
}));

vi.mock("@/shared/api/hangerCalc", () => ({
  calcHanger: vi.fn().mockResolvedValue({ results: [] }),
  calcPairedHanger: vi.fn().mockResolvedValue({ results: [] }),
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Product, QuantityPerHangerDict } from "@/shared/api/products";
import { CatalogForm } from "./CatalogForm";

const makeProduct = (overrides: Partial<Product> = {}): Product => ({
  id: 190,
  sku: "ЮП-3473",
  code: null,
  name: "Перила",
  type: "component",
  unit: "pcs",
  is_active: true,
  notes: null,
  profile_type: null,
  alloy: null,
  color: null,
  anod_type: null,
  weight_per_meter: null,
  perimeter_mm: null,
  mount_width_mm: null,
  quantity_per_hanger: null,
  hanger_mode: "manual",
  cross_section: null,
  photo_thumb: null,
  photo_full: null,
  source: null,
  is_catalog_item: false,
  is_paired_profile: false,
  dimension_state: "length",
  skip_shot_blast: false,
  aliases: [],
  lengths: [{ length_mm: 2700, raw_length_mm: 2750, is_primary: true }],
  processing_flags: [],
  is_laminated: false,
  ...overrides,
});

const orphanNorms: QuantityPerHangerDict = {
  "2750": { auto: null, manual: 62 },
};

const renderForm = (product: Product, onSave = vi.fn()) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <CatalogForm
          product={product}
          mode="edit"
          onSave={onSave}
          onCancel={() => {}}
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { onSave, ...view };
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CatalogForm: норма-сирота", () => {
  it("предупреждает, что норма не применима ни к одной длине", async () => {
    renderForm(makeProduct({ quantity_per_hanger: orphanNorms }));

    expect(
      await screen.findByText(/не применима ни к одной длине/),
    ).toBeTruthy();
    expect(screen.getByText(/2750 мм/)).toBeTruthy();
  });

  it("удаление значения уходит в PATCH явным null — блокировка снимается", async () => {
    const { onSave } = renderForm(
      makeProduct({ quantity_per_hanger: { ...orphanNorms, "2700": { auto: null, manual: 40 } } }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Удалить норму/ }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          quantity_per_hanger: {
            "2700": { auto: null, manual: 40 },
            "2750": { auto: null, manual: null },
          },
        }),
        "edit",
      ),
    );
  });

  it("свежий ключ в реестре снимает предупреждение", async () => {
    renderForm(
      makeProduct({
        quantity_per_hanger: orphanNorms,
        lengths: [
          { length_mm: 2700, raw_length_mm: 2750, is_primary: true },
          { length_mm: 2750, raw_length_mm: null, is_primary: false },
        ],
      }),
    );

    await waitFor(() => expect(screen.queryByText(/не применима ни к одной длине/)).toBeNull());
  });

  it("добавление длины не стирает норму-сироту — её снимает оператор", async () => {
    const { onSave } = renderForm(
      makeProduct({ quantity_per_hanger: { ...orphanNorms, "2700": { auto: null, manual: 40 } } }),
    );

    fireEvent.change(await screen.findByPlaceholderText("Введите длину"), {
      target: { value: "3000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    expect(await screen.findByText(/не применима ни к одной длине/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    // Нормы не менялись — payload их не несёт, и сервер оставляет 62 на месте.
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const patch = onSave.mock.calls[0][0];
    expect(patch.lengths).toHaveLength(2);
    expect(patch.quantity_per_hanger).toBeUndefined();
  });

  it("снятие длины убирает её норму из патча явным null", async () => {
    const { onSave } = renderForm(
      makeProduct({ quantity_per_hanger: { "2700": { auto: null, manual: 40 } } }),
    );

    fireEvent.click(await screen.findByTitle("Удалить длину"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          lengths: [],
          quantity_per_hanger: { "2700": { auto: null, manual: null } },
        }),
        "edit",
      ),
    );
  });
});