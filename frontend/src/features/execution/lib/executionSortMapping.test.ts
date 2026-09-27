import { describe, expect, it } from "vitest";
import { executionTableColumns } from "../components/execution-table-columns";
import { buildExecutionSortParam, mapExecutionSortFieldToApi } from "./executionSortMapping";

/**
 * Белый список полей сортировки на стороне API.
 * Источник истины — `ROWS_SORT_FIELDS` в
 * `backend/app/services/production_planning_rows.py`. Запрос с полем вне
 * списка сервер молча превращает в дефолтный порядок строк.
 */
const API_SORT_FIELDS = [
  "row_number",
  "product_sku",
  "status",
  "planned_qty",
  "completed_qty",
  "due_date",
  "sequence",
  "dimensions",
] as const;

describe("mapExecutionSortFieldToApi", () => {
  it("отдаёт для каждой сортируемой колонки поле, принимаемое API", () => {
    const sortableColumns = executionTableColumns.filter((column) => column.sortField);

    expect(sortableColumns.length).toBeGreaterThan(0);

    for (const column of sortableColumns) {
      const apiField = mapExecutionSortFieldToApi(column.sortField!);
      expect(apiField, `колонка «${column.label}» должна сортироваться сервером`).toBeDefined();
      expect(API_SORT_FIELDS).toContain(apiField);
    }
  });

  it("не отдаёт API-поле для колонок, которых нет в списке сортировки бэкенда", () => {
    // ID / Наименование / Маршрут сервер сортировать не умеет: в ROWS_SORT_FIELDS
    // нет ни plan_position_id, ни source_name, ни имени маршрута.
    expect(mapExecutionSortFieldToApi("id")).toBeUndefined();
    expect(mapExecutionSortFieldToApi("name")).toBeUndefined();
    expect(mapExecutionSortFieldToApi("route")).toBeUndefined();
    expect(mapExecutionSortFieldToApi("plan")).toBeUndefined();

    const nonSortableColumns = executionTableColumns.filter((column) => !column.sortField);
    expect(nonSortableColumns.map((column) => column.id)).toEqual(
      expect.arrayContaining(["id", "name", "route"]),
    );
    for (const column of nonSortableColumns) {
      if (!column.filterField) continue;
      expect(
        mapExecutionSortFieldToApi(column.filterField),
        `колонка «${column.label}» фильтруется, но не сортируется`,
      ).toBeUndefined();
    }
  });

  it("различает поля с разными значениями, а не отдаёт константу", () => {
    const mapped = new Set(
      executionTableColumns
        .map((column) => column.sortField)
        .filter((field): field is NonNullable<typeof field> => field !== undefined)
        .map((field) => mapExecutionSortFieldToApi(field)),
    );

    expect(mapped.size).toBe(
      executionTableColumns.filter((column) => column.sortField).length,
    );
  });

  it("оставляет фильтр доступным у несортируемых колонок", () => {
    for (const id of ["id", "name", "route"] as const) {
      const column = executionTableColumns.find((candidate) => candidate.id === id);
      expect(column?.filterField, `колонка ${id} должна фильтроваться`).toBe(id);
    }
  });
});

describe("buildExecutionSortParam", () => {
  it("уезжают ВСЕ выбранные приоритеты, от старшего к младшему", () => {
    // Регресс: раньше на сервер уходил только первый поддерживаемый конфиг,
    // а шапка уже показывала приоритет 2 — кликнул вторую колонку, бейдж
    // «2» виден, эффекта нет.
    expect(
      buildExecutionSortParam([
        { field: "row", order: "asc" },
        { field: "status", order: "desc" },
        { field: "dimensions", order: "asc" },
      ]),
    ).toBe("row_number:asc,status:desc,dimensions:asc");
  });

  it("несортируемая колонка не занимает место в строке и не подменяет поле", () => {
    // ID/наименование/маршрут сервер сортировать не умеет: молчалившая
    // подмена означала бы перестановку строк по чужой колонке.
    expect(
      buildExecutionSortParam([
        { field: "name", order: "asc" },
        { field: "sku", order: "desc" },
      ]),
    ).toBe("product_sku:desc");
  });

  it("нет поддерживаемых колонок — строка не уезжает вовсе", () => {
    expect(buildExecutionSortParam([])).toBeUndefined();
    expect(buildExecutionSortParam([{ field: "route", order: "asc" }])).toBeUndefined();
  });
});
