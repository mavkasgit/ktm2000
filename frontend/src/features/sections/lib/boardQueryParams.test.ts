/**
 * Параметры доски, которые уходят на сервер: поиск, фильтры колонок и сортировка.
 *
 * Регресс: раньше в запрос уезжал только `sortConfigs[0]`, а шапка уже
 * показывала приоритет 2 — оператор кликал вторую колонку, видел бейдж «2»
 * и не видел эффекта. Плюс клиентская колонка подменяла серверному полю
 * (`sequence`), из-за чего строки переставлялись не по той колонке.
 */

import { describe, expect, it } from "vitest";

import {
  buildBoardServerQueryParams,
  isServerSortField,
  mapTaskSortFieldToApi,
  type TaskSortField,
} from "./boardQueryParams";

function buildParams(sortConfigs: { field: TaskSortField; order: "asc" | "desc" }[]) {
  return buildBoardServerQueryParams({
    columnFilters: {},
    columnSearchQueries: {},
    sortConfigs,
  });
}

describe("mapTaskSortFieldToApi", () => {
  it("серверные колонки доски мапятся на свои поля ORDER BY", () => {
    expect(mapTaskSortFieldToApi("sequence")).toBe("sequence");
    expect(mapTaskSortFieldToApi("productSku")).toBe("product_sku");
    expect(mapTaskSortFieldToApi("status")).toBe("status");
    expect(mapTaskSortFieldToApi("dimensions")).toBe("dimensions");
  });

  it("количества дают undefined, а не подменяются серверным полем", () => {
    // Количества сервер не сортирует: они лежат в кэше задания. Подставить
    // вместо них `sequence` нельзя — оператор кликнул «План», а строки
    // переставились по номеру задания.
    for (const field of [
      "plannedQty",
      "issuedQty",
      "completedQty",
      "transferredQty",
      "rejectedQty",
      "remainingQty",
    ] as const) {
      expect(mapTaskSortFieldToApi(field), `колонка ${field} не сортируется сервером`).toBeUndefined();
    }
  });

  it("isServerSortField совпадает с наличием серверного поля", () => {
    for (const field of [
      "sequence",
      "productSku",
      "status",
      "dimensions",
      "plannedQty",
      "remainingQty",
    ] as const) {
      expect(isServerSortField(field)).toBe(mapTaskSortFieldToApi(field) !== undefined);
    }
  });
});

describe("buildBoardServerQueryParams", () => {
  it("уезжают ВСЕ выбранные серверные приоритеты, от старшего к младшему", () => {
    expect(
      buildParams([
        { field: "productSku", order: "asc" },
        { field: "status", order: "desc" },
        { field: "dimensions", order: "asc" },
      ]).sort,
    ).toBe("product_sku:asc,status:desc,dimensions:asc");
  });

  it("клиентские колонки в строку сортировки не попадают", () => {
    expect(
      buildParams([
        { field: "plannedQty", order: "desc" },
        { field: "productSku", order: "asc" },
      ]).sort,
    ).toBe("product_sku:asc");
  });

  it("только клиентские колонки — сортировка не уезжает вовсе, дефолт сервера", () => {
    // Сервер получает свой дефолт, а выбранную колонку сортирует клиент
    // поверх ответа (sortedTasks в SectionTasksBoard).
    expect(buildParams([{ field: "plannedQty", order: "desc" }]).sort).toBeUndefined();
    expect(buildParams([]).sort).toBeUndefined();
  });

  it("поиск и фильтры колонок остаются в своих параметрах", () => {
    const params = buildBoardServerQueryParams({
      search: "  арт-1  ",
      columnFilters: { dimensions: new Set(['{"length_mm":2700}']) },
      columnSearchQueries: { productSku: "АРТ" },
      sortConfigs: [{ field: "sequence", order: "asc" }],
    });
    expect(params).toEqual({
      search: "арт-1",
      product_sku: "АРТ",
      dimensions: '{"length_mm":2700}',
      sort: "sequence:asc",
    });
  });
});
