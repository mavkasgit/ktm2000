// Карточка артикула: сторонний заказ (T-383).
//
// Отметка односторонняя: показываем только «Сторонний», «Свой» не рисуем.
// Комплект 4 × 2 задаёт ручную норму 8, а снятие отметки очищает заказчика
// и комплект — иначе в API уехали бы поля, которых у обычного артикула нет.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/references/api", () => ({
  listDimensionTypes: vi.fn().mockResolvedValue([]),
  listProductDimensions: vi.fn().mockResolvedValue([]),
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
import type { Product } from "@/shared/api/products";
import { makeProduct as makeProductFixture } from "../lib/productFixture";
import { CatalogForm } from "./CatalogForm";

const makeUrny = (overrides: Partial<Product> = {}): Product =>
  makeProductFixture({
    id: 224,
    sku: "урны",
    name: "Урны, комплект 2 шт (корпус + крышка)",
    type: "component",
    unit: "шт",
    dimension_state: "volume",
    lengths: [],
    hanger_mode: "manual",
    third_party: true,
    customer: "ГорКомплекс",
    pack: { sets_per_hanger: 4, pieces_per_set: 2 },
    quantity_per_hanger: { default: { auto: null, manual: 8 } },
    ...overrides,
  });

const renderForm = (product: Product, onSave = vi.fn()) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <CatalogForm product={product} mode="edit" onSave={onSave} onCancel={() => {}} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { onSave, ...view };
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CatalogForm: сторонний заказ", () => {
  it("показывает отметку, заказчика и комплект, но не «Свой»", async () => {
    renderForm(makeUrny());

    expect(await screen.findByText("Сторонний")).toBeTruthy();
    expect(screen.queryByText("Свой")).toBeNull();
    expect((screen.getByLabelText("Заказчик") as HTMLInputElement).value).toBe("ГорКомплекс");
    expect((screen.getByLabelText("Комплектов на подвес") as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("Предметов в комплекте") as HTMLInputElement).value).toBe("2");
  });

  it("снятие отметки очищает заказчика и комплект", async () => {
    const { onSave } = renderForm(makeUrny());

    fireEvent.click(await screen.findByRole("checkbox", { name: /Сторонний/ }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          third_party: false,
          customer: null,
          pack: null,
        }),
        "edit",
      ),
    );
    expect(screen.queryByLabelText("Заказчик")).toBeNull();
  });

  it("комплект пересчитывает ручную норму: 3 × 2 = 6", async () => {
    const { onSave } = renderForm(makeUrny());

    fireEvent.change(await screen.findByLabelText("Комплектов на подвес"), {
      target: { value: "3" },
    });
    expect((screen.getByLabelText(/Кол-во на подвесе/) as HTMLInputElement).value).toBe("6");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          pack: { sets_per_hanger: 3, pieces_per_set: 2 },
          quantity_per_hanger: { default: { auto: null, manual: 6 } },
        }),
        "edit",
      ),
    );
  });

  it("у length-артикула комплект не создаёт норму default", async () => {
    const { onSave } = renderForm(
      makeUrny({
        dimension_state: "length",
        lengths: [{ length_mm: 2700, raw_length_mm: null, is_primary: true }],
        hanger_mode: "manual",
        quantity_per_hanger: { "2700": { auto: null, manual: 12 } },
      }),
    );

    fireEvent.change(await screen.findByLabelText("Комплектов на подвес"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const patch = onSave.mock.calls[0][0];
    expect(patch.quantity_per_hanger ?? {}).not.toHaveProperty("default");
  });
});
