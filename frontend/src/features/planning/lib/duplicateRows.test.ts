import { describe, expect, it } from "vitest";
import { isDuplicateRow } from "./duplicateRows";

describe("isDuplicateRow", () => {
  it("считает дублем строку с действием mark_possible_duplicate без кодов", () => {
    expect(isDuplicateRow({ change_action: "mark_possible_duplicate" })).toBe(true);
    expect(
      isDuplicateRow({ change_action: "mark_possible_duplicate", codes: [], errors: [], warnings: [] }),
    ).toBe(true);
  });

  it("распознаёт код duplicate_sku_due_date в codes", () => {
    expect(isDuplicateRow({ codes: ["duplicate_sku_due_date"] })).toBe(true);
    expect(isDuplicateRow({ codes: ["product_not_found", "duplicate_sku_due_date"] })).toBe(true);
  });

  it("распознаёт код duplicate_sku_due_date в errors", () => {
    expect(isDuplicateRow({ errors: ["duplicate_sku_due_date"] })).toBe(true);
    expect(isDuplicateRow({ errors: ["invalid_quantity", "duplicate_sku_due_date"] })).toBe(true);
  });

  it("распознаёт код duplicate_sku_due_date в warnings", () => {
    expect(isDuplicateRow({ warnings: ["duplicate_sku_due_date"] })).toBe(true);
  });

  it("распознаёт дубль при обоих сигналах одновременно", () => {
    expect(
      isDuplicateRow({
        change_action: "mark_possible_duplicate",
        codes: ["duplicate_sku_due_date"],
        errors: ["duplicate_sku_due_date"],
      }),
    ).toBe(true);
  });

  it("срабатывает по коду даже при чужом действии (OR-семантика)", () => {
    expect(isDuplicateRow({ change_action: "create_position", codes: ["duplicate_sku_due_date"] })).toBe(true);
    expect(isDuplicateRow({ change_action: "update_position", warnings: ["duplicate_sku_due_date"] })).toBe(true);
  });

  it("не считает дублем другие коды и пустые списки", () => {
    expect(isDuplicateRow({ codes: ["product_not_found"] })).toBe(false);
    expect(
      isDuplicateRow({
        change_action: "create_position",
        codes: ["product_not_found"],
        errors: ["invalid_quantity"],
        warnings: ["missing_budget"],
      }),
    ).toBe(false);
    expect(isDuplicateRow({ codes: [], errors: [], warnings: [] })).toBe(false);
  });

  it("не считает дублем отсутствующие поля", () => {
    expect(isDuplicateRow({})).toBe(false);
    expect(isDuplicateRow({ change_action: null })).toBe(false);
    expect(
      isDuplicateRow({ codes: null, errors: null, warnings: null }),
    ).toBe(false);
    expect(
      isDuplicateRow({ change_action: undefined, codes: undefined, errors: undefined, warnings: undefined }),
    ).toBe(false);
  });

  it("сравнивает код целиком, а не по подстроке", () => {
    expect(isDuplicateRow({ codes: ["duplicate_sku_due_date_extra"] })).toBe(false);
    expect(isDuplicateRow({ warnings: ["not_duplicate_sku_due_date"] })).toBe(false);
  });
});
