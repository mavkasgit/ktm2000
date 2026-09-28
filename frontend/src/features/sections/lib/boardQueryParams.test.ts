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
  buildBoardColumnApiParams,
  buildBoardServerQueryParams,
  isServerSortField,
  mapTaskSortFieldToApi,
  type TaskSortField,
} from "./boardQueryParams";
import { boardColumns } from "./boardColumns";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

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

describe("параметры фильтров колонок доски", () => {
  it("размер уезжает выбранным габаритом, а не подстрокой из поиска поповера", () => {
    // Поиск в поповере сужает только список значений; отправка подстроки
    // означала бы «фильтр по тексту подписи», которого у сервера нет.
    expect(
      buildBoardColumnApiParams(
        { dimensions: new Set(['{"length_mm":2700}']) },
        { dimensions: "2,7" },
      ),
    ).toEqual({ dimensions: '{"length_mm":2700}' });
  });

  it("поиск поповера без выбранного значения не уезжает вовсе", () => {
    expect(buildBoardColumnApiParams({}, { dimensions: "2,7" })).toEqual({});
  });

  it("колонка с фильтром уезжает под своим именем параметра без правки сборщика", () => {
    // Поле доски `productSku`, а параметр запроса — `product_sku`. Пока сборщик
    // брал поле руками, опечатка в имени параметра гасила фильтр молча.
    expect(buildBoardColumnApiParams({}, { productSku: "АРТ" })).toEqual({ product_sku: "АРТ" });
  });

  it("клиентские количества и статус в запрос не уезжают", () => {
    // Сервер фильтров по ним не знает, а значение колонки подписано
    // («Годные», «12 шт.») — отправка сузила бы выборку до пустой.
    expect(
      buildBoardColumnApiParams(
        {
          plannedQty: new Set(["12 шт."]),
          completedQty: new Set(["Годные"]),
          status: new Set(["Готово"]),
        },
        {},
      ),
    ).toEqual({});
  });

  it("ни один ключ описания не выходит за пределы контракта запроса", () => {
    // Обёртка `buildBoardColumnApiParams` отдаёт ровно два поля по типу, и
    // сверять с ней бесполезно: опечатку в `apiParam` поймал бы лишь сборщик,
    // отдающий ключи как есть.
    const all = buildColumnApiParams(
      Object.fromEntries(
        boardColumns
          .filter((column) => column.filterField)
          .map((column) => [column.filterField, new Set(["значение"])]),
      ),
      {},
      boardColumns,
    );

    expect(Object.keys(all).sort()).toEqual(["dimensions", "product_sku"]);
  });
});
