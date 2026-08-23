import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/actions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/actions")>()),
  getActions: vi.fn(),
}));

import { getActions, type JournalAction } from "@/shared/api/actions";
import { ActionsJournalPage } from "./ActionsJournalPage";

const makeAction = (overrides: Partial<JournalAction> = {}): JournalAction => ({
  id: 1,
  action_type: "transfer_send",
  ref_id: 42,
  actor: "Иван",
  status: "active",
  depends_on: [],
  created_at: "2026-08-20T10:00:00Z",
  ...overrides,
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ActionsJournalPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getActions).mockResolvedValue({
    items: [
      makeAction(),
      makeAction({
        id: 2,
        action_type: "task_complete",
        status: "reversed",
        ref_id: 7,
      }),
    ],
    total: 2,
    page: 1,
    page_size: 50,
  });
});

describe("ActionsJournalPage", () => {
  it("рендерит таблицу действий со статус-бейджами", async () => {
    renderPage();

    await screen.findByTestId("action-row-1");
    expect(screen.getByTestId("action-row-2")).toBeTruthy();
    expect(screen.getByText("transfer_send")).toBeTruthy();
    expect(screen.getByText("Активно")).toBeTruthy();
    expect(screen.getByText("Отменено")).toBeTruthy();
    expect(screen.getByText("#42")).toBeTruthy();
    expect(getActions).toHaveBeenCalledTimes(1);
  });

  it("фильтр по статусу перезапрашивает список со статусом", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    // Radix Select — открываем кликом по триггеру и выбираем опцию
    fireEvent.click(screen.getByTestId("filter-status"));
    const option = await screen.findByRole("option", { name: "Активно" });
    fireEvent.click(option);

    await waitFor(() => {
      expect(getActions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "active" }),
      );
    });
  });

  it("Отменить доступно только для active, Изменить — только transfer_send+active", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    const reverseActive = screen.getByTestId("reverse-button-1") as HTMLButtonElement;
    const amendActive = screen.getByTestId("amend-button-1") as HTMLButtonElement;
    expect(reverseActive.disabled).toBe(false);
    expect(amendActive.disabled).toBe(false); // transfer_send + active

    const reverseReversed = screen.getByTestId("reverse-button-2") as HTMLButtonElement;
    const amendReversed = screen.getByTestId("amend-button-2") as HTMLButtonElement;
    expect(reverseReversed.disabled).toBe(true); // status=reversed
    expect(amendReversed.disabled).toBe(true); // не transfer_send
  });

  it("кнопка дерева открывает диалог цепочки", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    fireEvent.click(screen.getByTestId("tree-button-1"));
    await screen.findByTestId("tree-dialog");
    expect(screen.getByText("Цепочка действия #1")).toBeTruthy();
  });

  it("пустой список — заглушка «Действия не найдены»", async () => {
    vi.mocked(getActions).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    renderPage();
    await screen.findByText("Действия не найдены");
  });
});
