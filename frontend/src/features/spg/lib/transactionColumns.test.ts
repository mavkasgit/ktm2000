/**
 * Параметры ящика истории движения собираются из описания колонок: пока
 * сборка стояла в ящике и перечисляла колонки руками, короткое имя колонки
 * («from») отдельно от длинного имени параметра (`from_location`) надо было
 * держать в уме — опечатка в параметре сужала выборку до пустой (#198,
 * ADR-0038).
 */
import { describe, expect, it } from "vitest";

import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import type { TransactionSortField } from "@/shared/lib/stockSortParams";

import { transactionColumns } from "./transactionColumns";

const build = (
  columnFilters: Partial<Record<TransactionSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TransactionSortField, string>> = {},
) => buildColumnApiParams(columnFilters, columnSearchQueries, transactionColumns);

/**
 * Ключи контракта запроса. Сверка с этим набором — единственный способ
 * поймать опечатку в имени параметра: сборщик отдаёт строки, и бэкенд
 * молча проигнорирует незнакомое имя, вернув полную выборку.
 */
const CONTRACT_KEYS = new Set([
  "reason",
  "from_location",
  "to_location",
  "quality_state",
  "comment",
]);

describe("параметры ящика истории движения", () => {
  it("выбранное значение каждой фильтруемой колонки уезжает под своим параметром", () => {
    expect(
      build({
        reason: new Set(["Ручной приход"]),
        from: new Set(["Склад готовой продукции"]),
        to: new Set(["Пиление"]),
        quality: new Set(["Брак"]),
        comment: new Set(["Пересчёт"]),
      }),
    ).toEqual({
      reason: "Ручной приход",
      from_location: "Склад готовой продукции",
      to_location: "Пиление",
      quality_state: "scrap",
      comment: "Пересчёт",
    });
  });

  it("уезжают только те ключи, которые знает бэкенд", () => {
    const params = build({
      reason: new Set(["Ручной приход"]),
      from: new Set(["Пиление"]),
      to: new Set(["Сушка"]),
      quality: new Set(["Годный"]),
      comment: new Set(["Пересчёт"]),
    });

    expect(Object.keys(params)).toHaveLength(CONTRACT_KEYS.size);
    for (const key of Object.keys(params)) {
      expect(CONTRACT_KEYS.has(key)).toBe(true);
    }
  });

  it("короткие имена колонок в параметры не уезжают", () => {
    const params = build({
      from: new Set(["Пиление"]),
      to: new Set(["Сушка"]),
      quality: new Set(["Годный"]),
    });

    expect(params).not.toHaveProperty("from");
    expect(params).not.toHaveProperty("to");
    expect(params).not.toHaveProperty("quality");
  });

  it("«—» — это отсутствие значения, а не значение: в запрос оно не уезжает", () => {
    // Участок без названия показан как «—», а сервер такого не понимает:
    // `from_location=—` сузил бы выборку до нуля строк.
    expect(build({ from: new Set(["—"]), to: new Set(["—"]) })).toEqual({});
    expect(build({ reason: new Set(["—"]), comment: new Set(["—"]) })).toEqual({});
    expect(build({ quality: new Set(["—"]) })).toEqual({});
  });

  it("качество уезжает кодом состояния, а не подписью", () => {
    // `quality_state` у бэкенда — точное совпадение с элементом перечисления,
    // поэтому подпись колонки переводится в код и для перехода
    // «Годный → Брак» берётся состояние «из».
    expect(build({ quality: new Set(["Годный"]) })).toEqual({ quality_state: "good" });
    expect(build({ quality: new Set(["Окончательный брак"]) })).toEqual({
      quality_state: "final_scrap",
    });
    expect(build({ quality: new Set(["Переделка"]) })).toEqual({ quality_state: "rework" });
    expect(build({ quality: new Set(["Годный → Брак"]) })).toEqual({ quality_state: "good" });
  });

  it("качество уезжает выбранным значением, а не результатом поиска в попапере", () => {
    // Поиск в поповере лишь сужает список значений: отправить «год» значило бы
    // спросить у сервера состояние, которого нет, и получить 422.
    expect(build({ quality: new Set(["Годный"]) }, { quality: "год" })).toEqual({
      quality_state: "good",
    });
  });

  it("участки и комментарий фильтруются подстрокой", () => {
    expect(build({}, { from: "пил" })).toEqual({ from_location: "пил" });
    expect(build({}, { to: "суш" })).toEqual({ to_location: "суш" });
    expect(build({}, { comment: "пере" })).toEqual({ comment: "пере" });
  });

  it("колонка без выбранного значения молчит", () => {
    expect(build({})).toEqual({});
    expect(build({}, {})).toEqual({});
    // Пустой набор — это не выбор значения, а снятие фильтра.
    expect(build({ from: new Set(), to: new Set(), quality: new Set() })).toEqual({});
  });

  it("колонки без фильтра в запрос не уезжают", () => {
    // У `GET /stock/transactions` нет ни параметра количества, ни фильтра по
    // одному моменту времени (только диапазон из панели), поэтому «Дата» и
    // «Кол-во» объявлены сортируемыми, но без фильтра.
    expect(
      build(
        { date: new Set(["12.09.2026 10:00:00"]), quantity: new Set(["12 шт."]) },
        { date: "12.09.2026", quantity: "12" },
      ),
    ).toEqual({});
  });
});

describe("описание колонок ящика истории движения", () => {
  it("у каждой колонки с фильтром объявлена сортировка", () => {
    for (const column of transactionColumns) {
      if (column.filterField) {
        expect(column.sortField, `колонка «${column.label}»`).toBeTruthy();
      }
    }
  });

  it("у каждой колонки, которая что-то отправляет, объявлено имя параметра", () => {
    for (const column of transactionColumns) {
      if (column.filterField) {
        expect(
          column.apiParam ?? column.filterField,
          `колонка «${column.label}»`,
        ).toBeTruthy();
      }
    }
  });
});
