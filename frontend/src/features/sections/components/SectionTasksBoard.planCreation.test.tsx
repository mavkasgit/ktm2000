/**
 * Отбор режима создания дневного плана на самой доске (#301).
 *
 * Контракт, который защищают тесты: скрытое задание нельзя выделить ни кликом
 * по строке, ни «Выделить все», ни кликом по шапке группы; когда кандидатов не
 * осталось, доска отвечает коротким «Нет заданий» — тем же текстом, что и
 * вкладка «Задания», без пояснений вида «всё занято».
 */

import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { useBulkSelection } from "@/shared/bulk";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { SectionTasksBoard } from "./SectionTasksBoard";

const PROFILE: GroupingProfile = {
  id: "sku",
  name: "Артикул + размер",
  criteria: ["productSku"],
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
const TAKEN_TASK = makeTask({ id: 2, display_sku: "SKU-TAKEN" });

function Harness({ tasks }: { tasks: SectionBoardTask[] }) {
  const [bulkMode] = useState(true);
  const bulkSelection = useBulkSelection<number>();
  return (
    <>
      <span data-testid="selected">{[...bulkSelection.selectedIds].join(",")}</span>
      <SectionTasksBoard
        tasks={tasks}
        total={tasks.length}
        isLoading={false}
        mode={{ active: true, waiting: true, completed: false }}
        onModeChange={vi.fn()}
        onAction={vi.fn()}
        profile={PROFILE}
        bulkMode={bulkMode}
        bulkSelection={bulkSelection}
        onVisibleTaskIdsChange={vi.fn()}
        onSelectAllVisible={(ids) => bulkSelection.selectAll(ids)}
        page={1}
        setPage={vi.fn()}
        limit={50 as PageLimitOption}
        setLimit={vi.fn()}
        totalPages={1}
        rangeLabel=""
        onServerQueryChange={vi.fn()}
      />
    </>
  );
}

/** Таблица доски на десктопе: рядом рисуются и мобильные карточки. */
function desktop(): HTMLElement {
  const table = document.querySelector("table");
  if (!table) throw new Error("таблица доски не найдена");
  return table as HTMLElement;
}

/** Строка задания по идентификатору: у доски он в `data-task-id` (адрес для e2e). */
function rowOf(taskId: number): HTMLElement {
  const row = document.querySelector(`tr[data-task-id="${taskId}"]`);
  if (!row) throw new Error(`строка задания ${taskId} не найдена`);
  return row as HTMLElement;
}

/**
 * Шапка группы: строка доски без `data-task-id` — у заданий он есть, у шапки
 * нет. Клик по ней и есть групповое выделение.
 */
function groupHeader(): HTMLElement {
  const header = Array.from(desktop().querySelectorAll("tbody tr")).find(
    (row) => !row.hasAttribute("data-task-id"),
  );
  if (!header) throw new Error("шапка группы не найдена");
  return header as HTMLElement;
}

describe("SectionTasksBoard: отбор режима создания плана", () => {
  it("«Выделить все» отдаёт странице только нарисованные строки", () => {
    render(<Harness tasks={[FREE_TASK]} />);

    fireEvent.click(screen.getByRole("button", { name: /Выделить все/ }));

    expect(screen.getByTestId("selected").textContent).toBe(String(FREE_TASK.id));
  });

  it("клик по строке выбирает именно её", () => {
    render(<Harness tasks={[FREE_TASK]} />);

    fireEvent.click(rowOf(FREE_TASK.id));

    expect(screen.getByTestId("selected").textContent).toBe(String(FREE_TASK.id));
  });

  it("клик по шапке группы выбирает строки группы, а не что-то ещё", () => {
    render(<Harness tasks={[FREE_TASK, makeTask({ id: 3, display_sku: "SKU-FREE" })]} />);

    fireEvent.click(groupHeader());

    const selected = screen.getByTestId("selected").textContent ?? "";
    expect(selected.split(",").sort()).toEqual([String(FREE_TASK.id), "3"]);
    expect(selected).not.toContain(String(TAKEN_TASK.id));
  });

  it("без кандидатов доска отвечает «Нет заданий» без пояснений", () => {
    render(<Harness tasks={[]} />);

    expect(screen.getByText("Нет заданий")).toBeDefined();
    expect(screen.queryByText(/всё занято/i)).toBeNull();
    expect(screen.queryByText(/в плане/i)).toBeNull();
  });
});