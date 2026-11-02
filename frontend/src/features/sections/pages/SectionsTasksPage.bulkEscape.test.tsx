/**
 * Escape в массовом режиме снимает выделение (#283, AC п. 4).
 *
 * Контракт, который защищает тест: Escape — это «снять выделение», а не «выйти
 * из массового режима». С непустым черновиком действие спрашивает
 * подтверждение (набранное не теряется молча), но подтверждённое действие
 * обязано оставить оператора в режиме: иначе он теряет и выделение, и режим
 * одним нажатием, хотя просил только первое.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import type { BulkDraft } from "../lib/bulkDraft";

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
  getDailyPlanComposition: vi.fn(),
  bulkCompleteTasks: vi.fn(),
}));

/**
 * Доска подменена: тест про состояние страницы, а не про её разметку. Мок
 * повторяет две вещи, которыми владеет страница, — выделение и черновик — и
 * печатает их, чтобы утверждения читались как наблюдения оператора.
 */
vi.mock("../components/SectionTasksBoard", () => ({
  SectionTasksBoard: (props: {
    bulkMode?: boolean;
    bulkDraft?: BulkDraft;
    bulkSelection?: { selectOne: (id: number, checked?: boolean) => void; isSelected: (id: number) => boolean };
    onBulkDraftChange?: (draft: BulkDraft) => void;
  }) => (
    <div>
      <output data-testid="bulk-mode">{props.bulkMode ? "включён" : "выключен"}</output>
      <output data-testid="selected">{props.bulkSelection?.isSelected(1) ? "выбрано" : "не выбрано"}</output>
      <output data-testid="draft">{JSON.stringify(props.bulkDraft ?? {})}</output>
      <button type="button" onClick={() => props.bulkSelection?.selectOne(1)}>
        выбрать строку
      </button>
      <button
        type="button"
        onClick={() => props.onBulkDraftChange?.({ 1: { good: "+3", defect: "" } })}
      >
        ввести количество
      </button>
    </div>
  ),
}));

vi.mock("../components/DailyPlansPanel", () => ({
  DailyPlansPanel: () => <div />,
}));

import { listSections, type Section } from "@/shared/api/sections";
import {
  getDailyPlanComposition,
  getSectionBoard,
  getSectionsSummary,
  getSectionDailyStats,
  listDailyPlans,
  type SectionBoardTask,
} from "@/shared/api/shopfloor";
import { SectionsTasksPage } from "./SectionsTasksPage";

const section: Section = {
  id: 2,
  code: "S2",
  name: "Пила",
  description: null,
  sort_order: 2,
  is_active: true,
  type: "production",
  icon: null,
  icon_color: null,
};

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
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
    input_sku: "SKU-A",
    output_sku: "SKU-A",
    display_sku: "SKU-A",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  // `?bulk=1` — штатный вход в массовый режим (ссылка «Групповые операции»).
  const router = createMemoryRouter(
    [{ path: "/section-tasks/:sectionId", element: <SectionsTasksPage /> }],
    { initialEntries: ["/section-tasks/2?bulk=1"] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([section]);
  vi.mocked(getSectionBoard).mockResolvedValue({
    section_id: 2,
    tasks: [makeTask()],
    available_operations: [],
    total: 1,
    limit: 50,
    offset: 0,
  });
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 2, daily_stats: [] });
  vi.mocked(getDailyPlanComposition).mockResolvedValue({ items: [] });
});

describe("SectionsTasksPage: Escape в массовом режиме", () => {
  it("с непустым черновиком подтверждённый Escape снимает выделение и остаётся в режиме", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "выбрать строку" }));
    fireEvent.click(screen.getByRole("button", { name: "ввести количество" }));
    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"+3","defect":""}}');
    expect(screen.getByTestId("bulk-mode").textContent).toBe("включён");

    fireEvent.keyDown(window, { key: "Escape" });

    // Набранное не теряется молча: Escape с черновиком спрашивает подтверждение.
    fireEvent.click(await screen.findByRole("button", { name: "Сбросить" }));

    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("не выбрано"));
    // Главное: режим не выключен — Escape просили «снять выделение», а не «выйти».
    expect(screen.getByTestId("bulk-mode").textContent).toBe("включён");
    // Снятое выделение уносит и набранное количество.
    expect(screen.getByTestId("draft").textContent).toBe("{}");
  });
});
