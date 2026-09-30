// Страница «История импортов остатков» (#232): правила видимости действий
// одинаковы со старой секцией в модалке, но проверять их надо на отдельном
// входе — именно он теперь основной.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/stockImportHistory", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stockImportHistory")>()),
  getStockImportBatches: vi.fn(),
  hideStockImportBatch: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

import {
  getStockImportBatches,
  hideStockImportBatch,
  type StockImportBatch,
} from "@/shared/api/stockImportHistory";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { AuthShellUser } from "@/features/auth/hooks/useAuth";
import { ImportHistoryPage } from "./ImportHistoryPage";

const batch = (overrides: Partial<StockImportBatch> = {}): StockImportBatch => ({
  batch_id: 1,
  action_id: 10,
  status: "applied",
  legacy: false,
  clear_existing: false,
  filename: "остатки_28.09.xlsx",
  file_id: 5,
  sheet_name: "Лист1",
  location_id: 1,
  location_name: "Склад сырья",
  total_rows: 10,
  imported_rows: 10,
  skipped_rows: 0,
  created_at: "2026-09-28T14:02:00Z",
  created_by_name: "Иван",
  rolled_back_at: null,
  deleted_at: null,
  can_rollback: true,
  rollback_blocked_reason: null,
  ...overrides,
});

const asRole = (role: string) => {
  const user: AuthShellUser = { username: "u", full_name: "U", role };
  vi.mocked(useAuth).mockReturnValue({
    user,
    rolesCatalog: [],
    roleLabel: (r: string) => r,
    roleSections: () => [],
    isAuthenticated: true,
    isLoading: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  });
};

const renderPage = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <ImportHistoryPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  asRole("admin");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ImportHistoryPage", () => {
  it("показывает батчи без прохождения нового импорта", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([
      batch(),
      batch({ batch_id: 2, action_id: 11, filename: null, file_id: null, legacy: false }),
    ]);

    renderPage();

    expect(await screen.findByText("остатки_28.09.xlsx")).toBeTruthy();
    // Батч без файла (legacy/буфер) показывает источник, а не пустую ячейку
    expect(screen.getByText("из буфера")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Скачать/ })).toHaveLength(1);
  });

  it("гасит откат у не-последнего батча склада с объяснением", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([
      batch({ can_rollback: false, rollback_blocked_reason: "batch_not_last_for_location" }),
    ]);

    renderPage();

    const rollback = await screen.findByRole("button", { name: /Откатить/ });
    expect((rollback as HTMLButtonElement).disabled).toBe(true);
    expect(rollback.getAttribute("title")).toBe(
      "Откатить можно только последний импорт этого склада",
    );
    expect(
      screen.getByText(/Откатить можно только последний импорт по каждому складу/),
    ).toBeTruthy();
  });

  it("не даёт откат и скрытие не-администратору", async () => {
    asRole("operator");
    vi.mocked(getStockImportBatches).mockResolvedValue([batch()]);

    renderPage();

    await screen.findByText("остатки_28.09.xlsx");
    const [rollback] = screen.getAllByRole("button", { name: /Откатить/ });
    const hide = screen.getByRole("button", { name: "Удалить" });
    expect((rollback as HTMLButtonElement).disabled).toBe(true);
    expect((hide as HTMLButtonElement).disabled).toBe(true);
  });

  it("показывает отмененный батч как отмененный, а не как залитый", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([
      batch({ status: "rolled_back", can_rollback: false, rolled_back_at: "2026-09-29T09:00:00Z" }),
    ]);

    renderPage();

    expect(await screen.findByText("Отменен")).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByText("Залит")).toBeNull();
    });
  });

  it("прячет батч без поля «причина», а причину всё равно пишет", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([batch({ batch_id: 9, action_id: 19 })]);
    vi.mocked(hideStockImportBatch).mockResolvedValue({ hidden: true, batch_id: 9 });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    // Поля причины в UI нет: оператору незачем её набирать
    expect(screen.queryByPlaceholderText(/Причина/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Убрать из списка" }));
    await waitFor(() => {
      expect(hideStockImportBatch).toHaveBeenCalledTimes(1);
    });
    // Причина уходит в БД непустой — иначе потерялся бы вопрос «на каком
    // основании запись спрятана»
    expect(vi.mocked(hideStockImportBatch).mock.calls[0]?.[1]).toBeTruthy();
  });

  it("пустой список не выглядит как ошибка загрузки", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("Импортов пока не было.")).toBeTruthy();
  });
});