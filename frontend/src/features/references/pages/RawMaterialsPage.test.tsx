// Тесты страницы «Справочник сырья» (#177): единая точка входа — меню «Операции»
// (импорт справочника Excel, импорт фото ZIP, выгрузка справочника Excel).
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  fetchAllProducts: vi.fn(),
  exportCatalogExcel: vi.fn(),
  patchProduct: vi.fn(),
  listProductsPaginated: vi.fn(),
  listProductPairCatalog: vi.fn(),
  listProductPairs: vi.fn(),
}));

vi.mock("@/shared/api/routes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/routes")>()),
  listRouteSelectionRules: vi.fn(),
}));

vi.mock("@/features/auth/hooks/usePermission", () => ({
  usePermission: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", () => ({
  toast: vi.fn(),
}));

vi.mock("@/shared/api/hangerCalc", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/hangerCalc")>()),
  calcHanger: vi.fn(),
  calcPairedHanger: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  listDimensionTypes: vi.fn(),
  listProductDimensions: vi.fn(),
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  exportCatalogExcel,
  fetchAllProducts,
  listProductPairCatalog,
  listProductPairs,
  listProductsPaginated,
  patchProduct,
} from "@/shared/api/products";
import type { Product } from "@/shared/api/products";
import { calcHanger, calcPairedHanger } from "@/shared/api/hangerCalc";
import { listDimensionTypes, listProductDimensions } from "../api";
import { listRouteSelectionRules } from "@/shared/api/routes";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { toast } from "@/shared/ui/use-toast";
import { RawMaterialsPage } from "./RawMaterialsPage";

const OPERATIONS = /Операции/;
const IMPORT_EXCEL = "Импорт: справочник сырья (Excel)";
const IMPORT_ZIP = "Импорт: фотографии (ZIP)";
const EXPORT_EXCEL = "Экспорт: скачать справочник (Excel)";

const SETTINGS = { area_limit_m2: 13, rod_length_mm: 1450, gap_mm: 20, rod_count: 2 };

const product = (overrides: Partial<Product> = {}): Product => ({
  id: 1,
  sku: "RAW-2700",
  code: null,
  name: "Профиль",
  type: "component",
  unit: "шт",
  is_active: true,
  notes: null,
  profile_type: null,
  alloy: null,
  color: null,
  anod_type: null,
  weight_per_meter: null,
  perimeter_mm: 64.2,
  mount_width_mm: 19.35,
  quantity_per_hanger: { "2700": { auto: 50, manual: 40 } },
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
  lengths: [{ length_mm: 2700, raw_length_mm: null, is_primary: true }],
  processing_flags: [],
  is_laminated: false,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePermission).mockReturnValue({
    canEditReferences: true,
    canEditSettings: false,
    canDeleteProductionPlan: false,
  });
  vi.mocked(fetchAllProducts).mockResolvedValue([]);
  vi.mocked(listRouteSelectionRules).mockResolvedValue([]);
  vi.mocked(listProductPairCatalog).mockResolvedValue([]);
  vi.mocked(listProductPairs).mockResolvedValue([]);
  vi.mocked(listProductsPaginated).mockResolvedValue({ items: [], total: 0, limit: 2000, offset: 0 });
  vi.mocked(listDimensionTypes).mockResolvedValue([]);
  vi.mocked(listProductDimensions).mockResolvedValue([]);
  vi.mocked(calcHanger).mockResolvedValue({ results: [], hanger: SETTINGS });
  vi.mocked(calcPairedHanger).mockResolvedValue({ results: [], hanger: SETTINGS });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const renderPage = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RawMaterialsPage />
    </QueryClientProvider>,
  );
};

/** Открывает меню «Операции» (Radix слушает pointerdown, а не click). */
const openOperationsMenu = async () => {
  const trigger = await screen.findByRole("button", { name: OPERATIONS });
  fireEvent.pointerDown(trigger);
};

const clickMenuItem = async (name: string) => {
  fireEvent.click(await screen.findByRole("menuitem", { name }));
};

