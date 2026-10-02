/**
 * Массовый режим «Готово к передаче»: кнопки передачи в строках остаются на
 * месте и гаснут, Escape выходит из режима (как «Выйти» в футере), а окно
 * поверх режима клавишу не отдаёт.
 *
 * Почему это тест, а не только поведение компонента: колонка «Действия» при
 * входе в режим переставала рисовать кнопки, ширина колонки ехала, и страница
 * прыгала. Проверяется то, что видит оператор: наличие кнопок, их disabled и
 * исчезновение футера по Escape.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  listReadyToTransfer: vi.fn(),
  listTransferHistory: vi.fn(),
}));

vi.mock("@/shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

// Футер массового режима читает профиль оператора (`useAuth`); страница живёт
// внутри провайдера приложения, в тесте его подменяем.
vi.mock("@/features/auth/hooks/useAuth", () => ({ useAuth: vi.fn() }));

import { useAuth, type AuthShellUser } from "@/features/auth/hooks/useAuth";

import { getSpgList } from "@/shared/api/spg";
import {
  listReadyToTransfer,
  listTransferHistory,
  type ReadyToTransferListParams,
  type ReadyToTransferResponse,
  type ReadyToTransferTask,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { TransfersPage } from "./TransfersPage";
import { isAnyDialogOpen } from "@/shared/lib/dialogOpen";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: "010",
    operation_name: "Пила",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "100",
    completed_quantity: "100",
    already_transferred_quantity: "0",
    transferable_quantity: "30",
    has_next_step: true,
    next_section_id: 4,
    next_section_code: "SHOT_BLAST",
    next_section_name: "Дробеструй",
    next_operation_name: "Дробеструй",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

const readyTasks: ReadyToTransferTask[] = [
  makeTask({ task_id: 1, plan_position_id: 7, transferable_quantity: "30", operation_name: "Пила" }),
  makeTask({ task_id: 2, plan_position_id: 3, transferable_quantity: "70", operation_name: "Пила" }),
  makeTask({ task_id: 3, plan_position_id: 5, transferable_quantity: "50", operation_name: "Пила" }),
];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

/** Кнопки передачи строк (не футера): «Передать»/«Отправить». */
function rowButtons(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("tbody button")).filter((button) =>
    /^(Передать|Отправить)$/.test(button.textContent ?? ""),
  );
}

function bulkFooter(): HTMLElement | null {
  return screen.queryByRole("button", { name: /^Передать все/ });
}

function enterBulkMode(): void {
  fireEvent.click(screen.getByRole("button", { name: "Групповые операции" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  const operator: AuthShellUser = {
    id: 7,
    username: "operator",
    full_name: "Иванов",
    role: "operator",
  };
  vi.mocked(useAuth).mockReturnValue({
    user: operator,
    rolesCatalog: [],
    roleLabel: (role: string) => role,
    roleSections: () => [],
    isAuthenticated: true,
    isLoading: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  });
  vi.mocked(getSpgList).mockResolvedValue([
    {
      id: 1,
      code: "GP1",
      name: "ГХП №1",
      description: null,
      sort_order: 10,
      is_active: true,
      icon: null,
      icon_color: null,
      sections: [],
    },
  ]);
  vi.mocked(listTransferHistory).mockResolvedValue({
    section_id: null,
    spg_id: null,
    transfers: [],
    total: 0,
    limit: 50,
    offset: 0,
  } satisfies TransferHistoryResponse);
  vi.mocked(listReadyToTransfer).mockImplementation(async (params: ReadyToTransferListParams = {}) => {
    const items = params.sort?.includes("transferable_qty:desc")
      ? [...readyTasks].sort((a, b) => parseFloat(b.transferable_quantity) - parseFloat(a.transferable_quantity))
      : readyTasks;
    return {
      items,
      total: items.length,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      filters: { section_id: null, spg_id: null },
    } satisfies ReadyToTransferResponse;
  });
});

describe("TransfersPage: массовый режим", () => {
  it("сохраняет кнопку передачи в шапке группы и гасит её, а не прячет", async () => {
    renderPage();
    await screen.findByText(/ЮП-2083/);
    await waitFor(() => expect(rowButtons().length).toBeGreaterThan(0));

    // Колонка «Действия» — её ширина и есть то, что «прыгало»: в обычном
    // режиме группа свёрнута, в массовом раскрыта, но колонка та же.
    const widthOfActions = (): number =>
      document.querySelector<HTMLTableCellElement>("tbody tr td:last-of-type")?.getBoundingClientRect()
        .width ?? 0;
    const normalWidth = widthOfActions();
    expect(rowButtons().some((button) => !button.disabled)).toBe(true);

    enterBulkMode();

    await waitFor(() => {
      const buttons = rowButtons();
      // Кнопки остались на месте у всех, кто виден, и все погашены.
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((button) => button.disabled)).toBe(true);
    });
    expect(widthOfActions()).toBe(normalWidth);

    // Выход из режима возвращает кнопкам работу.
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(rowButtons().some((button) => !button.disabled)).toBe(true));
  });

  it("в футере одна «Отмена» вместо «Сбросить» и «Выйти»", async () => {
    renderPage();
    await screen.findByText(/ЮП-2083/);
    enterBulkMode();
    await waitFor(() => expect(bulkFooter()).not.toBeNull());

    expect(screen.queryByRole("button", { name: "Сбросить", hidden: true })).toBeNull();
    expect(screen.queryByRole("button", { name: "Выйти", hidden: true })).toBeNull();
    expect(screen.getByRole("button", { name: "Отмена", hidden: true })).toBeTruthy();
  });

  it("Escape выходит из массового режима, как кнопка «Выйти»", async () => {
    renderPage();
    await screen.findByText(/ЮП-2083/);
    enterBulkMode();
    await waitFor(() => expect(bulkFooter()).not.toBeNull());

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => expect(bulkFooter()).toBeNull());
    // Выйдя из режима, строки снова умеют передавать себя сами.
    expect(rowButtons().some((button) => !button.disabled)).toBe(true);
  });

  it("Escape в открытом окне закрывает окно, а не выходит из режима", async () => {
    renderPage();
    await screen.findByText(/ЮП-2083/);
    enterBulkMode();
    await waitFor(() => expect(bulkFooter()).not.toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Печать списка" }));
    await waitFor(() => {
      expect(isAnyDialogOpen()).toBe(true);
    });

    fireEvent.keyDown(window, { key: "Escape" });

    // Клавишу забирает окно: режим остаётся включённым, иначе второе нажатие
    // выбрасывало бы оператора из режима вместе с окном. Открытое окно держит
    // остальную страницу в `aria-hidden`, поэтому футер ищем с `hidden: true`.
    expect(screen.queryByRole("button", { name: /^Передать все/, hidden: true })).not.toBeNull();
  });
});
