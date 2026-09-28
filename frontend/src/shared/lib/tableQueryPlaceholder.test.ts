/**
 * Два правила, которыми тринадцать экранов пользуются одинаково (ADR-0044).
 * Ошибаются они тихо: неверная заглушка либо уносит дерево вместе с открытым
 * поповером и набранным в нём текстом, либо подкладывает под шапку нового
 * участка задания прежнего — вместе с кнопкой «Завершить» над ними.
 */
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/shared/api/queryKeys";

import { isFirstRowsLoad, keepPreviousDataForScope } from "./tableQueryPlaceholder";

type BoardRows = { tasks: { id: number }[] };

const previousRows: BoardRows = { tasks: [{ id: 41 }] };

describe("keepPreviousDataForScope", () => {
  it("смена страницы или фильтра оставляет строки прежнего участка на экране", () => {
    // `sectionId` в ключе доски лежит вторым — так объект и читается. Дерево
    // держится на смене параметров, и если заглушка исчезнет здесь, таблица
    // размонтируется вместе с поповером и текстом, который в нём напечатали.
    const keepPrevious = keepPreviousDataForScope<BoardRows>((key) => key[1], 1);

    expect(
      keepPrevious(previousRows, {
        queryKey: queryKeys.shopfloor.board(1, { limit: 20, offset: 40 }),
      }),
    ).toBe(previousRows);
  });

  it("смена участка убирает строки прежнего, даже когда они были", () => {
    // Участок переключается плитками без размонтирования: строки прежнего под
    // шапкой нового читались бы как задания, к которым можно применить
    // «Завершить». Отрицание данных — единственный способ это скрыть.
    const keepPrevious = keepPreviousDataForScope<BoardRows>((key) => key[1], 2);

    expect(
      keepPrevious(previousRows, {
        queryKey: queryKeys.shopfloor.board(1, { limit: 20, offset: 0 }),
      }),
    ).toBeUndefined();
  });

  it("до первого ключа подставлять нечего, и экран при этом не падает", () => {
    // Первый рендер доски вызывает заглушку без прошлого ключа: чтение
    // `previousQuery` без проверки уронило бы экран до первой строки.
    const keepPrevious = keepPreviousDataForScope<BoardRows>((key) => key[1], 1);

    expect(keepPrevious(undefined)).toBeUndefined();
  });
});

describe("isFirstRowsLoad", () => {
  it.each<[string, boolean, readonly { id: number }[], boolean]>([
    // Пока строк не было ни разу, дерева на экране всё равно нет — рисуем
    // заглушку. Дальше гейт по `isLoading` уносил бы дерево на каждой смене
    // параметров вместе с открытым поповером.
    ["первая загрузка пустой таблицы", true, [], true],
    ["смена параметров при уже показанных строках", true, [{ id: 1 }], false],
    ["пустой результат без загрузки", false, [], false],
    ["загруженные строки на месте", false, [{ id: 1 }], false],
  ])("%s", (_case, isPending, rows, expected) => {
    expect(isFirstRowsLoad(isPending, rows)).toBe(expected);
  });
});
