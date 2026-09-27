import { describe, expect, it } from "vitest";

import {
  buildBalanceSortParam,
  buildRemainderPreviewSortParam,
  buildTransactionSortParam,
  mapBalanceSortFieldToApi,
  mapRemainderPreviewSortFieldToApi,
  mapTransactionSortFieldToApi,
} from "./stockSortParams";

describe("маппер колонок остатков", () => {
  it("названия колонок совпадают с полями ORDER BY бэкенда", () => {
    expect(mapBalanceSortFieldToApi("sku")).toBe("sku");
    expect(mapBalanceSortFieldToApi("quantity")).toBe("quantity");
    expect(mapBalanceSortFieldToApi("operations")).toBe("operations");
    expect(mapBalanceSortFieldToApi("quality")).toBe("quality");
    expect(mapBalanceSortFieldToApi("location")).toBe("location");
  });
});

describe("маппер колонок истории транзакций", () => {
  it("короткие имена колонок разворачиваются в поля транзакции", () => {
    expect(mapTransactionSortFieldToApi("date")).toBe("created_at");
    expect(mapTransactionSortFieldToApi("reason")).toBe("reason");
    expect(mapTransactionSortFieldToApi("from")).toBe("from_location");
    expect(mapTransactionSortFieldToApi("to")).toBe("to_location");
    expect(mapTransactionSortFieldToApi("quantity")).toBe("quantity");
    expect(mapTransactionSortFieldToApi("quality")).toBe("quality_state");
    expect(mapTransactionSortFieldToApi("comment")).toBe("comment");
  });
});

describe("маппер колонок превью импорта остатков", () => {
  it("поля превью уходят под теми же именами", () => {
    expect(mapRemainderPreviewSortFieldToApi("row")).toBe("row");
    expect(mapRemainderPreviewSortFieldToApi("length")).toBe("length");
    expect(mapRemainderPreviewSortFieldToApi("section")).toBe("section");
    expect(mapRemainderPreviewSortFieldToApi("errors")).toBe("errors");
  });
});

describe("сборка строки sort", () => {
  it("без выбранных колонок уходит дефолт эндпоинта", () => {
    expect(buildBalanceSortParam([])).toBe("sku:asc");
    expect(buildTransactionSortParam([])).toBe("created_at:desc");
    expect(buildRemainderPreviewSortParam([])).toBe("row:asc");
  });

  it("все выбранные приоритеты уходят в порядке выбора, а не только первый", () => {
    expect(
      buildBalanceSortParam([
        { field: "location", order: "desc" },
        { field: "quantity", order: "asc" },
      ]),
    ).toBe("location:desc,quantity:asc");

    expect(
      buildTransactionSortParam([
        { field: "quantity", order: "desc" },
        { field: "comment", order: "asc" },
      ]),
    ).toBe("quantity:desc,comment:asc");

    expect(
      buildRemainderPreviewSortParam([
        { field: "sku", order: "asc" },
        { field: "row", order: "desc" },
      ]),
    ).toBe("sku:asc,row:desc");
  });
});
