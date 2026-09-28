/**
 * Контракт описания колонок таблицы подвесов: что уезжает в `?sort=`, что
 * остаётся на клиенте, и в каком порядке объявлены колонки (#197, ADR-0037;
 * #198, ADR-0038).
 *
 * Тест ловит поведение, а не наличие экспорта. Раньше семантика колонки жила в
 * компоненте: шапка рисовалась тремя вызовами `SortableFilterHeader` с
 * раскрытыми полями, а сортировка — вызовом `buildSortParam` с маппером
 * рядом. Стоило объявить колонку, которая на сервере не сортируется, как
 * серверную — и её поле молча уезжало бы в `?sort=`, а клиентский фильтр
 * по подписанному значению («12 шт.», «площадь») сузил бы выборку.
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import { buildHangerCalcSortParam, hangerCalcColumns } from "./hangerCalcColumns";
import type { HangerCalcSortField } from "./hangerCalcRows";

/** Фильтруемые колонки описания: ровно они попадают в попапер фильтра. */
const filterFields = hangerCalcColumns
  .map((item) => item.filterField)
  .filter((field): field is HangerCalcSortField => field !== undefined);

describe("сортировка в запросе", () => {
  it("артикул уезжает на сервер", () => {
    expect(buildHangerCalcSortParam([{ field: "sku", order: "asc" }])).toBe("sku:asc");
  });

  it("клиентская сортировка по «Итогу» не уезжает", () => {
    expect(buildHangerCalcSortParam([{ field: "total", order: "desc" }])).toBeUndefined();
  });

  it("клиентская сортировка по «Лимитеру» не уезжает", () => {
    expect(buildHangerCalcSortParam([{ field: "limiter", order: "desc" }])).toBeUndefined();
  });

  it("в цепочке остаётся только серверное поле, порядок приоритета сохраняется", () => {
    const param = buildHangerCalcSortParam([
      { field: "total", order: "desc" },
      { field: "sku", order: "asc" },
    ]);
    expect(param).toBe("sku:asc");
  });

  it("пустая сортировка не даёт параметр", () => {
    expect(buildHangerCalcSortParam([])).toBeUndefined();
  });
});

describe("клиентские фильтры не уезжают в запрос", () => {
  it("описание объявляет все три фильтруемые колонки", () => {
    expect(filterFields).toEqual(["sku", "total", "limiter"]);
  });

  it.each(filterFields)("выбранное значение колонки %s не появляется в параметрах", (field) => {
    // Значение взято подписанным, как его видит оператор в поповере: именно
    // оно уехало бы на сервер, если бы колонка потеряла `clientOnly`.
    const columnFilters: Partial<Record<HangerCalcSortField, Set<string>>> = {
      [field]: new Set(["площадь"]),
    };
    expect(buildColumnApiParams(columnFilters, {}, hangerCalcColumns)).toEqual({});
  });

  it("ни одна фильтруемая колонка не считается серверной", () => {
    // Потеря `clientOnly` у любой из них отправила бы подписанное значение
    // («площадь», «—») в запрос под именем колонки.
    for (const item of hangerCalcColumns) {
      if (item.filterField) expect(item.clientOnly).toBe(true);
    }
  });
});

describe("состав шапки", () => {
  it("у каждой колонки есть id и подпись, id не повторяются", () => {
    const ids = hangerCalcColumns.map((item) => item.id);
    for (const item of hangerCalcColumns) expect(item.label).toBeTruthy();
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("порядок описания совпадает с порядком ячеек в теле таблицы", () => {
    // Тело строки: артикул, периметр, габарит, длины, по площади, по
    // размеру, итог, лимитер, м² на подвес — девять `<td>` в
    // `HangerCalcRowView` и `PairedHangerRowView` плюс угол сброса.
    expect(hangerCalcColumns.map((item) => item.id)).toEqual([
      "sku",
      "perimeter",
      "mountWidth",
      "lengths",
      "byArea",
      "bySize",
      "total",
      "limiter",
      "areaM2",
    ]);
  });

  it("у фильтруемой колонки объявлены и фильтр, и сортировка", () => {
    for (const item of hangerCalcColumns) {
      if (item.filterField) expect(item.sortField).toBe(item.filterField);
    }
  });

  it("колонка без фильтра не объявляет сортировку", () => {
    for (const item of hangerCalcColumns) {
      if (!item.filterField) expect(item.sortField).toBeUndefined();
    }
  });
});
