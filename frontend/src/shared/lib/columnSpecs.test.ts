/**
 * Семантика колонок объявляется один раз — в описании колонки, а не
 * тернарником по имени колонки в шапке и не перечислением в параметрах
 * запроса (#197, ADR-0037).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams, exactMatchColumnParams, type ColumnSpec } from "./columnSpecs";

type ParamField = "sku" | "dimensions" | "errors" | "rowNum" | "next";

const PARAM_COLUMNS: ColumnSpec<ParamField>[] = [
  { filterField: "sku" },
  { filterField: "dimensions", exactMatch: true },
  {
    filterField: "errors",
    apiParam: "has_errors",
    mapValue: (value) => (value === "0" ? "no" : "yes"),
  },
  { filterField: "rowNum", clientOnly: true },
  {
    filterField: "next",
    toParams: (value) => {
      const [name, section] = value.split(" / ");
      return { next_operation_name: name, next_section_name: section ?? "" };
    },
  },
];

describe("buildColumnApiParams", () => {
  it("подставляет значение под имя параметра, объявленное в описании", () => {
    const params = buildColumnApiParams(
      { sku: new Set(["КР-01"]), errors: new Set(["0"]), dimensions: new Set(['{"length_mm":2700}']) },
      {},
      PARAM_COLUMNS,
    );

    expect(params).toEqual({ sku: "КР-01", has_errors: "no", dimensions: '{"length_mm":2700}' });
  });

  it("поисковый запрос колонки уезжает подстрокой, если значения не выбраны", () => {
    expect(buildColumnApiParams({}, { sku: "КР" }, PARAM_COLUMNS)).toEqual({ sku: "КР" });
  });

  it("точная колонка уезжает выбранным значением, а не результатом поиска", () => {
    // Поиск в поповере лишь сужает список габаритов: выбрать «2,7 м» и
    // написать «2,7» — одно и то же, но в запрос уходит только выбранное.
    const params = buildColumnApiParams(
      { dimensions: new Set(['{"length_mm":2700}']) },
      { dimensions: "2,7" },
      PARAM_COLUMNS,
    );

    expect(params.dimensions).toBe('{"length_mm":2700}');
  });

  it("колонка, фильтруемая на клиенте, в запрос не уезжает", () => {
    expect(buildColumnApiParams({ rowNum: new Set(["12"]) }, { rowNum: "12" }, PARAM_COLUMNS)).toEqual({});
  });

  it("колонка без фильтра в описании в запрос не уезжает", () => {
    const columns: ColumnSpec<ParamField>[] = [{}, { filterField: "sku" }];

    expect(buildColumnApiParams({ sku: new Set(["A"]) }, {}, columns)).toEqual({ sku: "A" });
  });

  it("перекодировка может отбросить значение, которого сервер не понимает", () => {
    const columns: ColumnSpec<ParamField>[] = [
      { filterField: "sku", apiParam: "product_sku", mapValue: (value) => (value === "—" ? undefined : value) },
    ];

    expect(buildColumnApiParams({ sku: new Set(["—"]) }, {}, columns)).toEqual({});
    expect(buildColumnApiParams({ sku: new Set(["КР-2"]) }, {}, columns)).toEqual({ product_sku: "КР-2" });
  });

  it("колонка, дающая несколько параметров, раскладывает их все", () => {
    const params = buildColumnApiParams({ next: new Set(["Пиление / Упаковка"]) }, {}, PARAM_COLUMNS);

    expect(params).toEqual({ next_operation_name: "Пиление", next_section_name: "Упаковка" });
  });

  it("вторая перекодируемая колонка добавляется без правки сборщика", () => {
    const columns: ColumnSpec<ParamField>[] = [
      { filterField: "errors", apiParam: "has_errors", mapValue: (v) => (v === "0" ? "no" : "yes") },
      { filterField: "rowNum", apiParam: "has_warnings", mapValue: (v) => (v === "0" ? "no" : "yes") },
    ];

    expect(buildColumnApiParams({ errors: new Set(["2"]), rowNum: new Set(["0"]) }, {}, columns)).toEqual({
      has_errors: "yes",
      has_warnings: "no",
    });
  });
});

type Field = "sku" | "dimensions" | "status";

const COLUMNS: ColumnSpec<Field>[] = [
  { filterField: "sku" },
  { filterField: "dimensions", exactMatch: true },
  { filterField: "status" },
];

describe("exactMatchColumnParams", () => {
  it("берёт значение только у колонки, объявленной как точное совпадение", () => {
    const params = exactMatchColumnParams(
      { sku: new Set(["ABC"]), dimensions: new Set(['{"length_mm":2700}']) },
      COLUMNS,
    );
    expect(params).toEqual({ dimensions: '{"length_mm":2700}' });
  });

  it("колонка без признака exactMatch в результат не попадает, даже если отфильтрована", () => {
    // «Артикул» ищется по подстроке: его значение уходит отдельным
    // параметром, и повторять его здесь нельзя.
    const params = exactMatchColumnParams({ sku: new Set(["ABC"]) }, COLUMNS);
    expect(params).toEqual({});
  });

  it("колонка без фильтра в описании не даёт значения", () => {
    const columns: ColumnSpec<Field>[] = [{ filterField: "dimensions", exactMatch: true }, {}];
    expect(exactMatchColumnParams({ dimensions: new Set(['{"length_mm":900}']) }, columns)).toEqual({
      dimensions: '{"length_mm":900}',
    });
  });

  it("вторая колонка точного совпадения добавляется без правки вызова", () => {
    // Смысл объявления один раз: появление новой точной колонки не должно
    // требовать менять код, который собирает параметры.
    type TwoFields = "dimensions" | "location";
    const columns: ColumnSpec<TwoFields>[] = [
      { filterField: "dimensions", exactMatch: true },
      { filterField: "location", exactMatch: true },
    ];
    const params = exactMatchColumnParams<TwoFields>(
      { dimensions: new Set(['{"length_mm":2700}']), location: new Set(["A-1"]) },
      columns,
    );
    expect(params).toEqual({ dimensions: '{"length_mm":2700}', location: "A-1" });
  });

  it("колонка объявлена точной, но не отфильтрована — параметра нет", () => {
    expect(exactMatchColumnParams({}, COLUMNS)).toEqual({});
  });

  it("несколько выбранных значений точной колонки не отправляют ничего", () => {
    // «Выбрать все» в поповере выбирает несколько габаритов. Точный фильтр
    // не мультизначный: отправлять первый из них значит фильтровать по
    // произвольному размеру. Планирующая и передачи уже так себя ведут, и
    // доска обязана вести себя так же, иначе один клик даёт разный запрос
    // на разных экранах.
    const params = exactMatchColumnParams(
      { dimensions: new Set(['{"length_mm":2700}', '{"length_mm":900}']) },
      COLUMNS,
    );
    expect(params).toEqual({});
  });
});
