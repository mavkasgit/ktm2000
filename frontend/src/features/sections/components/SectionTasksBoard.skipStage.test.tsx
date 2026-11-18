/**
 * «Пропустить этап» на доске участка (#348).
 *
 * Решение владельца: пропускать этап вручную может только admin и
 * section_manager. Кнопка — подсказка интерфейса, а не защита: сервер вернёт
 * 403 остальным ролям. Контракт здесь один — у роли без права кнопки нет
 * вовсе, у разрешённой она открывает пропуск именно выбранной строки, а у
 * уже закрытого этапа выключена.
 */

import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { SectionTasksBoard, type TaskBoardViewMode } from "./SectionTasksBoard";

const PROFILE: GroupingProfile = {
  id: "sku",
  name: "Артикул + размер",
  criteria: ["productSku"],
};

const MODE: TaskBoardViewMode = { active: true, waiting: true, completed: true };

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
      available_quantity: "10",
      issued_quantity: "10",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "10",
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

function renderBoard(
  tasks: SectionBoardTask[],
  options: { canSkipStages?: boolean; onSkipStage?: (task: SectionBoardTask) => void } = {},
) {
  return render(
    <SectionTasksBoard
      tasks={tasks}
      total={tasks.length}
      isLoading={false}
      mode={MODE}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
      profile={PROFILE}
      canSkipStages={options.canSkipStages}
      onSkipStage={options.onSkipStage}
      page={1}
      setPage={vi.fn()}
      limit={50 as PageLimitOption}
      setLimit={vi.fn()}
      totalPages={1}
      rangeLabel=""
      onServerQueryChange={vi.fn()}
    />,
  );
}

function taskRow(container: HTMLElement): HTMLElement {
  const row = container.querySelector('tr[data-row-kind="board-task"]');
  if (!row) throw new Error("доска не отрисовала строку задания");
  return row as HTMLElement;
}

const skipButton = (scope: HTMLElement) =>
  within(scope).queryByRole("button", { name: "Пропустить этап" });

describe("SectionTasksBoard: «Пропустить этап» (#348)", () => {
  it("у роли без права кнопки нет", () => {
    const { container } = renderBoard([makeTask()], { canSkipStages: false });

    expect(skipButton(taskRow(container))).toBeNull();
  });

  it("с правом кнопка открывает пропуск именно выбранного задания", () => {
    const onSkipStage = vi.fn();
    const task = makeTask({ id: 7 });
    const { container } = renderBoard([task], {
      canSkipStages: true,
      onSkipStage,
    });

    fireEvent.click(skipButton(taskRow(container))!);

    expect(onSkipStage).toHaveBeenCalledWith(task);
  });

  it.each(["completed", "cancelled", "skipped"])(
    "закрытый этап (%s) пропустить нельзя — кнопка выключена",
    (status) => {
      const { container } = renderBoard([makeTask({ status })], {
        canSkipStages: true,
        onSkipStage: vi.fn(),
      });

      const button = skipButton(taskRow(container)) as HTMLButtonElement;
      expect(button).not.toBeNull();
      expect(button.disabled).toBe(true);
    },
  );

  it("открытый этап, в том числе ожидающий сырья, пропустить можно", () => {
    const { container } = renderBoard([makeTask({ status: "waiting_previous" })], {
      canSkipStages: true,
      onSkipStage: vi.fn(),
    });

    const button = skipButton(taskRow(container)) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });
});
