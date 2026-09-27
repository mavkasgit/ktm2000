import { describe, expect, it } from "vitest";
import { buildPlanSortParam, mapPlanSortFieldToApi } from "./planApiParams";
import type { PlanSortField } from "./plan-labels";

/**
 * Список полей, которые backend реально сортирует:
 * ALL_POSITIONS_SORT_FIELDS в backend/app/api/routes/production_plans.py.
 * Держим здесь явно, чтобы расхождение с бэкендом ловилось этим тестом.
 */
const BACKEND_SORT_FIELDS = new Set([
  "id",
  "source_row_number",
  "source_sku",
  "source_name",
  "quantity",
  "status",
  "validation_status",
  "dimensions",
  "errors",
]);

describe("mapPlanSortFieldToApi", () => {
  it("наименование сортируется по source_name, а не подменяется номером строки", () => {
    expect(mapPlanSortFieldToApi("name")).toBe("source_name");
  });

  it("id сортируется по первичному ключу позиции", () => {
    expect(mapPlanSortFieldToApi("id")).toBe("id");
  });

  it("число ошибок сортируется по серверному полю errors", () => {
    expect(mapPlanSortFieldToApi("errors")).toBe("errors");
  });

  it("остальные поддерживаемые колонки мапятся на свои серверные поля", () => {
    expect(mapPlanSortFieldToApi("rowNum")).toBe("source_row_number");
    expect(mapPlanSortFieldToApi("sku")).toBe("source_sku");
    expect(mapPlanSortFieldToApi("qty")).toBe("quantity");
    expect(mapPlanSortFieldToApi("dimensions")).toBe("dimensions");
    expect(mapPlanSortFieldToApi("status")).toBe("status");
    expect(mapPlanSortFieldToApi("validation")).toBe("validation_status");
  });

  it("неподдерживаемые сервером поля дают undefined, а не чужое поле", () => {
    // route собирается в Python (resolve_position_route), warnings — из
    // последнего PlanChangeItem позиции; в SQL ORDER BY они не выражаются.
    expect(mapPlanSortFieldToApi("route")).toBeUndefined();
    expect(mapPlanSortFieldToApi("warnings")).toBeUndefined();
  });

  it("набор полей сортировки в точности совпадает с серверным", () => {
    // Двусторонняя сверка: лишний маппинг (фронт шлёт поле, которого нет
    // на сервере) и пропуск (сервер умеет, а колонка не сортируется) — оба
    // ломают порядок строк, оба ловятся здесь.
    const fields: PlanSortField[] = [
      "id",
      "rowNum",
      "sku",
      "name",
      "qty",
      "route",
      "dimensions",
      "status",
      "validation",
      "errors",
      "warnings",
    ];
    const mapped = new Set(
      fields.map(mapPlanSortFieldToApi).filter((f): f is string => f !== undefined),
    );
    expect([...mapped].sort()).toEqual([...BACKEND_SORT_FIELDS].sort());
  });
});

describe("buildPlanSortParam", () => {
  it("пустая сортировка — параметр sort не уезжает вовсе", () => {
    expect(buildPlanSortParam([])).toBeUndefined();
  });

  it("уезжают ВСЕ выбранные приоритеты, от старшего к младшему", () => {
    // Регресс: раньше на сервер уходил только sortConfigs[0], а шапка уже
    // показывала приоритет 2 — оператор кликал вторую колонку и не видел
    // эффекта.
    expect(
      buildPlanSortParam([
        { field: "qty", order: "asc" },
        { field: "name", order: "desc" },
        { field: "status", order: "asc" },
      ]),
    ).toBe("quantity:asc,source_name:desc,status:asc");
  });

  it("направление desc не перепутано с asc", () => {
    // Первый клик по иконке даёт desc — сервер должен получить именно desc.
    expect(buildPlanSortParam([{ field: "name", order: "desc" }])).toBe("source_name:desc");
  });

  it("неподдерживаемые колонки пропускаются, поддерживаемые уходят", () => {
    expect(
      buildPlanSortParam([
        { field: "route", order: "asc" },
        { field: "warnings", order: "desc" },
        { field: "sku", order: "asc" },
      ]),
    ).toBe("source_sku:asc");
  });

  it("одна неподдерживаемая колонка не подменяет поле сортировки", () => {
    // Раньше здесь уезжал source_row_number: пользователь кликал «Маршрут»,
    // а строки переставлялись по номеру строки исходника.
    expect(buildPlanSortParam([{ field: "route", order: "asc" }])).toBeUndefined();
    expect(buildPlanSortParam([{ field: "warnings", order: "desc" }])).toBeUndefined();
  });
});
