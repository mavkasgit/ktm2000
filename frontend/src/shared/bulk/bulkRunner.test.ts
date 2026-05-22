import { describe, expect, it } from "vitest";
import { runBulkAction, summarizeBulkResults, type BulkActionDefinition } from "./bulkRunner";

describe("bulk runner", () => {
  it("aggregates partial success results", () => {
    const summary = summarizeBulkResults([
      { id: 1, status: "success" },
      { id: 2, status: "failed", reason: "bad status" },
      { id: 3, status: "skipped", reason: "not eligible" },
    ]);
    expect(summary).toEqual({ total: 3, success: 1, failed: 1, skipped: 1 });
  });

  it("skips ineligible ids and runs eligible ids", async () => {
    const action: BulkActionDefinition<number, void> = {
      id: "demo",
      label: "Demo",
      isEligible: (id) => id !== 2,
      getIneligibleReason: () => "not allowed",
      run: async (ids) => ids.map((id) => ({ id, status: "success" })),
    };
    const progress: unknown[] = [];
    const results = await runBulkAction(action, [1, 2, 3], undefined, (value) => progress.push(value));
    expect(results).toEqual([
      { id: 2, status: "skipped", reason: "not allowed" },
      { id: 1, status: "success" },
      { id: 3, status: "success" },
    ]);
    expect(progress).toEqual([
      { total: 3, completed: 1, running: true },
      { total: 3, completed: 3, running: false },
    ]);
  });

  it("normalizes action-level errors per executable id", async () => {
    const action: BulkActionDefinition<number, void> = {
      id: "demo",
      label: "Demo",
      run: async () => {
        throw new Error("network down");
      },
    };
    await expect(runBulkAction(action, [1, 2], undefined)).resolves.toEqual([
      { id: 1, status: "failed", reason: "network down" },
      { id: 2, status: "failed", reason: "network down" },
    ]);
  });
});
