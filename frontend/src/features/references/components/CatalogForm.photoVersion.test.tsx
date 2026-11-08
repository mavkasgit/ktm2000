// #404: после загрузки фото форма берёт версию из ответа API, а не локальный счётчик.
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
import type { Product } from "@/shared/api/products";
import { uploadProductPhoto } from "@/shared/api/products";
import { CatalogForm } from "./CatalogForm";

const product: Product = {
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
  photo_thumb_version: null,
  photo_full: "products/033_full.jpg",
  photo_full_version: "old-version",
  source: null,
  is_catalog_item: false,
  is_paired_profile: false,
  dimension_state: "length",
  skip_shot_blast: false,
  aliases: [],
  lengths: [],
  processing_flags: [],
  is_laminated: false,
};

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
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});

describe("CatalogForm: версия фото", () => {
  it("после upload использует версию из ответа API в URL фото", async () => {
    vi.mocked(uploadProductPhoto).mockResolvedValue({
      ...product,
      photo_full_version: "server-version",
    });
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: /Загрузить основное фото/ }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["photo"], "new-full.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /^Загрузить$/ }));

    await waitFor(() => expect(uploadProductPhoto).toHaveBeenCalledWith(190, file, "full"));
    const image = screen.getByAltText(product.name);
    await waitFor(() =>
      expect(image.getAttribute("src")).toBe("/static/products/033_full.jpg?v=server-version"),
    );
  });
});
