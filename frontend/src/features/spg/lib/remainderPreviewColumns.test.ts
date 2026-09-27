/**
 * Параметры предпросмотра импорта остатков собираются из описания колонок:
 * пока сборка стояла в диалоге и перечисляла восемь колонок руками, девятая
 * потребовала бы правки кода (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import type { RemainderPreviewSortField } from "@/shared/lib/stockSortParams";

import { remainderPreviewColumns } from "./remainderPreviewColumns";

const build = (
  columnFilters: Partial<Record<RemainderPreviewSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<RemainderPreviewSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, remainderPreviewColumns);

describe("параметры предпросмотра остатков", () => {
  it("значения колонок уезжают под своими именами", () => {
    expect(
      build({
        row: new Set(["3"]),
        sku: new Set(["КР-01"]),
        quantity: new Set(["5"]),
        length: new Set(["2,7 м"]),
        operations: new Set(["Пиление"]),
        quality: new Set(["Годное"]),
        section: new Set(["Сушка"]),
      }),
    ).toEqual({
      row: "3",
      sku: "КР-01",
      quantity: "5",
      length: "2,7 м",
      operations: "Пиление",
      quality: "Годное",
      section: "Сушка",
    });
  });

  it("«—» и «Ошибка» в ошибках не уезжают: это отсутствие значения, а не значение", () => {
    expect(build({ errors: new Set(["—"]) })).toEqual({});
    expect(build({ errors: new Set(["Ошибка"]) })).toEqual({});
    expect(build({ errors: new Set(["Неизвестный участок"]) })).toEqual({ errors: "Неизвестный участок" });
  });

  it("длина фильтруется подстрокой, а не точным габаритом", () => {
    // Бэкенд предпросмотра сравнивает подпись `dimensions_label` через
    // `needle in haystack`, параметра точного совпадения у него нет.
    expect(build({}, { length: "2,7" })).toEqual({ length: "2,7" });
  });

  it("поиск артикула уезжает подстрокой", () => {
    expect(build({}, { sku: "КР" })).toEqual({ sku: "КР" });
  });

  it("без фильтров параметров не уезжает", () => {
    expect(build({})).toEqual({});
  });
});
