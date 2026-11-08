/**
 * Выравнивание строк таблицы «Расчёт подвесов» (#402).
 *
 * Регресс: ячейки артикула, периметра и габарита несли `rowSpan={lines.length}`
 * от варианта «`<tr>` на длину». Подстроки давно печатаются стопкой внутри
 * одной ячейки (`HangerLineCell`), `<tr>` у артикула одна — и `rowSpan`
 * растягивался на строку следующего артикула: её первые три ячейки браузер
 * ставил после занятых колонок, вся строка уезжала вправо на три колонки
 * (SKU оказывался под «Длиной», поля ввода — под разбивкой).
 *
 * jsdom не считает layout таблицы, поэтому сдвиг здесь не воспроизвести, и
 * число ячеек у сломанной строки было тем же — `rowSpan` меняет раскладку, а
 * не разметку. Регресс сторожит отсутствие самого атрибута; совпадение числа
 * ячеек с шапкой — вторая проверка, на лишнюю/потерянную ячейку.
 */
import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Product, ProductLength } from "@/shared/api/products";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { TableCornerResetHeader } from "@/shared/ui";
import {
  buildHangerCalcRows,
  buildPairedHangerCalcRows,
  type PairedPair,
} from "../lib/hangerCalcRows";
import { makeProduct as makeProductBase } from "../lib/productFixture";
import { hangerCalcColumns } from "../lib/hangerCalcColumns";
import { HangerCalcRowView } from "./HangerCalcRowView";
import { PairedHangerRowView } from "./PairedHangerRowView";

const productLength = (
  length_mm: number,
  raw_length_mm: number | null = null,
  is_primary = false,
): ProductLength => ({ length_mm, raw_length_mm, is_primary });

function makeProduct(overrides: Partial<Product>): Product {
  return makeProductBase({ name: "Профиль", type: "component", ...overrides });
}

/** Артикул с двумя длинами — тот, что давал `rowSpan={2}`. */
const TWO_LENGTHS = makeProduct({
  id: 1,
  sku: "ЮП-2083",
  perimeter_mm: 81.5,
  mount_width_mm: 36.9,
  lengths: [productLength(1800, null, true), productLength(2700, 2750)],
});

/** Артикул с одной длиной — следующий в таблице, он и уезжал вправо. */
const ONE_LENGTH = makeProduct({
  id: 2,
  sku: "ЮП-2183",
  perimeter_mm: 53.4,
  mount_width_mm: 18.5,
  lengths: [productLength(2700, 2750, true)],
});

/** Пара A+B с двумя длинами — у парной строки то же правило. */
const PAIR: PairedPair = {
  pairId: 7,
  productA: makeProduct({
    id: 3,
    sku: "ЮП-3000",
    lengths: [productLength(2500, null, true), productLength(2700)],
  }),
  productB: makeProduct({
    id: 4,
    sku: "ЮП-3001",
    lengths: [productLength(2500, null, true), productLength(2700)],
  }),
  lengths: [2500, 2700],
  manualPerLength: {},
};

/**
 * Таблица с настоящей шапкой: строка тела обязана попадать в те же колонки,
 * что и шапка, — это и есть предмет проверки.
 */
function renderTable(children: ReactNode) {
  return render(
    <TooltipProvider>
      <table>
        <thead>
          <tr>
            {hangerCalcColumns.map((column) => (
              <th key={column.id}>{column.label}</th>
            ))}
            <TableCornerResetHeader hasActiveFilters={false} onReset={() => {}} />
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </TooltipProvider>,
  );
}

const headerCells = (container: HTMLElement) =>
  container.querySelectorAll("thead tr > *").length;

const bodyRows = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLTableRowElement>("tbody tr"));

/** Каждая строка тела — по ячейке на колонку шапки, `rowSpan` в теле нет. */
function expectRowsMatchHeader(container: HTMLElement) {
  const expected = headerCells(container);
  const rows = bodyRows(container);
  expect(rows).toHaveLength(2);
  for (const row of rows) {
    expect(row.querySelectorAll("td")).toHaveLength(expected);
  }
  expect(container.querySelectorAll("tbody [rowspan]")).toHaveLength(0);
  return rows;
}

describe("HangerCalcRowView: ячейки строки не выходят за колонки", () => {
  it("строка после артикула с двумя длинами остаётся в своих колонках", () => {
    const [withTwoLengths, withOneLength] = buildHangerCalcRows(
      [TWO_LENGTHS, ONE_LENGTH],
      new Map(),
      new Map(),
    );

    const { container } = renderTable(
      <>
        <HangerCalcRowView
          row={withTwoLengths}
          saveState={undefined}
          readOnly
          onEdit={() => {}}
          onCommit={async () => {}}
        />
        <HangerCalcRowView
          row={withOneLength}
          saveState={undefined}
          readOnly
          onEdit={() => {}}
          onCommit={async () => {}}
        />
      </>,
    );

    const rows = expectRowsMatchHeader(container);
    // Следующий артикул — в первой колонке, как и все остальные строки.
    expect(rows[1].querySelectorAll("td")[0].textContent).toContain(ONE_LENGTH.sku);
  });

  it("строка после парной строки с двумя длинами тоже остаётся в своих колонках", () => {
    const [paired] = buildPairedHangerCalcRows([PAIR], new Map(), new Map());
    const [single] = buildHangerCalcRows([ONE_LENGTH], new Map(), new Map());

    const { container } = renderTable(
      <>
        <PairedHangerRowView row={paired} />
        <HangerCalcRowView
          row={single}
          saveState={undefined}
          readOnly
          onEdit={() => {}}
          onCommit={async () => {}}
        />
      </>,
    );

    const rows = expectRowsMatchHeader(container);
    expect(rows[1].querySelectorAll("td")[0].textContent).toContain(ONE_LENGTH.sku);
  });
});
