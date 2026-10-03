/**
 * Блок «В реальной работе» переведён на общий стиль таблиц: описание
 * колонок, поповер фильтра, сортировка и кнопка сброса — те же, что у
 * остатков. Тест фиксирует контракт описания: клиентские фильтры не уезжают
 * в запрос, порядок колонок совпадает с телом таблицы, а числа сортируются
 * числами.
 */
import { describe, expect, it } from "vitest";

import type { ProductWipTask } from "@/shared/api/productionPlans";
import { buildColumnFilterPredicate } from "@/shared/lib/columnFilterSearch";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import {
  wipStatsTaskCellValue,
  wipStatsTaskColumns,
  wipStatsTaskSortValue,
  type WipStatsTaskField,
} from "./wipStatsTaskColumns";

const task = (overrides: Partial<ProductWipTask> = {}): ProductWipTask => ({
  section_id: 1,
  section_code: "ANODIZING",
  section_name: "Анодирование",
  operation_name: "Анодирование",
  section_icon: null,
  section_icon_color: null,
  dimensions: null,
  dimensions_label: "—",
  planned_qty: 10,
  completed_qty: 4,
  issued_qty: 10,
  active_tasks_count: 1,
  ...overrides,
});

const rows: ProductWipTask[] = [
  task({ operation_name: "Шампань", planned_qty: 10, completed_qty: 0 }),
  task({ operation_name: "Анодирование", planned_qty: 4, completed_qty: 4 }),
];

const predicateFor = (columnFilters: Partial<Record<WipStatsTaskField, Set<string>>>) =>
  buildColumnFilterPredicate({
    columnFilters,
    columnSearchQueries: {},
    getCellValue: wipStatsTaskCellValue,
  });

describe("описание колонок блока «в работе»", () => {
  it("порядок колонок совпадает с порядком ячеек в теле таблицы", () => {
    // Порядок `<td>` в `InWorkTaskRow`: операция, размер, задачи, план,
    // выдано, завершено.
    expect(wipStatsTaskColumns.map((column) => column.id)).toEqual([
      "operation",
      "dimensions",
      "tasks",
      "plan",
      "issued",
      "completed",
    ]);
  });

  it("у каждой колонки с фильтром есть и сортировка, иначе клик был бы молчаливым", () => {
    for (const column of wipStatsTaskColumns) {
      if (column.filterField) expect(column.sortField, column.id).toBeDefined();
    }
  });

  it("«Размер» объявлен служебной колонкой: ни фильтра, ни сортировки", () => {
    const dimensions = wipStatsTaskColumns.find((column) => column.id === "dimensions");
    expect(dimensions?.filterField).toBeUndefined();
    expect(dimensions?.sortField).toBeUndefined();
  });

  it("числовые колонки сортируются, но не фильтруются", () => {
    // Попапер из количеств сужал бы таблицу сильнее, чем помогал: выбор
    // «159» оставлял бы одну строку из двадцати.
    for (const id of ["tasks", "plan", "issued", "completed"]) {
      const column = wipStatsTaskColumns.find((item) => item.id === id);
      expect(column?.sortField, id).toBe(id);
      expect(column?.filterField, id).toBeUndefined();
    }
  });
});

describe("фильтры блока «в работе» не уезжают в запрос", () => {
  it("сервер знает только артикул", () => {
    expect(
      buildColumnApiParams(
        { operation: new Set(["Шампань"]) },
        { operation: "Анод" },
        wipStatsTaskColumns,
      ),
    ).toEqual({});
  });

  it("выбор в колонке сужает загруженные строки по операции", () => {
    const predicate = predicateFor({ operation: new Set(["Шампань"]) });
    expect(predicate ? rows.filter(predicate).map((row) => row.operation_name) : []).toEqual([
      "Шампань",
    ]);
  });

  it("поиск в поповере сужает по подстроке, как и выбор", () => {
    const predicate = buildColumnFilterPredicate({
      columnFilters: {},
      columnSearchQueries: { operation: "Шамп" },
      getCellValue: wipStatsTaskCellValue,
    });
    expect(predicate ? rows.filter(predicate).map((row) => row.operation_name) : []).toEqual([
      "Шампань",
    ]);
  });
});

describe("сортировка блока «в работе»", () => {
  it("план сортируется числом: «10» больше «4»", () => {
    const [a, b] = rows;
    // Сравнение строк дало бы обратный порядок: "10" < "4".
    expect(wipStatsTaskSortValue(a, "plan")).toBeGreaterThan(
      wipStatsTaskSortValue(b, "plan") as number,
    );
  });

  it("значение попапера совпадает с напечатанным в ячейке", () => {
    // Попапер отдаёт `wipStatsTaskCellValue`, ячейка печатает `fmtQty`.
    // Строка дробная: 2,5 округляется до «3», и попапер обязан предлагать
    // именно «3» — иначе выбор в нём не находил бы напечатанную строку.
    const fractional = task({ completed_qty: 2.5 });
    expect(wipStatsTaskCellValue(fractional, "completed")).toBe("3");
    const predicate = predicateFor({ completed: new Set(["3"]) });
    expect(predicate ? [fractional].filter(predicate) : []).toHaveLength(1);
  });
});