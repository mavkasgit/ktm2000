// #465: фото и чертёж — независимые слоты. Своя загрузка, свой прогресс и
// ошибка, раздельное удаление, честный пустой слот.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  deleteProductPhoto: vi.fn(),
}));

vi.mock("@/shared/api/hangerCalc", () => ({
  calcHanger: vi.fn().mockResolvedValue({ results: [] }),
  calcPairedHanger: vi.fn().mockResolvedValue({ results: [] }),
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Product } from "@/shared/api/products";
import { deleteProductPhoto, uploadProductPhoto } from "@/shared/api/products";
import { makeProduct } from "../lib/productFixture";
import { CatalogForm } from "./CatalogForm";

const product = makeProduct({
  id: 190,
  sku: "ЮП-3473",
  name: "Перила",
  photo_full: "products/033_full.jpg",
  photo_full_version: "full-1",
  photo_thumb: "products/033_thumb.jpg",
  photo_thumb_version: "thumb-1",
  drawing_full: "products/033_drawing.jpg",
  drawing_full_version: "dwg-1",
  visual_origin: "alias",
});

const renderForm = (candidate: Product = product) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <CatalogForm product={candidate} mode="edit" onSave={vi.fn()} onCancel={() => {}} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

const photoRegion = () => screen.getByRole("region", { name: "Фото изделия" });
const drawingRegion = () => screen.getByRole("region", { name: "Чертёж" });

const uploadThroughModal = (trigger: RegExp) => {
  fireEvent.click(screen.getByRole("button", { name: trigger }));
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["bytes"], "slot.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: /^Загрузить$/ }));
  return file;
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:preview"),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

describe("CatalogForm: раздельные слоты фото и чертежа", () => {
  it("удаление чертежа оставляет фото и превью", async () => {
    vi.mocked(deleteProductPhoto).mockResolvedValue({
      ...product,
      drawing_full: null,
      drawing_full_version: null,
      visual_origin: null,
    });
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Удалить чертёж" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Удалить чертёж?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(deleteProductPhoto).toHaveBeenCalledWith(product.id, "drawing"));
    expect(await screen.findByText("Чертежа нет")).toBeTruthy();
    expect(screen.queryByText("Чертёж алиаса")).toBeNull();
    expect(screen.getByAltText(`${product.name} — фото`).getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(screen.getByAltText(`${product.name} — превью`).getAttribute("src")).toBe(
      "/static/products/033_thumb.jpg?v=thumb-1",
    );
  });

  it("удаление фото оставляет чертёж", async () => {
    vi.mocked(deleteProductPhoto).mockResolvedValue({
      ...product,
      photo_full: null,
      photo_full_version: null,
    });
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Удалить фото" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Удалить фото?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(deleteProductPhoto).toHaveBeenCalledWith(product.id, "full"));
    expect(await screen.findByText("Фото нет")).toBeTruthy();
    expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
    expect(screen.getByText("Чертёж алиаса")).toBeTruthy();
  });

  it("удаление превью не трогает ни фото, ни чертёж", async () => {
    vi.mocked(deleteProductPhoto).mockResolvedValue({
      ...product,
      photo_thumb: null,
      photo_thumb_version: null,
    });
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Удалить превью" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Удалить превью?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(deleteProductPhoto).toHaveBeenCalledWith(product.id, "thumb"));
    expect(await screen.findByText("Превью нет")).toBeTruthy();
    expect(screen.getByAltText(`${product.name} — фото`).getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
  });

  it("ошибка загрузки чертежа остаётся в его блоке и не трогает фото", async () => {
    vi.mocked(uploadProductPhoto).mockRejectedValue(new Error("сервер недоступен"));
    renderForm();

    uploadThroughModal(/Заменить чертёж/);

    await waitFor(() =>
      expect(within(drawingRegion()).getByRole("alert").textContent).toContain("сервер недоступен"),
    );
    expect(within(photoRegion()).queryByRole("alert")).toBeNull();
    expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
  });

  it("загрузка фото не меняет версию чертежа", async () => {
    vi.mocked(uploadProductPhoto).mockResolvedValue({
      ...product,
      photo_full_version: "full-2",
    });
    renderForm();

    const file = uploadThroughModal(/Заменить фото/);

    await waitFor(() => expect(uploadProductPhoto).toHaveBeenCalledWith(product.id, file, "full"));
    await waitFor(() =>
      expect(screen.getByAltText(`${product.name} — фото`).getAttribute("src")).toBe(
        "/static/products/033_full.jpg?v=full-2",
      ),
    );
    expect(screen.getByAltText(`${product.name} — чертёж`).getAttribute("src")).toBe(
      "/static/products/033_drawing.jpg?v=dwg-1",
    );
  });

  it("пустые слоты честные: ни фото, ни превью, ни чертежа", () => {
    renderForm(makeProduct({ name: "Пустой артикул" }));

    expect(screen.getByText("Фото нет")).toBeTruthy();
    expect(screen.getByText("Превью нет")).toBeTruthy();
    expect(screen.getByText("Чертежа нет")).toBeTruthy();
    expect(screen.queryByAltText("Пустой артикул — фото")).toBeNull();
    expect(screen.queryByAltText("Пустой артикул — превью")).toBeNull();
    expect(screen.queryByAltText("Пустой артикул — чертёж")).toBeNull();
  });

  it("старая схема без drawing_full не ломает карточку", () => {
    renderForm(
      makeProduct({
        name: "Старая схема",
        photo_full: "products/033_full.jpg",
        photo_full_version: "full-1",
        drawing_full: undefined,
        drawing_full_version: undefined,
        visual_origin: undefined,
      }),
    );

    expect(screen.getByAltText("Старая схема — фото").getAttribute("src")).toBe(
      "/static/products/033_full.jpg?v=full-1",
    );
    expect(screen.getByText("Чертежа нет")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("прогресс загрузки виден только в своём слоте", async () => {
    let resolveUpload: (value: Product) => void = () => {};
    vi.mocked(uploadProductPhoto).mockReturnValue(
      new Promise<Product>((resolve) => {
        resolveUpload = resolve;
      }),
    );
    renderForm();

    uploadThroughModal(/Заменить чертёж/);

    await waitFor(() => expect(within(drawingRegion()).getByText("Загрузка…")).toBeTruthy());
    expect(within(photoRegion()).queryByText("Загрузка…")).toBeNull();

    await act(async () => {
      resolveUpload({ ...product, drawing_full_version: "dwg-2" });
    });
  });
});
