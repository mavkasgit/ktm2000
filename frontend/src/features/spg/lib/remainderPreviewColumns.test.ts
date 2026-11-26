/**
 * Параметры предпросмотра импорта остатков собираются из описания колонок:
 * пока сборка стояла в диалоге и перечисляла восемь колонок руками, девятая
 * потребовала бы правки кода (#198, ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import type { RemainderPreviewSortField } from "@/shared/lib/stockSortParams";

import {
  remainderPreviewColumns,
  REMAINDER_PREVIEW_CHEVRON_COLUMN_WIDTH,
  REMAINDER_PREVIEW_RESET_COLUMN_WIDTH,
} from "./remainderPreviewColumns";

const build = (
  columnFilters: Partial<Record<RemainderPreviewSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<RemainderPreviewSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, remainderPreviewColumns);

describe("колонки предпросмотра остатков", () => {
  it("идут в порядке спеки §10.1", () => {
    expect(remainderPreviewColumns.map((column) => column.label)).toEqual([
      "#",
      "Код 1С",
      "Артикул",
      "Наименование",
      "Кол-во, шт",
      "Метры",
      "Длина",
      "Операции",
      "Качество",
      "Участок",
      "Ошибки",
    ]);
  });

  it("источник (код 1С, наименование, метры) — без фильтра и сортировки", () => {
    // Сервер фильтрует `source_code` только общим поиском, а колонок
    // «наименование» и «метры» в контракте предпросмотра нет вовсе:
    // объявленный фильтр отправил бы параметр, которого никто не читает
    // (спека §5.2, ADR-0038 §4).
    for (const id of ["source_code", "source_name", "meters"]) {
      const column = remainderPreviewColumns.find((candidate) => candidate.id === id);
      expect(column, `колонка ${id}`).toBeDefined();
      expect(column?.filterField).toBeUndefined();
      expect(column?.sortField).toBeUndefined();
    }
  });

  it("ширины складываются в 100%: иначе table-fixed перераспределит остаток", () => {
    // Таблица предпросмотра виртуализирована, поэтому раскладка фиксированная:
    // ширины не должны зависеть от смонтированных строк. Служебные колонки
    // (шеврон и сброс) объявлены рядом, а не в диалоге.
    const total = [...remainderPreviewColumns.map((column) => column.width), REMAINDER_PREVIEW_CHEVRON_COLUMN_WIDTH, REMAINDER_PREVIEW_RESET_COLUMN_WIDTH]
      .reduce((sum, width) => sum + Number.parseFloat(width), 0);
    expect(total).toBeCloseTo(100, 5);
  });
});

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
