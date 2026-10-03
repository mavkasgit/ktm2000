import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
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
  createDailyPlan: vi.fn(),
}));

// Доска подменена — тест про то, какие задания страница отдаёт вкладке «План»
// и что уходит в `work_task_ids`. Мок повторяет все три пути выделения, какими
// пользуется настоящая доска: клик по строке, «Выделить все» по нарисованным
// строкам и клик по шапке группы. Выделение переживает смену вкладки — как
// переживает и настоящий контроллер, — поэтому скрытое задание может остаться
// в выборе, и страница обязана срезать его сама.
vi.mock("../components/SectionTasksBoard", () => ({
  SectionTasksBoard: (props: {
    tasks: { id: number }[];
    toolbar?: ReactNode;
    bulkSelection?: {
      selectOne: (id: number, checked?: boolean) => void;
      isSelected: (id: number) => boolean;
    };
    onSelectAllVisible?: (ids: number[]) => void;
  }) => (
    <div>
      <div>{props.toolbar}</div>
      <ul data-testid="board">
        {props.tasks.map((task) => (
          <li key={task.id}>
            <button
              type="button"
              onClick={() => props.bulkSelection?.selectOne(task.id)}
              aria-label={`строка ${task.id}`}
            />
            <span>{props.bulkSelection?.isSelected(task.id) ? "выбрано" : "не выбрано"}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        aria-label="выделить все"
        onClick={() => props.onSelectAllVisible?.(props.tasks.map((task) => task.id))}
      />
      <button
        type="button"
        aria-label="выделить группу"
        onClick={() => {
          for (const task of props.tasks) props.bulkSelection?.selectOne(task.id, true);
        }}
      />
    </div>
  ),
}));

// Панель подменена: страница владеет отбором и мутацией, панель только сообщает
// о кликах и показывает счётчик, который обязан совпадать с отправкой.
vi.mock("../components/DailyPlansPanel", () => ({
  DailyPlansPanel: (props: {
    selectedTaskCount?: number;
    onCreatePlan?: (planDate: string) => void;
    onCreateModeChange?: (creating: boolean) => void;
    plans: unknown[];
  }) => (
    <div>
      <span data-testid="selected-count">{props.selectedTaskCount ?? 0}</span>
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
  getDailyPlanComposition,
  getSectionBoard,
  getSectionsSummary,
  getSectionDailyStats,
  listDailyPlans,
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

const FREE_TASK = makeTask({ id: 1, display_sku: "SKU-FREE" });
const TAKEN_TASK = makeTask({ id: 2, display_sku: "SKU-TAKEN", in_daily_plan: true });

function board(): SectionBoardResponse {
  return {
    section_id: 2,
    tasks: [FREE_TASK, TAKEN_TASK],
    available_operations: [],
    total: 2,
    limit: 50,
    offset: 0,
  };
}

/** Идентификаторы заданий, нарисованных доской: у каждой строки своя кнопка. */
function renderedIds(): number[] {
  return Array.from(
    screen.getAllByTestId("board").flatMap((node) => Array.from(node.querySelectorAll("li"))),
    (li) => {
      const button = li.querySelector("button");
      return Number(button?.getAttribute("aria-label")?.replace("строка ", ""));
    },
  );
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

/** `work_task_ids` из единственного вызова `createDailyPlan`. */
function sentTaskIds(): number[] {
  return vi.mocked(createDailyPlan).mock.calls[0]![0].work_task_ids;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([section]);
  vi.mocked(getSectionBoard).mockResolvedValue(board());
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 2, daily_stats: [] });
  vi.mocked(getDailyPlanComposition).mockResolvedValue({ items: [] });
  vi.mocked(createDailyPlan).mockResolvedValue({
    id: 1,
    section_id: 2,
    plan_date: "2026-10-01",
    created_at: "2026-10-01T06:00:00Z",
    created_by: 1,
    item_count: 1,
    progress_percent: 0,
  });
});

/** Вкладка «План» без выбранного плана — режим, в котором задание выбирают. */
async function openPlanCreationMode() {
  renderPage();
  await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));
  fireEvent.click(screen.getByRole("button", { name: "План" }));
  fireEvent.click(await screen.findByRole("button", { name: "начать создание" }));
}

describe("SectionsTasksPage: вкладка «План» в режиме просмотра", () => {
  it("показывает и занятое планом задание — скрытие принадлежит только созданию", async () => {
    renderPage();
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));

    // Вкладка «План» без выбранного плана — «все актуальные задания участка»
    // (docs/daily-plans-spec.md, «Режим `План`»). Регресс: скрытие занятых
    // из #301 применялось и здесь, и «Все задания участка» показывала только
    // свободные строки — половина картины участка пропадала без причины.
    fireEvent.click(screen.getByRole("button", { name: "План" }));

    await waitFor(() => expect(renderedIds()).toEqual([FREE_TASK.id, TAKEN_TASK.id]));
  });
});

describe("SectionsTasksPage: кандидаты дневного плана", () => {
  it("в режиме создания скрывает задание, уже включённое в план", async () => {
    await openPlanCreationMode();

    expect(renderedIds()).toEqual([FREE_TASK.id]);
  });

  it("клик по строке не добавляет скрытое задание: его негде кликать", async () => {
    await openPlanCreationMode();

    fireEvent.click(screen.getByRole("button", { name: `строка ${FREE_TASK.id}` }));

    expect(screen.getByTestId("selected-count").textContent).toBe("1");
  });

  it("«Выделить все» берёт только нарисованные строки", async () => {
    await openPlanCreationMode();

    fireEvent.click(screen.getByRole("button", { name: "выделить все" }));
    // Счётчик проверяется до отправки: после успеха панель выходит из режима
    // создания и выбор сбрасывается.
    expect(screen.getByTestId("selected-count").textContent).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "создать план" }));

    await waitFor(() => expect(createDailyPlan).toHaveBeenCalled());
    expect(sentTaskIds()).toEqual([FREE_TASK.id]);
  });

  it("клик по шапке группы не добавляет скрытое задание", async () => {
    await openPlanCreationMode();

    fireEvent.click(screen.getByRole("button", { name: "выделить группу" }));
    fireEvent.click(screen.getByRole("button", { name: "создать план" }));

    await waitFor(() => expect(createDailyPlan).toHaveBeenCalled());
    expect(sentTaskIds()).toEqual([FREE_TASK.id]);
  });

  it("выделение, оставшееся от вкладки «Задания», не уходит в план и не считается", async () => {
    renderPage();
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));

    // Вкладка «Задания» показывает задание плана — там скрытия нет, и мастер
    // мог отметить его чекбоксом. Выбор живёт в контроллере и переживает
    // переключение вкладок: на вкладке «План» строки уже нет, а выделение —
    // есть.
    fireEvent.click(screen.getByRole("button", { name: `строка ${TAKEN_TASK.id}` }));
    fireEvent.click(screen.getByRole("button", { name: "План" }));
    fireEvent.click(await screen.findByRole("button", { name: "начать создание" }));

    expect(renderedIds()).toEqual([FREE_TASK.id]);
    expect(screen.getByTestId("selected-count").textContent).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "создать план" }));
    expect(createDailyPlan).not.toHaveBeenCalled();
  });

  it("счётчик равен числу реально отправленных заданий", async () => {
    await openPlanCreationMode();

    fireEvent.click(screen.getByRole("button", { name: "выделить все" }));

    const counted = Number(screen.getByTestId("selected-count").textContent);
    fireEvent.click(screen.getByRole("button", { name: "создать план" }));
    await waitFor(() => expect(createDailyPlan).toHaveBeenCalled());

    const sent = vi.mocked(createDailyPlan).mock.calls[0]![0].work_task_ids;
    expect(counted).toBe(sent.length);
    expect(sent).not.toContain(TAKEN_TASK.id);
  });
});