/**
 * Групповое состояние доски — один источник для десктопной и телефонной
 * таблиц (#345, ревью #283 п. 2).
 *
 * Тест пинит контракт «шапка группы знает всё о группе сама»: суммы по
 * колонкам, записанный факт, число доводимых строк и причину недоступности
 * завершения группы. Раскладки (desktop/mobile) берут эти числа и ничего не
 * пересчитывают — иначе шапка таблицы и шапка второй раскладки снова
 * разойдутся, как расходились `parseFloat` против `toQtyInteger`.
 */

import { describe, expect, it } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { buildTaskGroupView } from "./boardGroupView";
import { getCompletionBlockReason } from "./taskStatus";

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

const group = (...tasks: SectionBoardTask[]) => ({ key: "group-1", tasks });

describe("buildTaskGroupView: суммы группы считаются один раз", () => {
  it("складывает количества по всем строкам группы", () => {
    const view = buildTaskGroupView(
      group(
        makeTask({
          id: 1,
          planned_quantity: "10",
          cache: {
            ...makeTask().cache,
            issued_quantity: "10",
            completed_quantity: "4",
            rejected_quantity: "1",
            transferred_quantity: "3",
            remaining_quantity: "6",
          },
        }),
        makeTask({
          id: 2,
          planned_quantity: "20",
          cache: {
            ...makeTask().cache,
            issued_quantity: "20",
            completed_quantity: "6",
            rejected_quantity: "2",
            transferred_quantity: "7",
            remaining_quantity: "11",
          },
        }),
      ),
      { isCollapsed: true, isBulkMode: false, allSelected: false },
    );

    expect(view.taskCount).toBe(2);
    expect(view.planQty).toBe(30);
    expect(view.issuedQty).toBe(30);
    expect(view.goodQty).toBe(10);
    expect(view.defectQty).toBe(3);
    expect(view.transferredQty).toBe(10);
    expect(view.remainingQty).toBe(17);
  });

  it("дробное количество округляется по строке, а не по сумме", () => {
    // Две строки по «2,4»: `parseFloat`-сумма дала бы шапке 4,8 (на экране —
    // «5»), а разбор ввода видит каждую строку отдельно и округляет её до 2.
    // Расхождение шапки с вводом и закрывал этот пункт ревью (#283 п. 2).
    const view = buildTaskGroupView(
      group(
        makeTask({ id: 1, cache: { ...makeTask().cache, completed_quantity: "2.4" } }),
        makeTask({ id: 2, cache: { ...makeTask().cache, completed_quantity: "2.4" } }),
      ),
      { isCollapsed: false, isBulkMode: true, allSelected: false },
    );

    expect(view.goodQty).toBe(4);
  });

  it("мусор и пустая строка в кэше дают ноль, а не NaN", () => {
    const view = buildTaskGroupView(
      group(
        makeTask({ id: 1, cache: { ...makeTask().cache, completed_quantity: "" } }),
        makeTask({ id: 2, cache: { ...makeTask().cache, completed_quantity: "—" } }),
      ),
      { isCollapsed: false, isBulkMode: false, allSelected: false },
    );

    expect(view.goodQty).toBe(0);
    expect(Number.isNaN(view.goodQty)).toBe(false);
  });
});

describe("buildTaskGroupView: шапка группы и завершение", () => {
  it("свёрнутость и выделение — из общего состояния шапки", () => {
    const collapsed = buildTaskGroupView(group(makeTask(), makeTask({ id: 2 })), {
      isCollapsed: true,
      isBulkMode: false,
      allSelected: false,
    });
    expect(collapsed.isCollapsed).toBe(true);
    expect(collapsed.collapseTitle).toBe("Раскрыть");

    const selected = buildTaskGroupView(group(makeTask(), makeTask({ id: 2 })), {
      isCollapsed: false,
      isBulkMode: true,
      allSelected: true,
    });
    expect(selected.allSelected).toBe(true);
    expect(selected.collapseTitle).toBe("Скрыть");
  });

  it("пока в группе есть доводимая строка, групповое завершение доступно", () => {
    const tasks = [
      makeTask({ id: 1, status: "in_progress" }),
      makeTask({ id: 2, status: "waiting_previous" }),
    ];
    const view = buildTaskGroupView(group(...tasks), {
      isCollapsed: false,
      isBulkMode: false,
      allSelected: false,
    });

    expect(view.completableCount).toBe(1);
    expect(view.completeReason).toBeNull();
  });

  it("все строки недоводимы — причина называет домен, а не «нет кнопки»", () => {
    const tasks = [
      makeTask({ id: 1, status: "waiting_previous" }),
      makeTask({ id: 2, status: "completed" }),
    ];
    const view = buildTaskGroupView(group(...tasks), {
      isCollapsed: false,
      isBulkMode: false,
      allSelected: false,
    });

    expect(view.completableCount).toBe(0);
    expect(view.completeReason).toBe(getCompletionBlockReason(tasks[0]));
    expect(actionReasonText(view.completeReason!)).not.toBe("");
  });
});
