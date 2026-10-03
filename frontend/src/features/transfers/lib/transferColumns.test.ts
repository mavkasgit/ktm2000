/**
 * Параметры передач собираются из описания колонок: пока сборка стояла в двух
 * функциях страницы и перечисляла колонки руками, шестая колонка потребовала бы
 * правки кода (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import { historyColumns, readyColumns } from "./transferColumns";
import type { HistorySortField, ReadySortField } from "./transferSortParams";

const buildReady = (
  columnFilters: Partial<Record<ReadySortField, Set<string>>>,
  columnSearchQueries: Partial<Record<ReadySortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, readyColumns);

const buildHistory = (
  columnFilters: Partial<Record<HistorySortField, Set<string>>>,
  columnSearchQueries: Partial<Record<HistorySortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, historyColumns);

/**
 * Ключи контракта запроса. Держим здесь списком: сборщик отдаёт строки, и
 * сверять его вывод с этим списком — единственный способ поймать опечатку
 * в имени параметра.
 */
const READY_CONTRACT_KEYS = new Set([
  "product_sku",
  "operation_name",
  "next_operation_name",
  "next_section_name",
  "plan_position_id",
  "transferable_qty",
  "dimensions",
]);

const HISTORY_CONTRACT_KEYS = new Set([
  "product_sku",
  "from_section_name",
  "to_section_name",
  "status",
]);

describe("параметры готовых к передаче", () => {
  it("выбранный габарит уезжает точным значением", () => {
    expect(buildReady({ dimensions: new Set(['{"length_mm":2700}']) })).toEqual({
      dimensions: '{"length_mm":2700}',
    });
  });

  it("поиск в поповере габаритов не подменяется выбранным значением", () => {
    expect(buildReady({ dimensions: new Set(['{"length_mm":2700}']) }, { dimensions: "2,7" })).toEqual({
      dimensions: '{"length_mm":2700}',
    });
  });

  it("артикул и этап уезжают под серверными именами, а «—» не уезжает вовсе", () => {
    expect(buildReady({ sku: new Set(["КР-01"]), stage: new Set(["Пиление"]) })).toEqual({
      product_sku: "КР-01",
      operation_name: "Пиление",
    });
    expect(buildReady({ sku: new Set(["—"]), stage: new Set(["—"]) })).toEqual({});
  });

  it("номер позиции уезжает числом, а нечисловой ввод отбрасывается", () => {
    expect(buildReady({ positionId: new Set(["42"]) })).toEqual({ plan_position_id: "42" });
    expect(buildReady({ positionId: new Set(["abc"]) })).toEqual({});
  });

  it("«Следующий» раскладывается на операцию и участок", () => {
    expect(buildReady({ next: new Set(["Пиление / Упаковка"]) })).toEqual({
      next_operation_name: "Пиление",
      next_section_name: "Упаковка",
    });
  });

  it("финальный этап не уезжает ни как операция, ни как участок", () => {
    expect(buildReady({ next: new Set(["Финальный"]) })).toEqual({});
  });

  it("название участка с разделителем не разрывается на два параметра", () => {
    expect(buildReady({ next: new Set(["Хранение / Склад готовой продукции"]) })).toEqual({
      next_operation_name: "Хранение",
      next_section_name: "Склад готовой продукции",
    });
  });

  it("прочерк пустой части ячейки в запрос не уезжает", () => {
    expect(buildReady({ next: new Set(["Пиление / —"]) })).toEqual({
      next_operation_name: "Пиление",
    });
    expect(buildReady({ next: new Set(["— / Упаковка"]) })).toEqual({
      next_section_name: "Упаковка",
    });
  });

  it("без фильтров параметров не уезжает", () => {
    expect(buildReady({})).toEqual({});
  });
});

describe("параметры журнала передач", () => {
  it("«Размер» в журнале не фильтруется: сервер такого параметра не знает", () => {
    // Значение колонки есть, но описана она без фильтра: отправлять нечего.
    expect(buildHistory({ sku: new Set(["КР-01"]) })).toEqual({ product_sku: "КР-01" });
  });

  it("из «Пиление / Упаковка» в участок уезжает только участок", () => {
    expect(buildHistory({ from: new Set(["Пиление / Упаковка"]), to: new Set(["Сушка / ОТК"]) })).toEqual({
      from_section_name: "Пиление",
      to_section_name: "Сушка",
    });
  });

  it("подпись статуса разбирается в код сервера", () => {
    expect(buildHistory({ status: new Set(["Входящая / Принята"]) })).toEqual({ status: "accepted" });
    expect(buildHistory({ status: new Set(["Исходящая / Скорректирована"]) })).toEqual({});
  });
});

describe("имена параметров совпадают с контрактом запроса", () => {
  it("ни один ключ не выходит за пределы контракта запроса", () => {
    // Ключи сборщика — это буквально query string. Приведение к
    // `Pick<Params, …>` проверяет что угодно (сборщик отдаёт
    // `Record<string, string>`), поэтому единственная защита от опечатки в
    // имени — сверка с контрактом запроса. Именно так проскочило
    // `transferableQty` вместо `transferable_qty`, и фильтр перестал уезжать.
    const ready = buildReady(
      Object.fromEntries(readyColumns.map((c) => [c.filterField, new Set(["x"])])),
    );
    const history = buildHistory(
      Object.fromEntries(
        historyColumns.filter((c) => c.filterField).map((c) => [c.filterField, new Set(["x"])]),
      ),
    );

    expect(Object.keys(ready).filter((key) => !READY_CONTRACT_KEYS.has(key))).toEqual([]);
    expect(Object.keys(history).filter((key) => !HISTORY_CONTRACT_KEYS.has(key))).toEqual([]);
  });

  it("«К передаче» уезжает как transferable_qty, а не именем колонки", () => {
    const params = buildReady({ transferableQty: new Set(["70"]) });

    expect(params).toEqual({ transferable_qty: "70" });
    expect(params).not.toHaveProperty("transferableQty");
  });

  it("номер позиции уезжает как plan_position_id", () => {
    expect(buildReady({ positionId: new Set(["42"]) })).toEqual({ plan_position_id: "42" });
  });

  it("«Кол-во» в журнале не фильтруется: сервер такого параметра не знает", () => {
    const column = historyColumns.find((c) => c.id === "quantity");

    expect(column?.filterField).toBeUndefined();
    expect(column?.sortField).toBe("quantity");
  });
});
