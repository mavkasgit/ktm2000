import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { id: 1, email: "a@b.c", full_name: "A", role: "admin", section_id: null, is_active: true },
    }),
  },
  getErrorMessage: (e: unknown) => String(e),
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
  createDailyPlan: vi.fn(),
}));

// Доска подменена: тест про страницу — она владеет мутацией и обязана снять
// ошибку прежнего участка. Кнопка выбора задания нужна, чтобы пройти охранник
// `selectedTasks.length === 0` в обработчике создания плана.
vi.mock("../components/SectionTasksBoard", () => ({
  SectionTasksBoard: (props: { bulkSelection?: { selectOne: (id: number) => void } }) => (
    <button type="button" onClick={() => props.bulkSelection?.selectOne(1)}>
      выбрать задание
    </button>
  ),
}));

// Панель подменена: она лишь показывает то, что страница ей передала. Кнопка
// «начать создание» включает режим создания — только тогда доска получает
// контроллер выделения, а панель — обработчик создания.
vi.mock("../components/DailyPlansPanel", () => ({
  DailyPlansPanel: (props: {
    isCreating?: boolean;
    createErrorMessage?: string | null;
    onCreatePlan?: (planDate: string) => void;
    onCreateModeChange?: (creating: boolean) => void;
  }) => (
    <div>
      <span data-testid="plan-error">{props.createErrorMessage ?? "нет"}</span>
      <button type="button" onClick={() => props.onCreateModeChange?.(true)}>
        начать создание
      </button>
      <button type="button" onClick={() => props.onCreatePlan?.("2026-10-01")}>
        создать план
      </button>
    </div>
  ),
}));

import { listSections, type Section } from "@/shared/api/sections";
import {
  createDailyPlan,
  getSectionBoard,
  getSectionsSummary,
  listDailyPlans,
  getSectionDailyStats,
  type SectionBoardResponse,
  type SectionBoardTask,
} from "@/shared/api/shopfloor";
import { SectionsTasksPage } from "./SectionsTasksPage";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    is_significant: true,
    planned_quantity: "10",
    status: "ready",
    cache: {
      available_quantity: "10",
      issued_quantity: "0",
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

const board = (sectionId: number): SectionBoardResponse => ({
  section_id: sectionId,
  tasks: [makeTask()],
  available_operations: [],
  total: 1,
  limit: 50,
  offset: 0,
});

function renderPage(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/section-tasks", element: <SectionsTasksPage /> },
      { path: "/section-tasks/:sectionId", element: <SectionsTasksPage /> },
    ],
    { initialEntries: [initialEntry] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([section(2, "Пила"), section(8, "Упаковка")]);
  vi.mocked(getSectionBoard).mockImplementation(async (id: number) => board(id));
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 0, daily_stats: [] });
});

describe("SectionsTasksPage: ошибка создания плана", () => {
  it("не переносит ошибку прежнего участка на новый", async () => {
    vi.mocked(createDailyPlan).mockRejectedValue(new Error("boom"));

    renderPage("/section-tasks/2");
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));

    // Форма создания живёт на вкладке «План» — там панель получает onCreatePlan.
    fireEvent.click(screen.getByRole("button", { name: "План" }));
    fireEvent.click(screen.getByRole("button", { name: "начать создание" }));
    fireEvent.click(screen.getAllByRole("button", { name: "выбрать задание" })[0]!);
    fireEvent.click(await screen.findByRole("button", { name: "создать план" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("plan-error").some((node) => node.textContent?.includes("boom"))).toBe(true),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Упаковка/ }));
    await waitFor(async () => {
      await delay(100);
      // Ошибка создания плана относилась к прежнему участку: под новым она
      // держала бы форму создания открытой (панель гасит режим только без ошибки).
      expect(screen.getAllByTestId("plan-error").every((node) => node.textContent === "нет")).toBe(true);
    });
  });
});
