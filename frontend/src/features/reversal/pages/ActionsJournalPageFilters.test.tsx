import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/actions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/actions")>()),
  getActions: vi.fn(),
}));
vi.mock("@/features/auth/hooks/useAuth", () => ({ useAuth: vi.fn() }));

import { getActions, type JournalAction } from "@/shared/api/actions";
import { useAuth, type AuthShellUser } from "@/features/auth/hooks/useAuth";
import { ROW_TONE_STRIPE, ROW_TONE_WASH } from "@/shared/lib/rowTones";
import { DATA_TABLE_STYLES, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { TABLE_CORNER_RESET_TD_CLASS } from "@/shared/ui/TableCornerResetHeader";
import { ActionsJournalPage } from "./ActionsJournalPage";

/**
 * Панель фильтров журнала: параметры запроса, счётчик и сброс.
 *
 * Отдельный файл от `ActionsJournalPage.test.tsx` не из-за другого экрана, а
 * потому, что этот набор проверяет связку «панель ↔ попаперы в шапке ↔ запрос»:
 * оба фильтра приходят из одного состояния колонок, и разойтись они могут
 * только здесь.
 */

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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ActionsJournalPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  const user: AuthShellUser = { username: "u", full_name: "U", role: "admin" };
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
  vi.mocked(getActions).mockResolvedValue({
    items: [makeAction()],
    total: 1,
    page: 1,
    page_size: 50,
  });
});

describe("панель фильтров журнала «Отмена действий»", () => {
  it("выбор статуса уезжает в запрос как status", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    fireEvent.click(screen.getByTestId("filter-status"));
    fireEvent.click(await screen.findByRole("option", { name: "Отменено" }));

    await waitFor(() =>
      expect(getActions).toHaveBeenLastCalledWith(expect.objectContaining({ status: "reversed" })),
    );
  });

  it("выбор типа действия уезжает в запрос как action_type", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    fireEvent.click(screen.getByTestId("filter-type"));
    fireEvent.click(await screen.findByRole("option", { name: "Завершение операции" }));

    await waitFor(() =>
      expect(getActions).toHaveBeenLastCalledWith(
        expect.objectContaining({ action_type: "task_complete" }),
      ),
    );
  });

  it("без выбора сервер получает оба фильтра пустыми, а не «all»", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");

    // `all` — это подпись пункта «Все статусы», а не значение сервера: отдать его
    // значит отфильтровать журнал по статусу, которого не бывает.
    await waitFor(() =>
      expect(getActions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: null, action_type: null }),
      ),
    );
  });

  it("счётчик считает выбор один раз и сброс его гасит", async () => {
    renderPage();
    await screen.findByTestId("action-row-1");
    expect(screen.queryByText(/Активных фильтров/)).toBeNull();

    fireEvent.click(screen.getByTestId("filter-status"));
    fireEvent.click(await screen.findByRole("option", { name: "Изменено" }));

    // Панель и попапер в шапке пишут в одно состояние колонок, поэтому один
    // выбор — одна метка, а не две.
    await waitFor(() => expect(screen.getAllByText(/Активных фильтров: 1/)).toHaveLength(1));

    // Кнопок сброса две — в панели и угол таблицы; обе ведут в один сброс.
    fireEvent.click(screen.getAllByRole("button", { name: /Сбросить/ })[0]!);

    await waitFor(() =>
      expect(getActions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: null, action_type: null }),
      ),
    );
    await waitFor(() => expect(screen.queryByText(/Активных фильтров/)).toBeNull());
  });
});

describe("стиль строк журнала «Отмена действий»", () => {
  it("строка, ячейки и полоса тона берутся из общего словаря, а не своих классов", async () => {
    renderPage();

    // Статус `active` — живое, отменяемое действие: тон `active` из словаря.
    const row = (await screen.findByTestId("action-row-1")) as HTMLElement;

    expect(row.style.height).toBe(`${TABLE_ROW_DENSE.rowHeightPx}px`);
    expect(row.className).toContain(ROW_TONE_WASH.active);

    // Шапка: три токена, как в «Журнале действий». Возврат своих
    // `bg-slate-50 uppercase` должен ронять этот файл.
    const header = row.closest("table")!.querySelector("thead th") as HTMLElement;
    expect(header.className).toContain(DATA_TABLE_STYLES.headerRow);
    expect(header.className).toContain(DATA_TABLE_STYLES.headerCell);
    expect(header.className).toContain(TABLE_ROW_DENSE.headerCell);

    // Ячейки тела: каждая на `TABLE_ROW_DENSE.cell`, полоса тона — на первой.
    // Полоса именно на ячейке, а не на `<tr>`: таблица на `border-separate`,
    // и на строке её не видно (это же в комментарии `rowTones.ts`).
    // Угловая ячейка сброса из проверки исключена — ширина у неё своя.
    const cells = [...row.querySelectorAll("td")].filter(
      (cell) => !(cell as HTMLElement).className.includes(TABLE_CORNER_RESET_TD_CLASS),
    ) as HTMLElement[];
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.className).toContain(TABLE_ROW_DENSE.cell);
    }
    expect(cells[0]!.className).toContain(ROW_TONE_STRIPE.active);
  });
});