describe("RawMaterialsPage: меню «Операции»", () => {
  it("открывается по клику и содержит три пункта: импорт Excel, импорт ZIP, экспорт Excel", async () => {
    renderPage();

    await openOperationsMenu();

    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent?.trim())).toEqual([
      IMPORT_EXCEL,
      IMPORT_ZIP,
      EXPORT_EXCEL,
    ]);
  });

  it("«Экспорт: скачать справочник (Excel)» вызывает exportCatalogExcel один раз", async () => {
    vi.mocked(exportCatalogExcel).mockResolvedValue(undefined);
    renderPage();

    await openOperationsMenu();
    await clickMenuItem(EXPORT_EXCEL);

    await waitFor(() => expect(exportCatalogExcel).toHaveBeenCalledTimes(1));
  });

  it("ошибка выгрузки показывается тостом «Ошибка выгрузки справочника»", async () => {
    vi.mocked(exportCatalogExcel).mockRejectedValue(new Error("export down"));
    renderPage();

    await openOperationsMenu();
    await clickMenuItem(EXPORT_EXCEL);

    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "destructive", title: "Ошибка выгрузки справочника" }),
    );
  });

  it("«Импорт: фотографии (ZIP)» открывает выбор файла .zip", async () => {
    const clicked: HTMLElement[] = [];
    vi.spyOn(HTMLElement.prototype, "click").mockImplementation(function (
      this: HTMLElement,
    ) {
      clicked.push(this);
    });
    renderPage();

    await openOperationsMenu();
    await clickMenuItem(IMPORT_ZIP);

    // Нативный диалог выбора файла открывается кликом по скрытому input
    expect(clicked).toHaveLength(1);
    expect(clicked[0].getAttribute("accept")).toBe(".zip");
  });

  it("«Импорт: справочник сырья (Excel)» открывает мастер «Импорт из Excel»", async () => {
    renderPage();

    await openOperationsMenu();
    await clickMenuItem(IMPORT_EXCEL);

    expect(await screen.findByRole("heading", { name: "Импорт из Excel" })).toBeTruthy();
  });

  it("без правки справочников кнопки «Операции» нет", async () => {
    vi.mocked(usePermission).mockReturnValue({
      canEditReferences: false,
      canEditSettings: false,
      canDeleteProductionPlan: false,
    });
    renderPage();

    // Страница отрисовалась (панель фильтров есть), но меню операций скрыто
    await screen.findByRole("button", { name: /Фильтры/ });
    expect(screen.queryByRole("button", { name: OPERATIONS })).toBeNull();
  });
});

describe("RawMaterialsPage: реестр длин и расчёт подвесов", () => {
  it("редактирование raw сохраняет canonical lengths и ручной N по нормальной длине", async () => {
    const current = product();
    vi.mocked(fetchAllProducts).mockResolvedValue([current]);
    vi.mocked(patchProduct).mockResolvedValue({
      data: { ...current, lengths: [{ length_mm: 2700, raw_length_mm: 2750, is_primary: true }] },
      activatedAliases: [],
    });
    renderPage();

    fireEvent.click((await screen.findByRole("button", { name: "RAW-2700" })).closest("tr")!);
    const rawInput = await screen.findByRole("spinbutton", { name: "Сырьевая длина для 2700 мм" });
    fireEvent.change(rawInput, { target: { value: "2750" } });
    fireEvent.submit(rawInput.closest("form")!);

    await waitFor(() => expect(patchProduct).toHaveBeenCalledWith(1, {
      lengths: [{ length_mm: 2700, raw_length_mm: 2750, is_primary: true }],
    }));
  });

  it("в расчёте подвесов показывает обе длины, включая равные", async () => {
    const current = product({
      hanger_mode: "auto",
      lengths: [
        { length_mm: 2700, raw_length_mm: 2750, is_primary: true },
        { length_mm: 3000, raw_length_mm: null, is_primary: false },
      ],
    });
    vi.mocked(listProductsPaginated).mockResolvedValue({ items: [current], total: 1, limit: 2000, offset: 0 });
    vi.mocked(calcHanger).mockResolvedValue({
      hanger: SETTINGS,
      results: [
        { by_area: 50, by_size: 50, total: 50, limiter: "area", area_m2: 0.18, is_calculable: true },
        { by_area: 55, by_size: 55, total: 55, limiter: "area", area_m2: 0.2, is_calculable: true },
      ],
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Расчёт подвесов" }));
    const row = await screen.findByRole("button", { name: "RAW-2700" });
    const hangerRow = row.closest("tr");
    expect(hangerRow).not.toBeNull();
    expect(hangerRow!.textContent).toContain("2700 / сырьё 2750");
    expect(hangerRow!.textContent).toContain("3000 / сырьё 3000");
  });

  it.each(["2700", "2750"])("поиск по длине %s оставляет строку артикула", async (query) => {
    const current = product({
      hanger_mode: "auto",
      lengths: [{ length_mm: 2700, raw_length_mm: 2750, is_primary: true }],
    });
    const unrelated = product({
      id: 2,
      sku: "RAW-3000",
      lengths: [{ length_mm: 3000, raw_length_mm: 3000, is_primary: true }],
    });
    vi.mocked(listProductsPaginated).mockResolvedValue({ items: [current, unrelated], total: 2, limit: 2000, offset: 0 });
    vi.mocked(calcHanger).mockResolvedValue({
      hanger: SETTINGS,
      results: [
        { by_area: 50, by_size: 50, total: 50, limiter: "area", area_m2: 0.18, is_calculable: true },
        { by_area: 55, by_size: 55, total: 55, limiter: "area", area_m2: 0.2, is_calculable: true },
      ],
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Расчёт подвесов" }));
    await screen.findByRole("button", { name: "RAW-2700" });
    expect(screen.getByRole("button", { name: "RAW-3000" })).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Поиск по артикулу"), { target: { value: query } });

    expect(await screen.findByRole("button", { name: "RAW-2700" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("button", { name: "RAW-3000" })).toBeNull());
  });
});
