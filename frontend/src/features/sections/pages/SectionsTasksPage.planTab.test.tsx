import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
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
  getDailyPlanComposition: vi.fn(),
}));

// Доска подменена списком артикулов: тест про то, какой набор заданий страница
// вообще отдаёт вкладке «План». Слот `toolbar` доска держит сама — мок обязан
// его отрисовать, иначе кнопка печати не попадёт в дерево.
vi.mock("../components/SectionTasksBoard", () => ({
  SectionTasksBoard: (props: { tasks: { id: number; display_sku: string }[]; toolbar?: ReactNode }) => (
    <div>
      <div data-testid="board-toolbar">{props.toolbar}</div>
      <ul data-testid="board">
        {props.tasks.map((task) => (
          <li key={task.id}>{task.display_sku}</li>
        ))}
      </ul>
    </div>
  ),
}));

// Панель подменена списком планов: страница владеет выбором, панель только
// сообщает о клике.
vi.mock("../components/DailyPlansPanel", () => ({
  DailyPlansPanel: (props: { selectedPlanIds: Set<number>; onSelectPlan: (id: number) => void }) => (
    <div>
      <span data-testid="selected-plans">{[...props.selectedPlanIds].join(",")}</span>
      <button type="button" onClick={() => props.onSelectPlan(1)}>
        выбрать план
      </button>
    </div>
  ),
}));

// Печать подменена списком артикулов: печатается тот же набор, что и на доске.
vi.mock("../components/PlanModal", () => ({
  PlanModal: (props: { tasks: { id: number; display_sku: string }[] }) => (
    <ul data-testid="print">
      {props.tasks.map((task) => (
        <li key={task.id}>{task.display_sku}</li>
      ))}
    </ul>
  ),
}));

import { listSections, type Section } from "@/shared/api/sections";
import {
  getDailyPlanComposition,
  getSectionBoard,
  getSectionsSummary,
  listDailyPlans,
  getSectionDailyStats,
  type SectionBoardResponse,
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

const ACTUAL_TASK = makeTask({ id: 1, sequence: 1, display_sku: "SKU-ACTUAL" });
const COMPLETED_TASK = makeTask({
  id: 2,
  sequence: 2,
  display_sku: "SKU-COMPLETED",
  status: "completed",
  cache: {
    available_quantity: "0",
    issued_quantity: "10",
    completed_quantity: "10",
    transferred_quantity: "10",
    received_quantity: "10",
    rejected_quantity: "0",
    remaining_quantity: "0",
  },
});

function board(): SectionBoardResponse {
  return {
    section_id: 2,
    tasks: [ACTUAL_TASK, COMPLETED_TASK],
    available_operations: [],
    total: 2,
    limit: 50,
    offset: 0,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/section-tasks/:sectionId", element: <SectionsTasksPage /> }],
    { initialEntries: ["/section-tasks/2"] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </QueryClientProvider>,
  );
}

async function openPlanTab() {
  renderPage();
  await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));
  fireEvent.click(screen.getByRole("button", { name: "План" }));
  await waitFor(() => expect(screen.getAllByTestId("board").length).toBeGreaterThan(0));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([section]);
  vi.mocked(getSectionBoard).mockResolvedValue(board());
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 2, daily_stats: [] });
  vi.mocked(getDailyPlanComposition).mockResolvedValue({ items: [] });
});

describe("SectionsTasksPage: вкладка «План»", () => {
  it("без выбранного плана не показывает завершённые задания участка", async () => {
    await openPlanTab();
    const board = within(screen.getByTestId("board"));

    expect(board.getByText("SKU-ACTUAL")).toBeDefined();
    expect(board.queryByText("SKU-COMPLETED")).toBeNull();
  });

  it("печатает тот же набор, что и показывает: без плана завершённых нет", async () => {
    await openPlanTab();
    fireEvent.click(screen.getByRole("button", { name: "Печать плана" }));
    const print = within(screen.getByTestId("print"));

    expect(print.getByText("SKU-ACTUAL")).toBeDefined();
    expect(print.queryByText("SKU-COMPLETED")).toBeNull();
  });

  it("показывает завершённую строку в составе выбранного плана", async () => {
    vi.mocked(listDailyPlans).mockResolvedValue([
      {
        id: 1,
        section_id: 2,
        plan_date: "2026-10-01",
        created_at: "2026-10-01T06:00:00Z",
        created_by: 1,
        item_count: 1,
        progress_percent: 100,
      },
    ]);
    vi.mocked(getDailyPlanComposition).mockResolvedValue({
      items: [
        { id: 1, daily_plan_id: 1, work_task_id: COMPLETED_TASK.id, task: COMPLETED_TASK, progress_percent: 100 },
      ],
    });

    await openPlanTab();
    fireEvent.click(screen.getAllByRole("button", { name: "выбрать план" })[0]!);
    await waitFor(() => expect(screen.getByTestId("selected-plans").textContent).toBe("1"));

    const board = within(screen.getByTestId("board"));
    await waitFor(() => expect(board.getByText("SKU-COMPLETED")).toBeDefined());
    expect(board.queryByText("SKU-ACTUAL")).toBeNull();
  });
});
