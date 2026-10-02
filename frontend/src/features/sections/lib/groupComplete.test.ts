import { describe, expect, it } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { planGroupComplete } from "./groupComplete";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    status: "in_work",
    operation_name: "Пила",
    operation_code: "SAW",
    sequence: 1,
    product_sku: "ЮП-2083",
    display_sku: "ЮП-2083",
    planned_quantity: "100",
    is_significant: true,
    transforms_dimensions: false,
    cache: {
      issued_quantity: "100",
      completed_quantity: "0",
      rejected_quantity: "0",
      available_quantity: "0",
      transferred_quantity: "0",
      remaining_quantity: "100",
    },
    ...overrides,
  } as SectionBoardTask;
}

describe("planGroupComplete", () => {
  it("раскладывает цель группы по строкам последовательно", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "50" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "50" } }),
      makeTask({ id: 3, cache: { ...makeTask().cache, issued_quantity: "100" } }),
    ];

    const { entries, skipped } = planGroupComplete(tasks, "120", "5");

    expect(skipped).toEqual([]);
    expect(entries.map((entry) => [entry.taskId, entry.good.quantity, entry.defect.quantity])).toEqual([
      [1, 50, 5],
      [2, 50, 0],
      [3, 20, 0],
    ]);
  });

  it("цель, которой не хватило ни одной строке, попадает в пропущенные", () => {
    const tasks = [makeTask({ id: 1 }), makeTask({ id: 2 })];

    const { entries, skipped } = planGroupComplete(tasks, "0", "0");

    expect(entries).toEqual([]);
    expect(skipped.map((task) => task.id)).toEqual([1, 2]);
  });

  it("строка, которой цель не досталась, уходит в пропущенные, а не в пачку", () => {
    const tasks = [
      makeTask({ id: 1, cache: { ...makeTask().cache, issued_quantity: "50" } }),
      makeTask({ id: 2, cache: { ...makeTask().cache, issued_quantity: "50" } }),
    ];

    const { entries, skipped } = planGroupComplete(tasks, "50", "0");

    expect(entries.map((entry) => entry.taskId)).toEqual([1]);
    expect(skipped.map((task) => task.id)).toEqual([2]);
  });

  it("задание, которое завершить нельзя, пропускается и в пачку не попадает", () => {
    const tasks = [makeTask({ id: 1 }), makeTask({ id: 2, status: "cancelled" })];

    const { entries, skipped } = planGroupComplete(tasks, "10", "0");

    expect(entries.map((entry) => entry.taskId)).toEqual([1]);
    expect(skipped.map((task) => task.id)).toEqual([2]);
  });

  it("без завершаемых заданий пачка пустая, а все строки — в пропущенных", () => {
    const tasks = [makeTask({ id: 1, status: "cancelled" }), makeTask({ id: 2, status: "done" })];

    const { entries, skipped } = planGroupComplete(tasks, "10", "0");

    expect(entries).toEqual([]);
    expect(skipped.map((task) => task.id)).toEqual([1, 2]);
  });
});
