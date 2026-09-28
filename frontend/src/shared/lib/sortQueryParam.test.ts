import { describe, expect, it } from "vitest";
import { buildSortParam } from "./sortQueryParam";

type ColumnField = "plannedQty" | "sku" | "route" | "dimensions";

/** Маппер колонки в поле API: «Маршрут» сервер сортировать не умеет. */
function toApiField(field: ColumnField): string | undefined {
  const api: Record<ColumnField, string | undefined> = {
    plannedQty: "planned_qty",
    sku: "product_sku",
    route: undefined,
    dimensions: "dimensions",
  };
  return api[field];
}

describe("buildSortParam", () => {
  it("пустой набор сортировок не даёт параметр", () => {
    expect(buildSortParam<ColumnField, string>([], toApiField)).toBeUndefined();
  });

  it("одна колонка даёт пару поле:направление", () => {
    expect(buildSortParam([{ field: "sku", order: "asc" }], toApiField)).toBe("product_sku:asc");
  });

  it("порядок в строке это порядок приоритета", () => {
    const param = buildSortParam(
      [
        { field: "dimensions", order: "desc" },
        { field: "sku", order: "asc" },
        { field: "plannedQty", order: "desc" },
      ],
      toApiField,
    );
    expect(param).toBe("dimensions:desc,product_sku:asc,planned_qty:desc");
  });

  it("колонка без серверной сортировки не попадает в строку", () => {
    const param = buildSortParam(
      [
        { field: "route", order: "desc" },
        { field: "sku", order: "asc" },
      ],
      toApiField,
    );
    expect(param).toBe("product_sku:asc");
  });

  it("набор из одних несортируемых колонок не даёт параметр", () => {
    expect(buildSortParam([{ field: "route", order: "desc" }], toApiField)).toBeUndefined();
  });
});
