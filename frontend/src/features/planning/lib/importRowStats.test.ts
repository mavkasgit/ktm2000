import { describe, expect, it } from "vitest";

import { buildImportRowStats, type ImportStatRow } from "./importRowStats";

describe("buildImportRowStats", () => {
  it("считает статусы по строкам, а total — по всей длине входа", () => {
    const rows: ImportStatRow[] = [
      { status: "pending" },
      { status: "pending" },
      { status: "warning" },
      { status: "invalid" },
      // Неизвестный статус попадает в total, но ни в один из счётчиков статусов.
      { status: "approved" },
    ];
    expect(buildImportRowStats(rows)).toEqual({
      total: 5,
      valid: 2,
      warning: 1,
      invalid: 1,
      duplicates: 0,
      normal: 3,
      uploadAll: 5,
      uploadSkipInvalid: 4,
      errors: {},
    });
  });

  it("на пустом входе отдаёт нулевые счётчики", () => {
    expect(buildImportRowStats([])).toEqual({
      total: 0,
      valid: 0,
      warning: 0,
      invalid: 0,
      duplicates: 0,
      normal: 0,
      uploadAll: 0,
      uploadSkipInvalid: 0,
      errors: {},
    });
  });

  it("раскладывает коды только из errors и считает повторы", () => {
    const rows: ImportStatRow[] = [
      { status: "invalid", errors: ["product_not_found", "invalid_quantity"] },
      { status: "invalid", errors: ["product_not_found", "product_not_found"] },
      { status: "warning", errors: ["product_not_found"], warnings: ["missing_budget"], codes: ["missing_budget"] },
    ];
    expect(buildImportRowStats(rows).errors).toEqual({ product_not_found: 4, invalid_quantity: 1 });
  });

  it("считает дубль по каждому из трёх признаков и не считает чужие строки", () => {
    const rows: ImportStatRow[] = [
      { status: "warning", change_action: "mark_possible_duplicate" },
      { status: "pending", warnings: ["duplicate_sku_due_date"] },
      { status: "invalid", codes: ["duplicate_sku_due_date"] },
      { status: "pending", errors: ["duplicate_sku_due_date"] },
      { status: "pending", change_action: "create_position", errors: ["other_code"] },
    ];
    const stats = buildImportRowStats(rows);
    expect(stats.duplicates).toBe(4);
    // Код дубля из codes/warnings в раскладку ошибок не попадает.
    expect(stats.errors).toEqual({ duplicate_sku_due_date: 1, other_code: 1 });
  });

  it("пропускает нестроковые коды и не-массивы в полях", () => {
    const stats = buildImportRowStats([
      { status: "invalid", errors: ["dup_code", 7, null, { code: "x" }, "dup_code"] },
      { status: "warning", errors: "not-an-array", warnings: { code: "x" }, codes: 5 },
    ]);
    expect(stats.errors).toEqual({ dup_code: 2 });
    expect(stats).toMatchObject({
      total: 2,
      valid: 0,
      warning: 1,
      invalid: 1,
      duplicates: 0,
      normal: 0,
      uploadAll: 2,
      uploadSkipInvalid: 1,
    });
  });
});
