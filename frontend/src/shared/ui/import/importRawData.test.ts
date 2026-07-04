import { describe, it, expect } from "vitest";

import { extractPlanImportRawRows } from "./importRawData";

describe("extractPlanImportRawRows", () => {
  it("returns raw_columns_by_row in sorted order", () => {
    const row = {
      source_row_number: 5,
      payload: {
        raw_columns_by_row: {
          "12": { Артикул: "A", Колво: "10" },
          "5": { Артикул: "B", Колво: "20" },
        },
      },
    };
    const { segments, hasRawData } = extractPlanImportRawRows(row);
    expect(hasRawData).toBe(true);
    expect(segments[0].rowNumber).toBe("5");
    expect(segments[0].values).toEqual(["B", "20"]);
    expect(segments[1].rowNumber).toBe("12");
  });

  it("marks duplicate segments with variant duplicate", () => {
    const row = {
      source_row_number: 3,
      after_data: {
        duplicate_type: "against_existing",
        duplicate_existing_id: 99,
        duplicate_existing_payload: {
          raw_columns: { Артикул: "X", Колво: "1" },
        },
      },
      payload: { raw_columns: { Артикул: "X", Колво: "2" } },
    };
    const { segments } = extractPlanImportRawRows(row);
    expect(segments.some((s) => s.variant === "duplicate")).toBe(true);
    expect(segments.find((s) => s.variant === "duplicate")?.prefixLabel).toBe("(#99) ");
  });
});