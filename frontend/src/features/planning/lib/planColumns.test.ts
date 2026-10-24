/**
 * Описание колонок плана — единственное место, где объявлено, что колонка
 * показывает и каким параметром уезжает в запрос (ADR-0038).
 *
 * Здесь фиксируется контракт колонок «Ошибки» и «Предупр.» (#328):
 * счётчик предупреждений читается с самой позиции (`validation_warnings`),
 * а сортировка и фильтр «по ошибкам» считаются сервером только по ошибкам —
 * предупреждения в них не подмешиваются.
 */
import { describe, expect, it } from "vitest";

import type { PlanPositionOut } from "@/shared/api/productionPlans";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";

import { planColumns } from "./planColumns";

const position = (overrides: Partial<PlanPositionOut>): PlanPositionOut => ({
  id: 1,
  production_plan_id: 1,
  source_sku: "ЮП-460",
  source_name: "Профиль ЮП-460",
  quantity: "100",
  status: "draft",
  validation_status: "valid",
  errors: [],
  validation_warnings: [],
  source_row_number: 5,
  product_id: 10,
  route_id: null,
  route_profile_id: null,
  route_name: null,
  route_source: null,
  route_origin: null,
  route_match_quality: null,
  route_match_reason: null,
  route_assigned_at: null,
  route_manual_confirmed_at: null,
  route_error: null,
  raw_excel_row: null,
  ...overrides,
});

const column = (id: string) => planColumns.find((spec) => spec.id === id);

describe("колонка «Предупр.» (#328)", () => {
  it("стоит рядом с «Ошибками” и объявлена один раз в описании", () => {
    const ids = planColumns.map((spec) => spec.id);
    expect(ids.indexOf("warnings")).toBe(ids.indexOf("errors") + 1);
    expect(column("warnings")?.label).toBe("Предупреждения");
  });

  it("считает предупреждения персистированные на позиции", () => {
    const spec = column("warnings");
    const row = position({ validation_warnings: ["product_name_missing", "input_dimensions_unresolved"] });

    expect(spec?.cellValue!(row)).toBe("2");
  });

  it("без предупреждений печатает ноль, а не пустую строку", () => {
    expect(column("warnings")?.cellValue!(position({}))).toBe("0");
  });

  it("legacy-поле warnings из старого ответа не читается (#334)", () => {
    // Бэкфилл 082 закрыл исторические строки; если старое поле всё же
    // придёт в ответе, счётчик не должен снова на него опираться.
    const row = {
      ...position({ validation_warnings: [] }),
      warnings: ["hanger_quantity_not_set:2.7"],
    } as PlanPositionOut;

    expect(column("warnings")?.cellValue!(row)).toBe("0");
  });

  it("уезжает в запрос параметром has_warnings — тем же, что у фильтра", () => {
    expect(
      buildColumnApiParams({ warnings: new Set(["1"]) }, {}, planColumns),
    ).toEqual({ has_warnings: "yes" });
  });
});

describe("колонка «Ошибки» не смешивается с предупреждениями (#328)", () => {
  it("счётчик ошибок не видит предупреждений", () => {
    const row = position({
      errors: ["product_not_found"],
      validation_warnings: ["product_name_missing", "input_dimensions_unresolved"],
    });

    expect(column("errors")?.cellValue!(row)).toBe("1");
  });

  it("предупреждения не получают сортировку: сервер сортирует только по ошибкам", () => {
    expect(column("warnings")?.sortField).toBeUndefined();
    expect(column("errors")?.sortField).toBe("errors");
  });
});
