import { describe, expect, it } from "vitest";
import {
  initGroup,
  distributeAddAndDefect,
  getTaskProgress,
  toInteger,
  type BulkOpGroup,
  type MockTask,
} from "../lib/bulkOperations";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type MakeTaskOverrides = {
  id: number;
  product_sku?: string;
  operation_name?: string;
  operation_code?: string | null;
  planned_quantity?: string;
  cache?: Partial<MockTask["cache"]>;
};

function makeTask(overrides: MakeTaskOverrides): MockTask {
  return {
    id: overrides.id,
    product_sku: overrides.product_sku ?? "TEST-001",
    operation_name: overrides.operation_name ?? "Test Op",
    operation_code: overrides.operation_code ?? null,
    planned_quantity: overrides.planned_quantity ?? "100",
    cache: {
      available_quantity: overrides.cache?.available_quantity ?? "100",
      issued_quantity: overrides.cache?.issued_quantity ?? "0",
      in_work_quantity: overrides.cache?.in_work_quantity ?? "0",
      completed_quantity: overrides.cache?.completed_quantity ?? "0",
      transferred_quantity: overrides.cache?.transferred_quantity ?? "0",
      rejected_quantity: overrides.cache?.rejected_quantity ?? "0",
      remaining_quantity: overrides.cache?.remaining_quantity ?? "100",
    },
  };
}

function makeGroup(tasks: MockTask[]): BulkOpGroup {
  return initGroup(tasks);
}

// ---------------------------------------------------------------------------
// initGroup defaults
// ---------------------------------------------------------------------------

describe("initGroup defaults", () => {
  it("empty row — addQty defaults to 0, defectQty defaults to 0", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: {
        issued_quantity: "0",
        completed_quantity: "0",
        transferred_quantity: "0",
        rejected_quantity: "0",
      },
    });
    const group = makeGroup([task]);

    expect(group.totalPlan).toBe(100);
    expect(group.totalCompleted).toBe(0);
    expect(group.addQty).toBe("0");
    expect(group.defectQty).toBe("0");
    expect(group.confirmed).toBe(false);
    expect(group.taskAddQty[1]).toBe(0);
    expect(group.taskDefectQty[1]).toBe(0);
  });

  it("reads cache totals (issued, completed, etc) for read-only columns", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: {
        issued_quantity: "100",
        completed_quantity: "60",
        in_work_quantity: "40",
        transferred_quantity: "10",
        rejected_quantity: "5",
        remaining_quantity: "25",
      },
    });
    const group = makeGroup([task]);

    expect(group.totalIssued).toBe(100);
    expect(group.totalCompleted).toBe(60);
    expect(group.totalInWork).toBe(40);
    expect(group.totalTransferred).toBe(10);
    expect(group.totalRejected).toBe(5);
    expect(group.totalRemaining).toBe(25);
  });
});

// ---------------------------------------------------------------------------
// distributeAddAndDefect
// ---------------------------------------------------------------------------

describe("distributeAddAndDefect", () => {
  it("partial completion — small addQty distributed to first task only", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "50", completed_quantity: "0" },
    });
    const group = makeGroup([task]);

    const after = distributeAddAndDefect({ ...group, addQty: "3" });
    expect(toInteger(after.addQty)).toBe(3);
    expect(after.taskAddQty[1]).toBe(3);
    expect(after.taskDefectQty[1]).toBe(0);
  });

  it("addQty above plan still goes through (no cap)", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "0" },
    });
    const group = makeGroup([task]);

    const after = distributeAddAndDefect({ ...group, addQty: "150" });
    expect(after.taskAddQty[1]).toBe(150);
  });

  it("multi-task: full addQty goes to first task (sequential distribution)", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "100", cache: { issued_quantity: "100" } }),
      makeTask({ id: 2, planned_quantity: "200", cache: { issued_quantity: "200" } }),
    ];
    const group = makeGroup(tasks);

    const after = distributeAddAndDefect({ ...group, addQty: "50" });
    expect(after.taskAddQty[1]).toBe(50);
    expect(after.taskAddQty[2]).toBe(0);
  });

  it("defectQty distributed independently from addQty", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "0" },
    });
    const group = makeGroup([task]);

    const after = distributeAddAndDefect({ ...group, addQty: "10", defectQty: "2" });
    expect(after.taskAddQty[1]).toBe(10);
    expect(after.taskDefectQty[1]).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// progress display
// ---------------------------------------------------------------------------

describe("progress display", () => {
  it("shows completed/planned for each task", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "500", cache: { completed_quantity: "200" } }),
      makeTask({ id: 2, planned_quantity: "300", cache: { completed_quantity: "100" } }),
    ];
    const group = makeGroup(tasks);
    expect(getTaskProgress(group)).toBe("200/500, 100/300");
  });

  it("shows zeros for empty tasks", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "100", cache: { completed_quantity: "0" } }),
      makeTask({ id: 2, planned_quantity: "200", cache: { completed_quantity: "0" } }),
    ];
    const group = makeGroup(tasks);
    expect(getTaskProgress(group)).toBe("0/100, 0/200");
  });
});
