/**
 * «Участки» на телефоне (#345): карточки — только выбор участка, задания —
 * строка таблицы.
 *
 * Проверяется склейка двух решений, которую порознь уже держат
 * `SectionSwitcherTiles` и `SectionTasksBoard.mobileTable.test.tsx`: на узком
 * экране страница действительно рисует плитки участков и ту же таблицу доски,
 * а не карточку задания. Десктопная раскладка и порядок её колонок — в
 * `SectionTasksBoard.mobileTable.test.tsx` (там же общий контракт раскладок).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";

vi.mock("@/shared/api/client", () => ({
  API_BASE_URL: "/api",
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { id: 1, email: "a@b.c", full_name: "A", role: "admin", section_id: null, is_active: true },
    }),
  },
  getErrorMessage: (e: unknown) => String(e),
}));

vi.mock("@/entities/auth/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: 1, username: "op", full_name: "Оператор", role: "admin" },
    rolesCatalog: [],
    roleLabel: (role: string) => role,
    roleSections: () => [],
    isAuthenticated: true,
    isLoading: false,
    loginWithToken: async () => {},
    logout: () => {},
    refreshUser: async () => {},
  }),
}));

vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/shopfloor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/shopfloor")>()),
  getSectionBoard: vi.fn(),
  getSectionsSummary: vi.fn(),
  listDailyPlans: vi.fn(),
  getSectionDailyStats: vi.fn(),
}));

import { listSections, type Section } from "@/shared/api/sections";
import {
  getSectionBoard,
  getSectionsSummary,
  listDailyPlans,
  getSectionDailyStats,
  type SectionBoardResponse,
  type SectionBoardTask,
} from "@/shared/api/shopfloor";
import { stubViewportWidth } from "@/shared/lib/testViewport";
import { SectionsTasksPage } from "./SectionsTasksPage";

const section = (id: number, name: string): Section => ({
  id,
  code: `S${id}`,
  name,
  description: null,
  sort_order: id,
  is_active: true,
  type: "production",
  icon: null,
  icon_color: null,
});

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-MOBILE",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    is_significant: true,
    planned_quantity: "10",
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "10",
    },
    previous_stage: null,
    next_task_id: null,
    next_task_status: null,
    next_operation_name: null,
    source_ref: null,
    source_payload: {},
    source_fingerprint: null,
    input_sku: "SKU-MOBILE",
    output_sku: "SKU-MOBILE",
    display_sku: "SKU-MOBILE",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

function board(sectionId: number, tasks: SectionBoardTask[] = []): SectionBoardResponse {
  return {
    section_id: sectionId,
    tasks,
    available_operations: [],
    total: tasks.length,
    limit: 50,
    offset: 0,
  };
}

function renderPage(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/section-tasks", element: <SectionsTasksPage /> },
      { path: "/section-tasks/:sectionId", element: <SectionsTasksPage /> },
    ],
    { initialEntries: [initialEntry] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  stubViewportWidth(390);
  vi.mocked(listSections).mockResolvedValue([section(2, "Упаковка"), section(8, "Сверловка")]);
  vi.mocked(getSectionBoard).mockImplementation(async (id: number) =>
    id === 2 ? board(id, [makeTask()]) : board(id),
  );
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 0, daily_stats: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SectionsTasksPage на телефоне: карточки выбора участка и таблица заданий", () => {
  it("выбор участка — карточки, а задание — строка таблицы, не карточка", async () => {
    const { container } = renderPage("/section-tasks/2");

    // Карточка выбора участка остаётся: заголовок списка и кнопка-плитка.
    expect(await screen.findByText("Выберите рабочий участок")).toBeTruthy();
    const tile = await screen.findByRole("button", { name: /^Упаковка/ });
    expect(tile.getAttribute("aria-pressed")).toBe("true");

    // Задание приходит строкой доски, а не вторым слоем карточек.
    const row = await screen.findByText("SKU-MOBILE");
    const taskRow = row.closest('tr[data-row-kind="board-task"]') as HTMLElement | null;
    expect(taskRow, "строка задания на доске участка").toBeTruthy();
    expect(container.querySelector('div[data-task-id="1"]')).toBeNull();

    // Мобильная раскладка: профиль закреплён слева, действия — справа.
    expect(taskRow!.querySelector('[data-sticky="profile"]')).toBeTruthy();
    expect(taskRow!.querySelector('[data-sticky="actions"]')).toBeTruthy();
  });
});
