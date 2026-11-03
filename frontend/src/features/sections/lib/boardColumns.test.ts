/**
 * Порядок телефонных колонок доски (#345) — отдельный перечень, поэтому его
 * надо сверять с десктопным: `mobileBoardColumns` берёт описания по id, и
 * опечатка в id или новая колонка в `boardColumns` молча лишили бы телефон
 * целого столбца — его не было бы видно ни в кадре, ни под свайпом.
 */

import { describe, expect, it } from "vitest";

import { boardColumns, mobileBoardColumns, visibleBoardColumns } from "./boardColumns";

const ids = (columns: typeof boardColumns) => columns.map((column) => column.id);
const sortedIds = (columns: typeof boardColumns) => [...ids(columns)].sort();

describe("mobileBoardColumns: телефон показывает всё, что показывает десктоп", () => {
  it("набор колонок совпадает с десктопным — ничего не теряется при переименовании id", () => {
    expect(sortedIds(mobileBoardColumns(true))).toEqual(sortedIds(boardColumns));
  });

  it("порядок — оператора, а не десктопа: профиль, размер, остаток, план, годные, брак, действие", () => {
    expect(ids(mobileBoardColumns(true)).slice(0, 7)).toEqual([
      "productSku",
      "dimensions",
      "remainingQty",
      "plannedQty",
      "completedQty",
      "rejectedQty",
      "actions",
    ]);
  });

  it("участок без упаковки теряет «Упаковку» на обоих экранах одинаково", () => {
    expect(sortedIds(mobileBoardColumns(false))).toEqual(sortedIds(visibleBoardColumns(false)));
    expect(ids(mobileBoardColumns(false))).not.toContain("packaging");
  });
});
