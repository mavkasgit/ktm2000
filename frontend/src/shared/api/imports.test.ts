import { describe, expect, it } from "vitest";

import { buildImportApplyStats } from "./imports";

describe("buildImportApplyStats", () => {
  it("maps server summary to dialog stats", () => {
    const stats = buildImportApplyStats({
      total: 10,
      valid: 6,
      warning: 1,
      invalid: 3,
      duplicates: 2,
      errors: { product_not_found: 3 },
    });
    expect(stats).toMatchObject({
      total: 10,
      valid: 6,
      warning: 1,
      invalid: 3,
      duplicates: 2,
      normal: 6,
      uploadAll: 10,
      uploadSkipInvalid: 7,
      errors: { product_not_found: 3 },
    });
  });

  it("derives valid when missing and clamps negatives", () => {
    const stats = buildImportApplyStats({ total: 5, warning: 1, invalid: 1 });
    expect(stats.valid).toBe(3);
    expect(stats.normal).toBe(3);
    expect(stats.errors).toEqual({});
    expect(stats.duplicates).toBe(0);
  });
});
