/**
 * Причина недоступности «Завершить» напечатана рядом с кнопкой (#193).
 *
 * Контракт, который защищают тесты: оператор видит, почему кнопка не
 * нажимается, не наводя мышь, — на обоих экранах доски (строка таблицы и
 * мобильная карточка). У доступного задания, наоборот, рядом с работающей
 * кнопкой не должно быть ни текста, ни подсказки: лишних слов быть не должно.
 *
 * Формулировку не пиню: ожидаемый текст берётся из словаря по коду, который
 * вернул `getCompletionBlockReason` для конкретного задания.
 */

import { render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { getCompletionBlockReason } from "../lib/taskStatus";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { ACTION_REASON_TEXT, actionReasonText } from "@/shared/lib/actionReasons";
import { SectionTasksBoard, type TaskBoardViewMode } from "./SectionTasksBoard";

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

/** Задание, по которому весь выданный материал обработан. */
function fullyProcessedTask(): SectionBoardTask {
  return makeTask({
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
      completed_quantity: "10",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "10",
    },
  });
}

function renderBoard(tasks: SectionBoardTask[]): HTMLElement {
  const mode: TaskBoardViewMode = { active: true, waiting: true, completed: true };
  const { container } = render(
    <SectionTasksBoard
      tasks={tasks}
      total={tasks.length}
      isLoading={false}
      mode={mode}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
      profile={PROFILE}
      showCompletedStatus
      page={1}
      setPage={vi.fn()}
      limit={50 as PageLimitOption}
      setLimit={vi.fn()}
      totalPages={1}
      rangeLabel=""
      onServerQueryChange={vi.fn()}
    />,
  );
  return container;
}

/** Строка таблицы доски — десктопный экран. */
function tableRow(container: HTMLElement): HTMLElement {
  const table = container.querySelector("table");
  if (!table) throw new Error("доска не отрисовала таблицу");
  const rows = table.querySelectorAll('tr[data-row-kind="board-task"]');
  if (rows.length !== 1) throw new Error(`ожидалась одна строка задания, найдено ${rows.length}`);
  return rows[0] as HTMLElement;
}

/** Блок мобильных карточек — второй экран того же задания. */
function mobileBlock(container: HTMLElement): HTMLElement {
  const block = container.querySelector('div[class*="md:hidden"]');
  if (!block) throw new Error("доска не отрисовала мобильный блок");
  return block as HTMLElement;
}

function completeButton(scope: HTMLElement): HTMLElement {
  return within(scope).getByRole("button", { name: "Завершить" });
}

/**
 * Тексты причин, напечатанные РЯДОМ с кнопкой: подписи-элементы, лежащие с
 * ней в одной строке. `title` самой кнопки сюда не попадает — это не элемент
 * и без наведения мыши оператор его всё равно не прочитает.
 */
function reasonTextsBeside(button: HTMLElement): string[] {
  const row = button.parentElement;
  if (!row) throw new Error("кнопка вне контейнера");
  return Array.from(row.children)
    .filter((node): node is HTMLElement => node.tagName === "SPAN" && node.hasAttribute("title"))
    .map((node) => node.textContent ?? "");
}

describe("SectionTasksBoard: причина недоступности «Завершить» видна на экране", () => {
  it.each([
    [
      "сырьё с предыдущего этапа не поступило",
      makeTask({ status: "ready", previous_stage: null }),
    ],
    ["ожидает предыдущий участок", makeTask({ status: "waiting_previous" })],
    ["уже закрыт", makeTask({ status: "completed" })],
    ["этап пропущен", makeTask({ status: "skipped" })],
    ["факт уже внесён", fullyProcessedTask()],
  ])("в строке задания: %s → текст причины рядом с кнопкой", (_case, task) => {
    const expected = actionReasonText(getCompletionBlockReason(task));
    if (!expected) throw new Error("у заблокированного задания должен быть код причины");

    const row = tableRow(renderBoard([task]));
    const button = completeButton(row);

    expect(reasonTextsBeside(button)).toEqual([expected]);
    // Причина объясняет недоступность — сама кнопка при этом заблокирована.
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("та же причина видна и на мобильной карточке", () => {
    const task = makeTask({ status: "waiting_previous" });
    const expected = actionReasonText(getCompletionBlockReason(task));
    if (!expected) throw new Error("у заблокированного задания должен быть код причины");

    const button = completeButton(mobileBlock(renderBoard([task])));

    expect(reasonTextsBeside(button)).toEqual([expected]);
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("доступное задание: рядом с кнопкой нет ни текста причины, ни подсказки", () => {
    const task = makeTask({ status: "in_progress" });
    expect(getCompletionBlockReason(task)).toBeNull();

    const container = renderBoard([task]);
    const row = tableRow(container);
    const button = completeButton(row);

    expect(reasonTextsBeside(button)).toEqual([]);
    expect((button as HTMLButtonElement).disabled).toBe(false);
    // Ни одного текста причины в строке: рядом с работающей кнопкой пусто,
    // и скрытой подсказки в тултипе строки тоже нет.
    for (const reasonText of Object.values(ACTION_REASON_TEXT)) {
      expect(row.textContent).not.toContain(reasonText);
    }

    // Тот же контракт на втором экране доски.
    const mobileButton = completeButton(mobileBlock(container));
    expect(reasonTextsBeside(mobileButton)).toEqual([]);
    expect((mobileButton as HTMLButtonElement).disabled).toBe(false);
  });
});
