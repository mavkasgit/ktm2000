import { describe, expect, it } from "vitest";
import { isProductionSection, STOCK_SECTION_KINDS } from "./sectionKinds";

describe("isProductionSection", () => {
  it("returns true for production kind", () => {
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
});

describe("STOCK_SECTION_KINDS", () => {
  it("contains exactly three stock kinds", () => {
    expect(STOCK_SECTION_KINDS).toEqual(["raw_stock", "wip_stock", "finished_stock"]);
  });
});
