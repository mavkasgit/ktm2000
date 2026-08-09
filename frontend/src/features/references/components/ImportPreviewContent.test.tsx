import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CatalogPreview } from "@/shared/api/products";
import { ImportPreviewContent } from "./ImportPreviewContent";

function makePreview(overrides: Partial<CatalogPreview> = {}): CatalogPreview {
  return {
    items: [
      {
        sku: "SKU-CREATE",
        name: "Создаваемый",
        length_mm: 1000,
        quantity_per_hanger: 5,
        has_photo: false,
        action: "create",
      },
      {
        sku: "SKU-UPDATE",
        name: "Обновляемый",
        length_mm: 2000,
        quantity_per_hanger: null,
        has_photo: true,
        action: "update",
      },
    ],
    stats: { total: 2, create: 1, update: 1, skip: 0 },
    ...overrides,
  };
}

describe("ImportPreviewContent", () => {
  it("renders the summary counters and the table rows", () => {
    render(<ImportPreviewContent preview={makePreview()} />);

    expect(screen.getByText("Всего 2:")).toBeTruthy();
    expect(screen.getByText("1 создать")).toBeTruthy();
    expect(screen.getByText("1 обновить")).toBeTruthy();
    expect(screen.getByText("0 пропустить")).toBeTruthy();

    expect(screen.getByText("SKU-CREATE")).toBeTruthy();
    expect(screen.getByText("SKU-UPDATE")).toBeTruthy();
    // Действия в строках таблицы
    expect(screen.getAllByText("Создать").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Обновить").length).toBeGreaterThan(0);
    // Заголовки колонок
    expect(screen.getByText("Артикул")).toBeTruthy();
    expect(screen.getByText("Длины, мм")).toBeTruthy();
    expect(screen.getByText("Кол-во на подвесе")).toBeTruthy();
    expect(screen.getByText("Фото")).toBeTruthy();
    expect(screen.getByText("Действие")).toBeTruthy();
  });

  it("filters the table rows by action", () => {
    render(<ImportPreviewContent preview={makePreview()} />);

    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));

    expect(screen.queryByText("SKU-CREATE")).toBeNull();
    expect(screen.getByText("SKU-UPDATE")).toBeTruthy();
  });

  it("resets the filter back to all rows with the «Все» button", () => {
    render(<ImportPreviewContent preview={makePreview()} />);

    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(screen.queryByText("SKU-CREATE")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Все" }));

    expect(screen.getByText("SKU-CREATE")).toBeTruthy();
    expect(screen.getByText("SKU-UPDATE")).toBeTruthy();
  });

  it("renders the row errors report", () => {
    const preview = makePreview({
      stats: { total: 2, create: 1, update: 1, skip: 0, errors: 1 },
      errors: [{ row: 7, sku: "SKU-BAD", message: "нет длины" }],
    });
    render(<ImportPreviewContent preview={preview} />);

    expect(screen.getByText("Ошибки строк (строки пропущены):")).toBeTruthy();
    expect(screen.getByText("Строка 7 — SKU-BAD: нет длины")).toBeTruthy();
    expect(screen.getByText("1 строк с ошибками")).toBeTruthy();
  });

  it("does not render the row errors report when there are no errors", () => {
    render(<ImportPreviewContent preview={makePreview()} />);

    expect(screen.queryByText("Ошибки строк (строки пропущены):")).toBeNull();
  });

  it("shows the empty state when no rows match the current filter", () => {
    const preview = makePreview();
    render(<ImportPreviewContent preview={preview} />);

    fireEvent.click(screen.getByRole("button", { name: "Пропустить" }));

    expect(screen.getByText("Нет записей")).toBeTruthy();
    expect(screen.queryByText("SKU-CREATE")).toBeNull();
    expect(screen.queryByText("SKU-UPDATE")).toBeNull();
  });
});
