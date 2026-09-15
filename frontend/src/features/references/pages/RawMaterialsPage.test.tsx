// Тесты страницы «Справочник сырья» (#177): единая точка входа — меню «Операции»
// (импорт справочника Excel, импорт фото ZIP, выгрузка справочника Excel).
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/products", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/products")>()),
  fetchAllProducts: vi.fn(),
  exportCatalogExcel: vi.fn(),
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

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { exportCatalogExcel, fetchAllProducts } from "@/shared/api/products";
import { listRouteSelectionRules } from "@/shared/api/routes";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { toast } from "@/shared/ui/use-toast";
import { RawMaterialsPage } from "./RawMaterialsPage";

const OPERATIONS = /Операции/;
const IMPORT_EXCEL = "Импорт: справочник сырья (Excel)";
const IMPORT_ZIP = "Импорт: фотографии (ZIP)";
const EXPORT_EXCEL = "Экспорт: скачать справочник (Excel)";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(usePermission).mockReturnValue({
    canEditReferences: true,
    canEditSettings: false,
  });
  vi.mocked(fetchAllProducts).mockResolvedValue([]);
  vi.mocked(listRouteSelectionRules).mockResolvedValue([]);
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
    });
    renderPage();

    // Страница отрисовалась (панель фильтров есть), но меню операций скрыто
    await screen.findByRole("button", { name: /Фильтры/ });
    expect(screen.queryByRole("button", { name: OPERATIONS })).toBeNull();
  });
});
