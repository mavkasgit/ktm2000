/**
 * Параметры списка сотрудников собираются из описания колонок: пока сборка
 * стояла в компоненте и перечисляла `department` строкой, шестая колонка
 * потребовала бы правки этого кода (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import { employeeColumns, EMPLOYEE_SORT_FIELD_TO_API } from "./employeeColumns";
import type { EmployeeSortField } from "./employeeColumns";

const build = (
  columnFilters: Partial<Record<EmployeeSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<EmployeeSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, employeeColumns);

/**
 * Белый список полей сортировки на стороне API. Источник истины —
 * `_SORT_COLUMNS` в `backend/app/services/hrms_employees.py`: `apply_sort`
 * отвечает 400 на поле, которого в таблице нет, а молчаливый фолбэк на `name`
 * показал бы оператору чужой порядок строк.
 */
const API_SORT_FIELDS = ["hrms_id", "name", "tab_number", "position", "department"];


describe("параметры списка сотрудников", () => {
  it("выбранное значение уезжает под своим именем параметра", () => {
    expect(build({ department: new Set(["Сварка"]) })).toEqual({ department: "Сварка" });
  });

  it("поиск в поповере уезжает подстрокой — так его понимает сервер", () => {
    // `list_employees` сравнивает подразделение через `ilike`, а не точно.
    expect(build({}, { department: "свар" })).toEqual({ department: "свар" });
  });

  it("«—» — это отсутствие подразделения, а не его имя", () => {
    // Пустое подразделение показывается в поповере как «—», но сервер такого
    // значения не знает: уехавшее «—» сузило бы список не по тому, что
    // выбрал оператор.
    expect(build({ department: new Set(["—"]) })).toEqual({});
  });

  it("колонка без выбранного значения ничего не шлёт", () => {
    expect(build({})).toEqual({});
  });

  it("ни одна колонка не clientOnly: единственный фильтр уезжает на сервер", () => {
    // Клиентская колонка сборщиком пропускается. Здесь такой нет: фильтр
    // «Подразделение» применяет сервер, и потеря clientOnly убрала бы его из
    // запроса молча.
    expect(employeeColumns.filter((column) => column.clientOnly)).toEqual([]);
  });

  it("фильтр объявлен только у той колонки, которую фильтрует сервер", () => {
    // `list_employees` принимает `department`, `search` и `sort` — и больше
    // ничего. Поповер у колонки, параметра у которой сервер не знает, молчал
    // бы: значение уходило в состояние таблицы и выборку не сужало.
    expect(
      employeeColumns.flatMap((column) => (column.filterField ? [column.filterField] : [])),
    ).toEqual(["department"]);
  });
});

describe("сортировка списка сотрудников", () => {
  it("у каждой колонки есть поле сортировки, принимаемое API", () => {
    const sortable = employeeColumns.filter((column) => column.sortField);

    expect(sortable.length).toBe(employeeColumns.length);

    for (const column of sortable) {
      const apiField = EMPLOYEE_SORT_FIELD_TO_API[column.sortField ?? "name"];
      expect(apiField, `колонка «${column.label}» должна сортироваться сервером`).toBeDefined();
      expect(API_SORT_FIELDS).toContain(apiField);
    }
  });

  it("различает колонки, чьё поле на сервере называется иначе", () => {
    // Подмена чужого поля молчаливая: оператор кликнул «HRMS ID» и увидел
    // порядок по имени.
    expect(EMPLOYEE_SORT_FIELD_TO_API.hrmsId).toBe("hrms_id");
    expect(EMPLOYEE_SORT_FIELD_TO_API.tabNumber).toBe("tab_number");
    expect(EMPLOYEE_SORT_FIELD_TO_API.name).toBe("name");
  });

  it("у каждой колонки description есть поле, по которому её фильтруют", () => {
    // `DataTableColumnHeader` ищет активную сортировку по `filterField ??
    // sortField`, поэтому у колонки с фильтром поле сортировки обязано быть
    // тем же самым: иначе значок сортировки не нашёлся бы никогда.
    for (const column of employeeColumns) {
      if (!column.filterField) continue;
      expect(column.sortField).toBe(column.filterField);
    }
  });
});
