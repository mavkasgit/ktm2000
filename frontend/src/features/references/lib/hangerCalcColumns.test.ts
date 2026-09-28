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
import type { Product } from "@/shared/api/products";

import {
  buildHangerCalcSortParam,
  compareHangerCalcTotals,
  hangerCalcColumns,
  hangerCalcCellValue,
  hangerCalcTotalText,
} from "./hangerCalcColumns";
import type { HangerCalcRow, HangerCalcSortField, HangerLengthLine } from "./hangerCalcRows";

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
    // Тело строки: артикул, периметр, габарит, длина, по площади, по
    // размеру, итог, лимитер, м² на подвес — девять `<td>` в
    // `HangerCalcRowView` и `PairedHangerRowView` плюс угол сброса.
    expect(hangerCalcColumns.map((item) => item.id)).toEqual([
      "sku",
      "perimeter",
      "mountWidth",
      "length",
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

/** Подстрока строки по длине: N и источник задаются тестом. */
const line = (
  total: number | null,
  overrides: Partial<HangerLengthLine> = {},
): HangerLengthLine => ({
  lengthMm: 6000,
  lengthLabel: "6000",
  isPrimary: false,
  result: null,
  total,
  source: total == null ? null : "manual",
  totalReason: null,
  breakdownReason: null,
  ...overrides,
});

/** Строка таблицы подвесов: собирается напрямую, формат берётся из строки. */
const row = (total: number | null, overrides: Partial<HangerCalcRow> = {}): HangerCalcRow => ({
  kind: "single",
  product: { sku: "ЮП-100" } as Product,
  lengths: [6000],
  primaryLength: 6000,
  auto: true,
  incompatibleReason: null,
  lines: [line(total, { isPrimary: true })],
  total,
  limiter: null,
  ...overrides,
});

describe("«Итог»: ячейка и попапер печатают одно и то же", () => {
  it("значение попапера совпадает с напечатанным в ячейке на дробном итоге", () => {
    // Ячейка печатает `hangerCalcTotalText(row)`, попапер берёт
    // `hangerCalcCellValue`. Старый попапер отдавал `String(row.total)` →
    // «2.5», тогда как в строке было «2,5».
    const fractional = row(2.5);
    expect(hangerCalcTotalText(fractional)).toBe("2,5");
    expect(hangerCalcCellValue(fractional, "total")).toBe(hangerCalcTotalText(fractional));
  });

  it("попапер не отдаёт строку, которой в таблице нет", () => {
    const fractional = row(2.5);
    expect(String(fractional.total)).not.toBe(hangerCalcCellValue(fractional, "total"));
  });

  it("ячейка и попапер берут итог строки — по основной длине, а не по любой подстроке", () => {
    // Вторая длина даёт 99 шт, но ключ ячейки и попапера — N основной (40 шт).
    // Регресс: если бы печатался максимум или N неосновной подстроки, строка и
    // попапер разошлись бы с колонкой «Итог».
    const multi = row(40, {
      auto: false,
      lines: [
        line(40, { isPrimary: true, source: "manual" }),
        line(99, { lengthMm: 7000, lengthLabel: "7000", source: "manual" }),
      ],
    });
    expect(hangerCalcTotalText(multi)).toBe("40");
    expect(hangerCalcCellValue(multi, "total")).toBe("40");
  });

  it("итог без значения печатается «—» в обоих местах", () => {
    const empty = row(null);
    expect(hangerCalcTotalText(empty)).toBe("—");
    expect(hangerCalcCellValue(empty, "total")).toBe("—");
  });

  it("значения попапера сортируются так, как они напечатаны", () => {
    // Старый `Number(a) - Number(b)` на «2,5» давал NaN, и дробные значения
    // вставали в произвольном месте списка.
    const values = [row(10), row(4), row(2.5), row(7), row(null)].map((item) =>
      hangerCalcCellValue(item, "total"),
    );
    expect([...values].sort(compareHangerCalcTotals)).toEqual(["2,5", "4", "7", "10", "—"]);
  });

  it("сортировка колонки «Итог» — та же, что у значений в попапере", () => {
    const total = hangerCalcColumns.find((item) => item.id === "total");
    expect(total?.sortValues).toBe(compareHangerCalcTotals);
  });
});
