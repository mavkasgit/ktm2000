import { describe, expect, it } from "vitest";
import { buildPlanColumnApiParams, buildPlanPositionsQuery, buildPlanSortParam, mapPlanSortFieldToApi } from "./planApiParams";
import { isRouteFilterClientSide, PLAN_CLIENT_FILTER_FIELDS, planColumns } from "./planColumns";
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

describe("buildPlanColumnApiParams", () => {
  it("выбранный габарит уезжает в запрос — фильтр «Размер» работает", () => {
    // Сборщик отдавал `dimensions`, а страница перечисляла поля запроса руками
    // и его там не было: фильтр был виден и не фильтровал ничего.
    const params = buildPlanColumnApiParams({ dimensions: new Set(['{"length_mm":2700}']) }, {});

    expect(params.dimensions).toBe('{"length_mm":2700}');
  });

  it("поиск габарита в поповере не подменяется выбранным значением", () => {
    const params = buildPlanColumnApiParams(
      { dimensions: new Set(['{"length_mm":2700}']) },
      { dimensions: "2,7" },
    );

    expect(params.dimensions).toBe('{"length_mm":2700}');
  });

  it("колонки, фильтруемые на клиенте, в запрос не уезжают", () => {
    const params = buildPlanColumnApiParams(
      { id: new Set(["42"]), rowNum: new Set(["7"]), qty: new Set(["5"]) },
      { id: "42", rowNum: "7", qty: "5" },
    );

    expect(params).toEqual({});
  });

  it("артикул и наименование уезжают под серверными именами", () => {
    expect(buildPlanColumnApiParams({ sku: new Set(["КР-01"]) }, { name: "Брус" })).toEqual({
      source_sku: "КР-01",
      source_name: "Брус",
    });
  });

  it("«Не назначен» в маршруте уезжает как отсутствие маршрута", () => {
    expect(buildPlanColumnApiParams({ route: new Set(["Не назначен"]) }, {})).toEqual({ has_route: "no" });
    expect(buildPlanColumnApiParams({ route: new Set(["Пиление"]) }, {})).toEqual({ has_route: "yes" });
  });

  it("нулевые ошибки и предупреждения уезжат как их отсутствие", () => {
    expect(buildPlanColumnApiParams({ errors: new Set(["0"]), warnings: new Set(["0"]) }, {})).toEqual({
      has_errors: "no",
      has_warnings: "no",
    });
  });

  it("без фильтров параметров не уезжает вовсе", () => {
    expect(buildPlanColumnApiParams({}, {})).toEqual({});
  });
});

describe("isRouteFilterClientSide — куда уходит фильтр «Маршрут»", () => {
  it("конкретный маршрут фильтруется на клиенте: сервер знает только «назначен или нет»", () => {
    // В запрос ушёл бы `has_route=yes`, а это все строки с любым маршрутом:
    // фильтр выглядел бы работающим и показывал лишнее.
    expect(isRouteFilterClientSide({ route: new Set(["Пиление"]) }, {})).toBe(true);
  });

  it("поиск конкретного маршрута в поповере — тоже клиентский", () => {
    expect(isRouteFilterClientSide({}, { route: "Пиление" })).toBe(true);
  });

  it("«Не назначен» — серверный фильтр, клиент вмешиваться не должен", () => {
    expect(isRouteFilterClientSide({ route: new Set(["Не назначен"]) }, {})).toBe(false);
  });

  it("без выбранного маршрута фильтр не клиентский", () => {
    expect(isRouteFilterClientSide({}, {})).toBe(false);
    expect(isRouteFilterClientSide({ route: new Set() }, {})).toBe(false);
  });
});

describe("PLAN_CLIENT_FILTER_FIELDS — что страница сужает у себя", () => {
  it("в списке ровно те колонки, которые объявлены clientOnly в описании", () => {
    // Перечисление в странице расходилось бы с описанием молча: колонка
    // переехала бы в запрос, который такого фильтра не знает.
    expect(PLAN_CLIENT_FILTER_FIELDS).toEqual(
      planColumns.filter((column) => column.clientOnly).map((column) => column.filterField),
    );
    expect(PLAN_CLIENT_FILTER_FIELDS).toContain("qty");
    expect(PLAN_CLIENT_FILTER_FIELDS).not.toContain("route");
  });
});

describe("buildPlanPositionsQuery", () => {
  const base = { limit: 50, offset: 0, search: "", sort: undefined };
  const noPanel = {
    status: "all",
    validationStatus: "all",
    hasRoute: "all",
    hasErrors: "all",
    hasWarnings: "all",
  };

  it("выбранный габарит доезжает до запроса — фильтр «Размер» работает", () => {
    // Страница перечисляла поля запроса руками и `dimensions` среди них не
    // было: фильтр собирался, показывался и не фильтровал ничего.
    const query = buildPlanPositionsQuery(
      buildPlanColumnApiParams({ dimensions: new Set(['{"length_mm":2700}']) }, {}),
      { ...base, panel: noPanel },
    );

    expect(query.dimensions).toBe('{"length_mm":2700}');
  });

  it("без выбранного габарита параметра в запросе нет", () => {
    expect(buildPlanPositionsQuery(buildPlanColumnApiParams({}, {}), { ...base, panel: noPanel }).dimensions)
      .toBeUndefined();
  });

  it("панельный фильтр имеет приоритет над фильтром колонки", () => {
    const query = buildPlanPositionsQuery(
      buildPlanColumnApiParams({ route: new Set(["Не назначен"]) }, {}),
      { ...base, panel: { ...noPanel, hasRoute: "yes" } },
    );

    expect(query.has_route).toBe("yes");
  });

  it("при пустой панели уезжает фильтр колонки", () => {
    const query = buildPlanPositionsQuery(
      buildPlanColumnApiParams({ route: new Set(["Не назначен"]) }, {}),
      { ...base, panel: noPanel },
    );

    expect(query.has_route).toBe("no");
  });

  it("поиск обрезается, а пустой не уезжает вовсе", () => {
    expect(buildPlanPositionsQuery({}, { ...base, search: "  ", panel: noPanel }).search).toBeUndefined();
    expect(buildPlanPositionsQuery({}, { ...base, search: " брус ", panel: noPanel }).search).toBe("брус");
  });
});
