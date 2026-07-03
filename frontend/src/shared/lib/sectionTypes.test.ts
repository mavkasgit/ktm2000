import { describe, expect, it } from "vitest";
import { isProductionSection, STOCK_SECTION_TYPES } from "./sectionTypes";

describe("isProductionSection", () => {
  it("returns true for production type", () => {
    expect(isProductionSection("production")).toBe(true);
  });

  it("returns false for raw_stock", () => {
    expect(isProductionSection("raw_stock")).toBe(false);
  });

  it("returns false for wip_stock", () => {
    expect(isProductionSection("wip_stock")).toBe(false);
  });

  it("returns false for finished_stock", () => {
    expect(isProductionSection("finished_stock")).toBe(false);
  });

  it("returns false for scrap", () => {
    expect(isProductionSection("scrap")).toBe(false);
  });

});

describe("STOCK_SECTION_TYPES", () => {
  it("contains exactly four stock types", () => {
    expect(STOCK_SECTION_TYPES).toEqual([
      "raw_stock",
      "wip_stock",
      "finished_stock",
      "scrap",
    ]);
  });
});
