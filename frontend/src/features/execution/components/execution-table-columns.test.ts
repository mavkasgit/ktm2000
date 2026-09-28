/**
 * Параметры запроса исполнения собираются из описания колонок: пока сборка
 * стояла в странице и перечисляла десять колонок через `pickColumnApiValue`,
 * переименование параметра или новое «значение серверу не показывать» надо
 * было бы искать в двух местах (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import type { ExecutionSortField } from "./execution-utils";
import { executionTableColumns } from "./execution-table-columns";

const build = (
  columnFilters: Partial<Record<ExecutionSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<ExecutionSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, executionTableColumns);

/**
 * Ключи контракта запроса. Сборщик отдаёт строки, поэтому сверка его вывода
 * с этим списком — единственная защита от опечатки в имени параметра: приведение
 * к `Pick<Params, …>` проверяет что угодно.
 */
const CONTRACT_KEYS = new Set([
  "plan_position_id",
  "source_row_number",
  "product_sku",
  "source_name",
  "quantity",
  "route_name",
  "status",
  "current_stage_section_name",
  "dimensions",
]);

describe("параметры списка исполнения", () => {
  it("значения колонок уезжают под именами параметров запроса", () => {
    expect(
      build({
        id: new Set(["42"]),
        row: new Set(["5"]),
        sku: new Set(["КР-01"]),
        name: new Set(["Доска"]),
        qty: new Set(["12"]),
        status: new Set(["approved"]),
        route: new Set(["Пиление"]),
        stage: new Set(["Сушка"]),
      }),
    ).toEqual({
      plan_position_id: "42",
      source_row_number: "5",
      product_sku: "КР-01",
      source_name: "Доска",
      quantity: "12",
      status: "approved",
      route_name: "Пиление",
      current_stage_section_name: "Сушка",
    });
  });

  it("«Не назначен» и «—» — это отсутствие значения, а не значение", () => {
    // Позиция без маршрута и без участка рисует прочерк в колонке: отправлять
    // его серверу нельзя, иначе фильтр вернёт пустую выборку.
    expect(build({ route: new Set(["Не назначен"]), stage: new Set(["—"]) })).toEqual({});
  });

  it("выбранный габарит уезжает точным значением, а не результатом поиска", () => {
    // Поиск в поповере только сужает список значений и в состояние таблицы
    // не попадает: уезжать должен выбранный габарит.
    expect(
      build({ dimensions: new Set(['{"length_mm":2700}']) }, { dimensions: "2,7" }),
    ).toEqual({ dimensions: '{"length_mm":2700}' });
  });

  it("колонка без фильтра не отправляет ничего", () => {
    // «Действия» объявлены без `filterField`: кликнуть в них нечего, и
    // отправлять нечего.
    expect(build({ id: new Set(["42"]) })).not.toHaveProperty("actions");
  });

  it("поиск в поповере без выбранных значений уезжает как подстрока", () => {
    expect(build({}, { name: "доск" })).toEqual({ source_name: "доск" });
  });

  it("без фильтров параметров не уезжает", () => {
    expect(build({})).toEqual({});
  });
});

describe("имена параметров совпадают с контрактом запроса", () => {
  it("ни один ключ не выходит за пределы контракта запроса", () => {
    const params = build(
      Object.fromEntries(
        executionTableColumns
          .filter((column) => column.filterField)
          .map((column) => [column.filterField, new Set(["x"])]),
      ),
    );

    expect(Object.keys(params).filter((key) => !CONTRACT_KEYS.has(key))).toEqual([]);
  });

  it("артикул уезжает как product_sku, а не именем колонки", () => {
    const params = build({ sku: new Set(["КР-01"]) });

    expect(params).toEqual({ product_sku: "КР-01" });
    expect(params).not.toHaveProperty("sku");
  });

  it("позиция плана уезжает как plan_position_id, а строка — как source_row_number", () => {
    expect(build({ id: new Set(["42"]), row: new Set(["5"]) })).toEqual({
      plan_position_id: "42",
      source_row_number: "5",
    });
  });
});
