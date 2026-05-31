import { describe, expect, it } from "vitest";
import {
  initGroup,
  activateIssueArrow,
  activateCompleteArrow,
  getTaskProgress,
  toInteger,
  type BulkOpGroup,
  type MockTask,
} from "../lib/bulkOperations";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTask(overrides: Partial<MockTask> & { id: number }): MockTask {
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

function cascade(group: BulkOpGroup): BulkOpGroup {
  // Issue arrow → Complete arrow
  const afterIssue = activateIssueArrow(group);
  return activateCompleteArrow(afterIssue);
}

// ---------------------------------------------------------------------------
// 7 scenarios for a single task row
// ---------------------------------------------------------------------------

describe("single row — 7 fill variants", () => {
  // Variant 1: Nothing filled yet (all zeros)
  it("variant 1: empty row — all zeros", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "0", completed_quantity: "0", transferred_quantity: "0", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    expect(group.totalPlan).toBe(100);
    expect(group.totalIssued).toBe(0);
    expect(group.totalCompleted).toBe(0);
    expect(group.totalTransferred).toBe(0);
    expect(group.issueQty).toBe("");
    expect(group.completeQty).toBe("0");
    expect(group.sendQty).toBe("0");
    expect(getTaskProgress(group)).toBe("0/100");
  });

  // Variant 2: Only issued (выдано)
  it("variant 2: only issued — issue arrow transfers to complete", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "60", completed_quantity: "0", transferred_quantity: "0", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    expect(group.totalIssued).toBe(60);

    // Activate issue arrow (empty input → uses issued - completed - defect = 60)
    const afterIssue = activateIssueArrow(group);
    expect(toInteger(afterIssue.completeQty)).toBe(60);
    expect(afterIssue.taskCompleteQty[1]).toBe(60);

    // Progress: transferred/planned = 0/100 (not transferred yet)
    expect(getTaskProgress(group)).toBe("0/100");
  });

  // Variant 3: Issued + completed (выдано + завершено)
  it("variant 3: issued + completed — complete arrow transfers to send", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "80", transferred_quantity: "0", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    expect(group.totalCompleted).toBe(80);
    expect(group.completeQty).toBe("80");

    const afterComplete = activateCompleteArrow(group);
    expect(toInteger(afterComplete.sendQty)).toBe(80);
    expect(afterComplete.taskSendQty[1]).toBe(80);
  });

  // Variant 4: Issued + completed + transferred (full cycle)
  it("variant 4: full cycle — already transferred, arrows show remaining", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "100", transferred_quantity: "100", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    expect(group.totalTransferred).toBe(100);
    expect(getTaskProgress(group)).toBe("100/100");

    // Issue arrow: issued(100) - completed(100) - defect(0) = 0, nothing to add
    const afterIssue = activateIssueArrow({ ...group, issueQty: "" });
    expect(toInteger(afterIssue.completeQty)).toBe(0);

    // Complete arrow: completed(100) - transferred(100) - defect(0) = 0
    const afterComplete = activateCompleteArrow(afterIssue);
    expect(toInteger(afterComplete.sendQty)).toBe(0);
  });

  // Variant 5: Issued + defect (брак)
  it("variant 5: issued + defect — complete arrow accounts for defect", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "70", transferred_quantity: "0", rejected_quantity: "10" },
    });
    const group = makeGroup([task]);

    expect(group.totalRejected).toBe(10);
    expect(group.defectQty).toBe("10");

    // Complete arrow: input complete(70) - input defect(10) = 60 good
    // Already completed: 70 - 0 - 10 = 60
    const afterComplete = activateCompleteArrow(group);
    expect(toInteger(afterComplete.sendQty)).toBe(60);
    expect(afterComplete.taskSendQty[1]).toBe(60);
  });

  // Variant 6: Partial transfer (частично передано)
  it("variant 6: partial transfer — complete arrow shows remaining to transfer", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "100", completed_quantity: "80", transferred_quantity: "30", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    // Already completed but not transferred: 80 - 30 - 0 = 50
    const afterComplete = activateCompleteArrow(group);
    expect(toInteger(afterComplete.sendQty)).toBe(50);
    expect(afterComplete.taskSendQty[1]).toBe(50);

    expect(getTaskProgress(group)).toBe("30/100");
  });

  // Variant 7: Issue qty filled manually + cascade
  it("variant 7: manual issueQty + cascade to send — complete arrow uses actual completed data", () => {
    const task = makeTask({
      id: 1,
      planned_quantity: "100",
      cache: { issued_quantity: "50", completed_quantity: "40", transferred_quantity: "0", rejected_quantity: "0" },
    });
    const group = makeGroup([task]);

    // User enters 30 more in issue field
    const groupWithInput = { ...group, issueQty: "30" };

    // Issue arrow: already in work (50 - 40 - 0 = 10) + new input (30, but canAdd = 100-50=50) = 40
    const afterIssue = activateIssueArrow(groupWithInput);
    expect(toInteger(afterIssue.completeQty)).toBe(40); // 10 already + 30 from input
    expect(afterIssue.taskCompleteQty[1]).toBe(40);

    // Complete arrow: input complete(40) - defect(0) = 40
    // Already completed: 40 - 0 - 0 = 40
    const afterComplete = activateCompleteArrow(afterIssue);
    expect(toInteger(afterComplete.sendQty)).toBe(40);
    expect(afterComplete.taskSendQty[1]).toBe(40);
  });
});

