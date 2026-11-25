// #463: полный просмотр открывается чертежом, переключатель ведёт на фото,
// чужой чертёж помечен бейджем (ADR-0078).
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
import { makeProduct } from "../lib/productFixture";
import { uploadProductPhoto } from "@/shared/api/products";
import { CatalogForm } from "./CatalogForm";

const product = makeProduct({
  sku: "ЮП-2413",
  name: "Профиль ЮП-2413",
  photo_full: "products/033_full.jpg",
  photo_full_version: "full-1",
  drawing_full: "products/033_drawing.jpg",
  drawing_full_version: "dwg-1",
  visual_origin: "alias",
});

const renderForm = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <CatalogForm product={product} mode="edit" onSave={vi.fn()} onCancel={() => {}} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:preview"),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

describe("CatalogForm: слот чертежа", () => {
  it("показывает фото и чертёж в своих слотах независимо", () => {
    renderForm();

    expect(screen.getByAltText(`${product.name} — фото`).getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
  });

  it("помечает чертёж алиаса бейджем", () => {
    renderForm();
    expect(screen.getByText("Чертёж алиаса")).toBeTruthy();
  });

  it("без чертежа блок честно пуст — фото в слот не подставляется", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <CatalogForm
            product={makeProduct({
              name: "Без чертежа",
              photo_full: "products/033_full.jpg",
              photo_full_version: "full-1",
            })}
            mode="edit"
            onSave={vi.fn()}
            onCancel={() => {}}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(screen.getByAltText("Без чертежа — фото").getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(screen.queryByAltText("Без чертежа — чертёж")).toBeNull();
    expect(screen.getByText("Чертежа нет")).toBeTruthy();
  });

  it("загружает чертёж в отдельный слот, не меняя фото", async () => {
    vi.mocked(uploadProductPhoto).mockResolvedValue({
      ...product,
      drawing_full_version: "dwg-2",
    });
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: /Заменить чертёж/ }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["drawing"], "drawing.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /^Загрузить$/ }));

    await waitFor(() => expect(uploadProductPhoto).toHaveBeenCalledWith(product.id, file, "drawing"));
    await waitFor(() =>
      expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
        "/static/products/033_drawing.jpg?v=dwg-2",
      ),
    );
    // Загрузка чертежа не перезагружает фото: у него своя версия.
    expect(screen.getByAltText(`${product.name} — фото`).getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
  });

  it("полный просмотр открывается чертежом, если он есть", () => {
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Открыть полностью" }));

    expect(screen.getByAltText(product.name).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
  });

  it("без чертежа полный просмотр открывает фото", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <CatalogForm
            product={makeProduct({
              name: "Без чертежа",
              photo_full: "products/033_full.jpg",
              photo_full_version: "full-1",
            })}
            mode="edit"
            onSave={vi.fn()}
            onCancel={() => {}}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Открыть полностью" }));

    expect(screen.getByAltText("Без чертежа").getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
  });
});
