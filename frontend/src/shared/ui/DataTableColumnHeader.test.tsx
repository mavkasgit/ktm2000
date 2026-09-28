/**
 * Шапка собирается из описания колонки, и по этому описанию решается, чем
 * оператор выбирает значение и уходит ли набранный текст в запрос. Обе развилки
 * проверяются здесь на настоящем хуке состояния, а не на переданных колбэках:
 * иначе тест повторил бы пересылку пропсов и ничего бы не защищал.
 */
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSortableColumnFilters } from "@/shared/hooks/useSortableColumnFilters";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

import { DataTableColumnHeader } from "./DataTableColumnHeader";

type Field = "sku" | "status" | "dimensions";

afterEach(cleanup);

function mountColumnHeader(
  column: ColumnSpec<Field> & { label: string },
  values: string[],
) {
  const state: { current: ReturnType<typeof useSortableColumnFilters<Field>> | null } = {
    current: null,
  };

  function Harness() {
    const hook = useSortableColumnFilters<Field>();
    state.current = hook;
    return (
      <DataTableColumnHeader<Field, Field>
        column={column}
        bindColumn={hook.bindColumn}
        values={values}
        currentSorts={[]}
        onSortChange={vi.fn()}
      />
    );
  }

  render(<Harness />);

  return {
    /** Попапер открыт так же, как у оператора: кликом по подписи колонки. */
    open: () => fireEvent.click(screen.getByText(column.label)),
    selected: () => state.current!.columnFilters,
    searches: () => state.current!.columnSearchQueries,
    hasActiveFilters: () => state.current!.hasActiveColumnFilters,
  };
}

describe("DataTableColumnHeader", () => {
  it("у серверной колонки выбор остаётся одним значением", () => {
    const header = mountColumnHeader(
      { filterField: "sku", sortField: "sku", label: "Артикул" },
      ["ЮП-460", "ABC-100"],
    );
    header.open();

    fireEvent.click(screen.getByText("ЮП-460"));
    fireEvent.click(screen.getByText("ABC-100"));

    // Второе значение заменило первое: сервер на такую колонку принимает одно.
    expect(header.selected()).toEqual({ sku: new Set(["ABC-100"]) });
  });

  it("у колонки, которую фильтрует сам экран, выбор может быть из нескольких значений", () => {
    const header = mountColumnHeader(
      { filterField: "status", sortField: "status", label: "Статус", clientOnly: true },
      ["Годен", "Брак"],
    );
    header.open();

    fireEvent.click(screen.getByText("Годен"));
    fireEvent.click(screen.getByText("Брак"));

    expect(header.selected()).toEqual({ status: new Set(["Годен", "Брак"]) });
  });

  it("поиск у обычной колонки доезжает до состояния таблицы", () => {
    // Контр-случай к следующему: молчание точной колонки должно объясняться
    // exactMatch, а не тем, что обработчик вообще не подключён.
    const header = mountColumnHeader(
      { filterField: "sku", sortField: "sku", label: "Артикул" },
      ["ЮП-460", "ABC-100"],
    );
    header.open();

    fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "ЮП" } });

    expect(header.searches()).toEqual({ sku: "ЮП" });
    expect(header.hasActiveFilters()).toBe(true);
  });

  it("поиск у точной колонки остаётся локальным и не попадает в состояние таблицы", () => {
    // «Размер» выбирается кликом по габариту, а набранный текст живёт только
    // внутри поповера. Если бы он ушёл в состояние таблицы, счётчик активных
    // фильтров и кнопка сброса загорелись бы впустую: в запрос точной колонки
    // поиск не уезжает.
    const header = mountColumnHeader(
      { filterField: "dimensions", sortField: "dimensions", exactMatch: true, label: "Размер" },
      ["2700x1500", "1800x600"],
    );
    header.open();

    fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "1800" } });

    expect(header.searches()).toEqual({});
    expect(header.hasActiveFilters()).toBe(false);
  });

  it("у точной колонки текст сужает список значений на экране, а выбранное остаётся", () => {
    // Поповер рисуется по описанию колонки, и «Размер» обязан получить тот,
    // где текст ищет по списку. Получи серверный — выбор молча снялся бы на
    // первом же символе, а оператор искал бы по списку, которого на экране
    // нет.
    const header = mountColumnHeader(
      { filterField: "dimensions", sortField: "dimensions", exactMatch: true, label: "Размер" },
      ["2700x1500", "1800x600"],
    );
    header.open();
    fireEvent.click(screen.getByText("2700x1500"));

    fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "1800" } });

    expect(screen.getByText("1800x600")).toBeTruthy();
    expect(screen.queryByText("2700x1500")).toBeNull();
    expect(screen.queryByText(/Список значений скрыт/)).toBeNull();
    expect(header.selected()).toEqual({ dimensions: new Set(["2700x1500"]) });
  });

  it("у обычной колонки тот же текст убирает список и снимает выбор", () => {
    // Контр-случай к предыдущему: молчание точной колонки должно объясняться
    // `exactMatch`, а не тем, что поповер вообще не реагирует на текст.
    const header = mountColumnHeader(
      { filterField: "sku", sortField: "sku", label: "Артикул" },
      ["ЮП-460", "ABC-100"],
    );
    header.open();
    fireEvent.click(screen.getByText("ЮП-460"));

    fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "460" } });

    expect(screen.getByText(/Список значений скрыт/)).toBeTruthy();
    expect(header.selected()).toEqual({ sku: new Set() });
  });
});