// ---------------------------------------------------------------------------
// Multi-task group
// ---------------------------------------------------------------------------

describe("multi-task group — sequential distribution", () => {
  it("issue arrow distributes sequentially across tasks", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "200", cache: { issued_quantity: "100", completed_quantity: "0", transferred_quantity: "0", rejected_quantity: "0" } }),
      makeTask({ id: 2, planned_quantity: "300", cache: { issued_quantity: "150", completed_quantity: "0", transferred_quantity: "0", rejected_quantity: "0" } }),
      makeTask({ id: 3, planned_quantity: "500", cache: { issued_quantity: "200", completed_quantity: "0", transferred_quantity: "0", rejected_quantity: "0" } }),
    ];
    const group = makeGroup(tasks);

    expect(group.totalPlan).toBe(1000);
    expect(group.totalIssued).toBe(450);

    // Issue arrow: each task gets issued - completed - defect = all issued
    const afterIssue = activateIssueArrow(group);
    expect(afterIssue.taskCompleteQty[1]).toBe(100); // 100 - 0 - 0
    expect(afterIssue.taskCompleteQty[2]).toBe(150); // 150 - 0 - 0
    expect(afterIssue.taskCompleteQty[3]).toBe(200); // 200 - 0 - 0
    expect(toInteger(afterIssue.completeQty)).toBe(450);
  });

  it("complete arrow distributes sequentially across tasks", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "200", cache: { issued_quantity: "200", completed_quantity: "100", transferred_quantity: "40", rejected_quantity: "0" } }),
      makeTask({ id: 2, planned_quantity: "300", cache: { issued_quantity: "300", completed_quantity: "150", transferred_quantity: "50", rejected_quantity: "0" } }),
    ];
    const group = makeGroup(tasks);

    // Task 1: 100 - 40 - 0 = 60 available to send
    // Task 2: 150 - 50 - 0 = 100 available to send
    const afterComplete = activateCompleteArrow(group);
    expect(afterComplete.taskSendQty[1]).toBe(60);
    expect(afterComplete.taskSendQty[2]).toBe(100);
    expect(toInteger(afterComplete.sendQty)).toBe(160);
  });

  it("full cascade on multi-task group", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "100", cache: { issued_quantity: "60", completed_quantity: "20", transferred_quantity: "10", rejected_quantity: "5" } }),
      makeTask({ id: 2, planned_quantity: "200", cache: { issued_quantity: "120", completed_quantity: "40", transferred_quantity: "20", rejected_quantity: "10" } }),
    ];
    const group = makeGroup(tasks);

    // Total: plan=300, issued=180, completed=60, transferred=30, rejected=15
    expect(group.totalPlan).toBe(300);
    expect(group.totalIssued).toBe(180);
    expect(group.totalCompleted).toBe(60);
    expect(group.totalTransferred).toBe(30);

    const afterCascade = cascade(group);

    // Issue arrow:
    // Task 1: issued(60) - completed(20) - defect(5) = 35 in work
    // Task 2: issued(120) - completed(40) - defect(10) = 70 in work
    // Total complete = 105
    expect(toInteger(afterCascade.completeQty)).toBe(105);

    // Complete arrow:
    // Input complete(105) - defect(15) = 90 good
    // Task 1: completed(20) - transferred(10) - defect(5) = 5 available
    // Task 2: completed(40) - transferred(20) - defect(10) = 10 available
    // Total send = 15... but with input:
    // remaining from input = 105 - 15 = 90, minus already 15 = 75 extra
    // But sendable per task: Task1 = 20-10-5=5, Task2 = 40-20-10=10
    // Already allocated: 5 + 10 = 15
    // remainingInput = 90 - 15 = 75, but no more sendable capacity
    expect(toInteger(afterCascade.sendQty)).toBe(15);
  });
});

describe("progress display", () => {
  it("shows transferred/planned for each task", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "500", cache: { transferred_quantity: "200" } }),
      makeTask({ id: 2, planned_quantity: "300", cache: { transferred_quantity: "100" } }),
    ];
    const group = makeGroup(tasks);
    expect(getTaskProgress(group)).toBe("200/500, 100/300");
  });

  it("shows zeros for empty tasks", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "100", cache: { transferred_quantity: "0" } }),
      makeTask({ id: 2, planned_quantity: "200", cache: { transferred_quantity: "0" } }),
    ];
    const group = makeGroup(tasks);
    expect(getTaskProgress(group)).toBe("0/100, 0/200");
  });
});
