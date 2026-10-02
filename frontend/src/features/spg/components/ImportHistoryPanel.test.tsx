// «Посмотреть» в истории импортов остатков (#239): колонка «Операции» несёт
// пятую ось ключа остатка (ADR-0055) и подписывается общим правилом
// `formatCompletedOperationsLabel`. Без неё две строки одного артикула, склада
// и размера с разными остатками читаются как дубль — ровно тот симптом, из-за
// которого ось и вводилась.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/stockImportHistory", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stockImportHistory")>()),
  getStockImportBatches: vi.fn(),
  getStockImportBatch: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

import {
  getStockImportBatches,
  getStockImportBatch,
  type StockImportBatch,
  type StockImportBatchDetail,
  type StockImportRow,
} from "@/shared/api/stockImportHistory";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { AuthShellUser } from "@/features/auth/hooks/useAuth";
import { ImportHistoryPanel } from "./ImportHistoryPanel";

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
  total_rows: 2,
  imported_rows: 2,
  skipped_rows: 0,
  created_at: "2026-09-28T14:02:00Z",
  created_by_name: "Иван",
  rolled_back_at: null,
  deleted_at: null,
  can_rollback: true,
  rollback_blocked_reason: null,
  ...overrides,
});

/** Строка одного артикула, склада и размера; ось и остаток — параметры. */
const row = (overrides: Partial<StockImportRow> = {}): StockImportRow => ({
  row_id: 1,
  source_row_number: 2,
  sku: "OPS-460",
  matched_sku: null,
  product_id: 1,
  product_sku: "OPS-460",
  product_name: "Профиль",
  quantity: "10",
  dimensions_label: "2,7 м",
  target_section_id: 1,
  target_section_name: "Склад сырья",
  quality_state: "good",
  completed_operations: null,
  status: "valid",
  errors: [],
  warnings: [],
  raw_values: [],
  current_balance: "8888",
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

const renderPanel = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <ImportHistoryPanel />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

/** Открыть диалог «посмотреть» и вернуть его строки: [шапка, …тело]. */
async function openDetail(): Promise<HTMLElement[]> {
  fireEvent.click(await screen.findByRole("button", { name: "Посмотреть" }));
  const dialog = await screen.findByRole("dialog");
  // Диалог открывается раньше ответа запроса: ждём готовую таблицу, а не
  // первый кадр с «Загрузка строк…».
  await within(dialog).findByRole("columnheader", { name: "Операции" });
  return within(dialog).getAllByRole("row");
}

/** Ячейки строки по именам колонок — шапка и тело обязаны совпадать. */
function cellsByHeader(rows: HTMLElement[]): Map<string, string> {
  const header = within(rows[0])
    .getAllByRole("columnheader")
    .map((cell) => cell.textContent ?? "");
  const body = within(rows[1])
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
  return new Map(header.map((name, index) => [name, body[index] ?? ""]));
}

beforeEach(() => {
  vi.clearAllMocks();
  asRole("admin");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ImportHistoryPanel — «посмотреть»", () => {
  it("показывает ось операций и свои остатки у двух строк одного артикула", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([batch()]);
    const detail: StockImportBatchDetail = {
      batch: batch(),
      rows: [
        row({ row_id: 1, source_row_number: 2, completed_operations: ["WINDOW"] }),
        row({
          row_id: 2,
          source_row_number: 3,
          completed_operations: ["SHOT"],
          current_balance: "4500",
        }),
      ],
    };
    vi.mocked(getStockImportBatch).mockResolvedValue(detail);

    renderPanel();
    const rows = await openDetail();

    expect(rows).toHaveLength(3);
    const first = cellsByHeader(rows);
    // Шапка несёт колонку и тело отвечает ей же, а не сдвигается на ячейку.
    expect(first.get("Операции")).toBe("WINDOW");
    expect(first.get("Текущий остаток")).toBe("8888");

    const headerNames = within(rows[0])
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent ?? "");
    const second = new Map(
      headerNames.map((name, index) => [
        name,
        within(rows[2]).getAllByRole("cell")[index]?.textContent ?? "",
      ]),
    );
    expect(second.get("Операции")).toBe("SHOT");
    expect(second.get("Текущий остаток")).toBe("4500");
    // Один артикул, склад и размер — различаются ровно осью и остатком.
    expect(second.get("Артикул")).toBe(first.get("Артикул"));
    expect(second.get("Склад")).toBe(first.get("Склад"));
    expect(second.get("Размер")).toBe(first.get("Размер"));
    expect(second.get("Операции")).not.toBe(first.get("Операции"));
  });

  it("два пустых состояния оси печатают прочерк, но остаются двумя строками", async () => {
    vi.mocked(getStockImportBatches).mockResolvedValue([batch()]);
    vi.mocked(getStockImportBatch).mockResolvedValue({
      batch: batch(),
      rows: [
        row({ row_id: 1, source_row_number: 2, completed_operations: null }),
        row({ row_id: 2, source_row_number: 3, completed_operations: [] }),
      ],
    });

    renderPanel();
    const rows = await openDetail();

    expect(rows).toHaveLength(3);
    // Подпись ячейки одна — прочерк; различаются строки, а не их подписи
    // (ADR-0055 п.6): `null` и `[]` — разные ключи остатка.
    expect(cellsByHeader(rows).get("Операции")).toBe("—");

    const headerNames = within(rows[0])
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent ?? "");
    const opsIndex = headerNames.indexOf("Операции");
    expect(opsIndex).toBeGreaterThanOrEqual(0);
    expect(
      within(rows[2]).getAllByRole("cell")[opsIndex]?.textContent,
    ).toBe("—");
    expect(document.body.textContent).not.toContain("не зафиксировано");
    expect(document.body.textContent).not.toContain("без операций");
  });
});
