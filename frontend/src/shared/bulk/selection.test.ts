import { describe, expect, it } from "vitest";
import { areAllSelected, isSelectionIndeterminate, selectAllFilteredIds, toggleBulkSelection } from "./selection";

describe("bulk selection core", () => {
  it("selects all filtered ids", () => {
    const selected = selectAllFilteredIds([1, 2, 3]);
    expect(Array.from(selected)).toEqual([1, 2, 3]);
  });

  it("toggles one id without mutating the previous set", () => {
    const initial = new Set([1]);
    const selected = toggleBulkSelection(initial, 2);
    const cleared = toggleBulkSelection(selected, 1, false);
    expect(Array.from(initial)).toEqual([1]);
    expect(Array.from(selected)).toEqual([1, 2]);
    expect(Array.from(cleared)).toEqual([2]);
  });

  it("reports tri-state checkbox state against filtered ids", () => {
    const selected = new Set([1, 2]);
    expect(areAllSelected(selected, [1, 2])).toBe(true);
    expect(areAllSelected(selected, [1, 2, 3])).toBe(false);
    expect(isSelectionIndeterminate(selected, [1, 2, 3])).toBe(true);
    expect(isSelectionIndeterminate(new Set<number>(), [1, 2, 3])).toBe(false);
  });
});
