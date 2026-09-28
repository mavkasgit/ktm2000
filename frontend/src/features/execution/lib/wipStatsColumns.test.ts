/**
 * Сводка по незавершённому производству грузится одним запросом по артикулу:
 * сервер не знает ни одного её фильтра. Тест фиксирует именно это — что
 * выбор в колонке не уезжает в запрос под именем колонки, а сужает уже
 * загруженные строки (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import type { ProductWipRemainder } from "@/shared/api/productionPlans";
import { buildColumnFilterPredicate } from "@/shared/lib/columnFilterSearch";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import {
  wipStatsCellValue,
  wipStatsColumns,
  wipStatsSortValue,
  type WipStatsField,
} from "./wipStatsColumns";

const remainder = (name: string, quantity: number): ProductWipRemainder => ({
  spg_id: 1,
  spg_code: "SPG-1",
  spg_name: name,
  completed_ops: "Сверловка",
  spg_icon: null,
  spg_icon_color: null,
  dimensions: null,
  dimensions_label: "—",
  quantity,
  max_completed_seq: 0,
  stages_with_icons: [],
});

const rows = [remainder("ГХП А", 10), remainder("ГХП Б", 4), remainder("ГХП А", 7)];

/** Клиентский предикат диалога: тот же, что собирает `useFilterableTable`. */
const predicateFor = (columnFilters: Partial<Record<WipStatsField, Set<string>>>) =>
  buildColumnFilterPredicate({ columnFilters, columnSearchQueries: {}, getCellValue: wipStatsCellValue });

const keptNames = (predicate: ((row: ProductWipRemainder) => boolean) | null) =>
  predicate ? rows.filter(predicate).map((row) => `${row.spg_name} ${row.quantity}`) : rows.map((row) => `${row.spg_name} ${row.quantity}`);

describe("фильтры сводки незавершённого производства", () => {
  it("в запрос не уезжают: сервер знает только артикул", () => {
    expect(
      buildColumnApiParams(
        { name: new Set(["ГХП А"]), qty: new Set(["4"]) },
        { name: "ГХП" },
        wipStatsColumns,
      ),
    ).toEqual({});
  });

  it("выбор в колонке сужает загруженные строки по значению этой колонки", () => {
    expect(keptNames(predicateFor({ name: new Set(["ГХП А"]) }))).toEqual(["ГХП А 10", "ГХП А 7"]);
    // Остаток сравнивается как текст в ячейке: иначе выбор «4» не нашёл бы строку.
    expect(keptNames(predicateFor({ qty: new Set(["4"]) }))).toEqual(["ГХП Б 4"]);
  });

  it("колонка без выбора молчит: пустой набор не сужает таблицу", () => {
    expect(predicateFor({ name: new Set(), qty: new Set() })).toBeNull();
    expect(predicateFor({})).toBeNull();
  });

  it("поиск в поповере сужает по подстроке, как и выбор", () => {
    const predicate = buildColumnFilterPredicate({
      columnFilters: {},
      columnSearchQueries: { name: "Б" },
      getCellValue: wipStatsCellValue,
    });
    expect(keptNames(predicate)).toEqual(["ГХП Б 4"]);
  });
});

describe("описание колонок сводки", () => {
  it("у каждой колонки с фильтром есть и сортировка, иначе клик был бы молчаливым", () => {
    for (const column of wipStatsColumns) {
      if (column.filterField) expect(column.sortField, column.id).toBeDefined();
      if (column.sortField) expect(column.filterField, column.id).toBeDefined();
    }
  });

  it("порядок колонок совпадает с порядком ячеек в теле таблицы", () => {
    // Порядок `<td>` в `RemainderRow`: ГХП, размер, остаток.
    expect(wipStatsColumns.map((column) => column.id)).toEqual(["name", "dimensions", "qty"]);
  });

  it("«Размер» объявлен колонкой без фильтра: в запрос она не уезжает и не сортируется", () => {
    const dimensions = wipStatsColumns.find((column) => column.id === "dimensions");
    expect(dimensions?.filterField).toBeUndefined();
    expect(dimensions?.sortField).toBeUndefined();
  });

  it("остаток сортируется числом: строка «10» больше строки «4»", () => {
    const qty = wipStatsColumns.find((column) => column.id === "qty")?.sortField;
    expect(qty).toBeDefined();
    const [a, b] = [remainder("ГХП А", 10), remainder("ГХП Б", 4)];
    // Сравнение строк дало бы обратный порядок: "10" < "4".
    expect(wipStatsSortValue(a, qty!)).toBeGreaterThan(wipStatsSortValue(b, qty!) as number);
  });
});
