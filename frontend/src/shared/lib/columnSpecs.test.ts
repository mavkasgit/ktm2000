/**
 * Семантика колонок объявляется один раз — в описании колонки, а не
 * тернарником по имени колонки в шапке и не перечислением в параметрах
 * запроса (#197, ADR-0037).
 */
import { describe, expect, it } from "vitest";

import {
  buildColumnApiParams,
  buildColumnFilterPredicate,
  buildColumnFilterValues,
  type ColumnSpec,
} from "./columnSpecs";

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

  it("несколько выбранных значений серверной колонки не отправляют ничего", () => {
    // Граница с сервером: отправлять первое из выбранных — значит фильтровать по
    // произвольному значению, которого оператор не выбирал. UI второго значения
    // не даёт выбрать (ADR-0044), но полагаться на это в сборщике нельзя.
    const params = buildColumnApiParams(
      { dimensions: new Set(['{"length_mm":2700}', '{"length_mm":900}']) },
      {},
      PARAM_COLUMNS,
    );
    expect(params.dimensions).toBeUndefined();
  });
});


/**
 * Значение колонки читается из описания (#322): клиентский предикат и список
 * значений попапера берут один и тот же `cellValue`, поэтому «показывает одно,
 * фильтрует по другому» перестаёт быть возможным.
 */
describe("buildColumnFilterPredicate и buildColumnFilterValues", () => {
  type Row = { sku: string; qty: number };

  const CLIENT_COLUMNS: ColumnSpec<"sku" | "qty", "sku" | "qty", Row>[] = [
    { filterField: "sku", sortField: "sku", clientOnly: true, cellValue: (row) => row.sku },
    { filterField: "qty", sortField: "qty", clientOnly: true, cellValue: (row) => String(row.qty) },
  ];

  const ROWS: Row[] = [
    { sku: "ЮП-460", qty: 12 },
    { sku: "ABC-100", qty: 3 },
    { sku: "ЮП-460", qty: 12 },
  ];

  it("поиск в поповере фильтрует строки значением из описания", () => {
    const predicate = buildColumnFilterPredicate<Row, "sku" | "qty", "sku" | "qty">(
      {},
      { sku: "юп" },
      CLIENT_COLUMNS,
    );

    expect(predicate).not.toBeNull();
    expect(predicate!({ sku: "ЮП-460", qty: 12 })).toBe(true);
    expect(predicate!({ sku: "ABC-100", qty: 3 })).toBe(false);
  });

  it("выбранное значение (в том числе мультивыбор) сужает строки", () => {
    const predicate = buildColumnFilterPredicate<Row, "sku" | "qty", "sku" | "qty">(
      { sku: new Set(["ЮП-460", "ABC-100"]) },
      {},
      CLIENT_COLUMNS,
    );

    expect(predicate!({ sku: "ЮП-460", qty: 12 })).toBe(true);
    expect(predicate!({ sku: "ABC-100", qty: 3 })).toBe(true);
    expect(predicate!({ sku: "ЮП-200", qty: 1 })).toBe(false);
  });

  it("колонка без читателя не отсеивает строки", () => {
    const columns: ColumnSpec<"sku" | "qty", "sku" | "qty", Row>[] = [
      { filterField: "sku", clientOnly: true, cellValue: (row) => row.sku },
    ];
    const predicate = buildColumnFilterPredicate<Row, "sku" | "qty", "sku" | "qty">(
      { qty: new Set(["12"]) },
      {},
      columns,
    );

    // Значения для `qty` никто не объявил: `selected.has("")` не должен
    // выбросить все строки.
    expect(predicate!({ sku: "ABC-100", qty: 3 })).toBe(true);
  });

  it("без активных фильтров предиката нет", () => {
    expect(
      buildColumnFilterPredicate<Row, "sku" | "qty", "sku" | "qty">({}, {}, CLIENT_COLUMNS),
    ).toBeNull();
  });

  it("список значений собирается по читателям описания, без повторов", () => {
    expect(buildColumnFilterValues(ROWS, CLIENT_COLUMNS)).toEqual({
      sku: ["ЮП-460", "ABC-100"],
      qty: ["12", "3"],
    });
  });

  it("порядок списка значений объявляет колонка", () => {
    const columns: ColumnSpec<"sku" | "qty", "sku" | "qty", Row>[] = [
      {
        filterField: "qty",
        clientOnly: true,
        cellValue: (row) => String(row.qty),
        sortValues: (a, b) => Number(a) - Number(b),
      },
    ];

    expect(buildColumnFilterValues(ROWS, columns).qty).toEqual(["3", "12"]);
  });

  it("колонка без читателя в список значений не попадает: попапера у неё нет", () => {
    const columns: ColumnSpec<"sku" | "qty", "sku" | "qty", Row>[] = [
      { filterField: "sku", clientOnly: true },
    ];

    expect(buildColumnFilterValues(ROWS, columns)).toEqual({});
  });
});
