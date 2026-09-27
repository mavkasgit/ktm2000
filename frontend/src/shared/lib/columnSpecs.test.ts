/**
 * Семантика колонок объявляется один раз — в описании колонки, а не
 * тернарником по имени колонки в шапке и не перечислением в параметрах
 * запроса (#197, ADR-0037).
 */
import { describe, expect, it } from "vitest";

import { exactMatchColumnParams, type ColumnSpec } from "./columnSpecs";

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

  it("несколько выбранных значений точной колонки дают первый", () => {
    // Точное совпадение по определению не мультизначное: «Размер» — это
    // один габарит, а не набор. Значение отбирается первым, как и раньше.
    const params = exactMatchColumnParams(
      { dimensions: new Set(['{"length_mm":2700}', '{"length_mm":900}']) },
      COLUMNS,
    );
    expect(params).toEqual({ dimensions: '{"length_mm":2700}' });
  });
});
