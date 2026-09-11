import { describe, expect, it } from "vitest";

import type { PlanFileInfo } from "@/shared/api/productionPlans";

import { findLastAppliedBatchId, findNewerAppliedBatch } from "./appliedBatches";

function planFile(overrides: Partial<PlanFileInfo> = {}): PlanFileInfo {
  return {
    batch_id: 1,
    file_id: 1,
    production_plan_id: 1,
    change_set_id: 10,
    filename: "Упаковочный план.xlsx",
    extension: "xlsx",
    size_bytes: 1024,
    sheet_name: "Лист1",
    total_rows: 3,
    parsed_rows: 3,
    status: "applied",
    created_at: "2026-03-01T00:00:00Z",
    applied_at: null,
    ...overrides,
  };
}

describe("findLastAppliedBatchId", () => {
  it("выбирает батч с самым поздним applied_at, а не последний в списке", () => {
    const files = [
      planFile({ batch_id: 9, applied_at: "2026-03-02T00:00:00Z", created_at: "2026-03-09T00:00:00Z" }),
      planFile({ batch_id: 5, applied_at: "2026-03-04T00:00:00Z", created_at: "2026-03-01T00:00:00Z" }),
      planFile({ batch_id: 3, applied_at: "2026-03-03T00:00:00Z", created_at: "2026-03-20T00:00:00Z" }),
    ];
    expect(findLastAppliedBatchId(files, 1)).toBe(5);
  });

  it("пропускает неприменённые батчи и батчи других планов", () => {
    const files = [
      planFile({ batch_id: 3, applied_at: null, created_at: "2026-03-05T00:00:00Z" }),
      planFile({ batch_id: 4, production_plan_id: 2, applied_at: "2026-03-06T00:00:00Z" }),
      planFile({ batch_id: 6, applied_at: "2026-03-01T00:00:00Z" }),
    ];
    expect(findLastAppliedBatchId(files, 1)).toBe(6);
  });

  it("не считает применением неразбираемую дату", () => {
    const files = [
      planFile({ batch_id: 5, applied_at: "2026-03-01T00:00:00Z" }),
      planFile({ batch_id: 4, applied_at: "не дата" }),
    ];
    expect(findLastAppliedBatchId(files, 1)).toBe(5);
  });

  it("возвращает null без плана и когда применённых батчей нет", () => {
    expect(findLastAppliedBatchId([], 1)).toBeNull();
    expect(findLastAppliedBatchId([planFile({ applied_at: "2026-03-01T00:00:00Z" })], null)).toBeNull();
    expect(findLastAppliedBatchId([planFile({ applied_at: "2026-03-01T00:00:00Z" })], undefined)).toBeNull();
    expect(findLastAppliedBatchId([planFile({ applied_at: null })], 1)).toBeNull();
  });
});

describe("findNewerAppliedBatch", () => {
  it("возвращает самый поздний чужой батч плана, применённый после parsedAt", () => {
    const newest = planFile({ batch_id: 12, filename: "третий.xlsx", applied_at: "2026-03-04T00:00:00Z" });
    const files = [
      planFile({ batch_id: 11, filename: "второй.xlsx", applied_at: "2026-03-03T00:00:00Z" }),
      newest,
      planFile({ batch_id: 13, applied_at: "2026-03-02T00:00:00Z" }),
      planFile({ batch_id: 20, production_plan_id: 2, applied_at: "2026-04-01T00:00:00Z" }),
      planFile({ batch_id: 10, applied_at: "2026-03-01T00:00:00Z" }),
    ];
    const result = findNewerAppliedBatch(files, { planId: 1, batchId: 10, parsedAt: "2026-03-01T00:00:00Z" });
    expect(result).toBe(newest);
    expect(result?.batch_id).toBe(12);
    expect(result?.filename).toBe("третий.xlsx");
  });

  it("не считает свежим сам батч и применения не позже parsedAt", () => {
    const files = [
      planFile({ batch_id: 10, applied_at: "2026-03-05T00:00:00Z" }),
      planFile({ batch_id: 11, applied_at: "2026-03-01T00:00:00Z" }),
      planFile({ batch_id: 12, applied_at: "2026-02-20T00:00:00Z" }),
      planFile({ batch_id: 13, applied_at: null }),
    ];
    expect(findNewerAppliedBatch(files, { planId: 1, batchId: 10, parsedAt: "2026-03-01T00:00:00Z" })).toBeNull();
  });

  it("возвращает null без batchId, parsedAt или плана", () => {
    const files = [planFile({ batch_id: 11, applied_at: "2026-03-05T00:00:00Z" })];
    expect(findNewerAppliedBatch(files, { planId: 1, batchId: null, parsedAt: "2026-03-01T00:00:00Z" })).toBeNull();
    expect(findNewerAppliedBatch(files, { planId: 1, batchId: 10, parsedAt: null })).toBeNull();
    expect(findNewerAppliedBatch(files, { planId: null, batchId: 10, parsedAt: "2026-03-01T00:00:00Z" })).toBeNull();
  });
});
