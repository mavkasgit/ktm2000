/**
 * Поповер фильтра — общий слой: он решает, чем оператор выбирает значение и
 * когда набранный текст забирает контрол себе. Ошибка здесь тихая: поповер
 * продолжает выглядеть рабочим, а в запрос уезжает не то.
 */
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SortableFilterHeader, type SortableFilterHeaderProps } from "./SortableFilterHeader";

type Field = "sku";

afterEach(cleanup);

/**
 * Поповер живёт по клику в шапке — так им пользуется оператор, и так же он
 * открывается в тесте: состояние держит сам радикс, снаружи его не включить.
 * Значение и текст держит обвязка, как их держит `useSortableColumnFilters`,
 * иначе компонент нельзя было бы проверить вовсе.
 */
function mountFilterPopover(props: Partial<SortableFilterHeaderProps<Field>> = {}) {
  /** Что компонент отдал наружу при каждом изменении выбора, по порядку. */
  const emittedSelections: Set<string>[] = [];
  /** Текст на момент «применить» — «Готово» и Enter не могут применить пустое. */
  const appliedQueries: string[] = [];

  function Harness() {
    const [selected, setSelected] = useState<Set<string>>(new Set<string>());
    const [query, setQuery] = useState("");
    return (
      <SortableFilterHeader<Field>
        field="sku"
        label="Артикул"
        currentSorts={[]}
        onSortChange={() => {}}
        values={["ЮП-460", "ABC-100"]}
        selectedValues={selected}
        searchQuery={query}
        onSearchChange={(_field, next) => setQuery(next)}
        onFilterChange={(_field, next) => {
          emittedSelections.push(next);
          setSelected(next);
        }}
        onApplySearch={() => appliedQueries.push(query)}
        {...props}
      />
    );
  }

  render(<Harness />);
  fireEvent.click(screen.getByText("Артикул"));

  return { emittedSelections, appliedQueries };
}

/** Попапер открыт: ищем поле ввода тем же способом, что и элементы рядом. */
function searchInput(): HTMLInputElement {
  return screen.getByPlaceholderText("Поиск...") as HTMLInputElement;
}

describe("SortableFilterHeader", () => {
  it("renders closed trigger with label", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="sku"
        label="Артикул"
        currentSorts={[]}
        onSortChange={vi.fn()}
        values={["ЮП-460", "ABC-100"]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
      />,
    );

    expect(html).toContain("Артикул");
  });

  it("exposes sort state on sort button", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="sku"
        label="Артикул"
        currentSorts={[{ field: "sku", order: "asc" }]}
        onSortChange={vi.fn()}
        values={[]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
      />,
    );

    expect(html).toContain('data-sort-order="asc"');
    expect(html).toContain('aria-pressed="true"');
  });

  it("при sortable=false не рендерит кнопку сортировки, но оставляет фильтр", () => {
    const html = renderToStaticMarkup(
      <SortableFilterHeader
        field="route"
        label="Маршрут"
        currentSorts={[{ field: "route", order: "desc" }]}
        onSortChange={vi.fn()}
        values={["Резка"]}
        selectedValues={new Set()}
        onFilterChange={vi.fn()}
        sortable={false}
      />,
    );

    expect(html).toContain("Маршрут");
    expect(html).not.toContain("data-sort-order");
  });
});

describe("выбор значения в поповере", () => {
  it("у однозначной колонки второе значение заменяет первое, а повторный клик снимает выбор", () => {
    // Сервер принимает на колонку одно значение: второе в том же наборе ушло бы
    // в запрос параметром, которого там нет, и осталось бы в бейдже надолго.
    const { emittedSelections } = mountFilterPopover();

    fireEvent.click(screen.getByText("ЮП-460"));
    fireEvent.click(screen.getByText("ABC-100"));
    fireEvent.click(screen.getByText("ABC-100"));

    expect(emittedSelections).toEqual([
      new Set(["ЮП-460"]),
      new Set(["ABC-100"]),
      new Set(),
    ]);
  });

  it("у колонки с множественным выбором клики накапливают значения, а повторный клик убирает своё", () => {
    const { emittedSelections } = mountFilterPopover({ multiSelect: true });

    fireEvent.click(screen.getByText("ЮП-460"));
    fireEvent.click(screen.getByText("ABC-100"));
    fireEvent.click(screen.getByText("ЮП-460"));

    expect(emittedSelections).toEqual([
      new Set(["ЮП-460"]),
      new Set(["ЮП-460", "ABC-100"]),
      new Set(["ABC-100"]),
    ]);
  });

  it("«Выбрать все» рисуется только у колонки с множественным выбором", () => {
    mountFilterPopover();

    // Однозначной колонке «выбрать все» нечего предложить: сервер примет одно
    // значение, а оператор останется с бейджем без запроса.
    expect(screen.queryByText("Выбрать все")).toBeNull();
  });

  it("«Выбрать все» берёт все видимые значения", () => {
    const { emittedSelections } = mountFilterPopover({ multiSelect: true });

    fireEvent.click(screen.getByText("Выбрать все"));

    expect(emittedSelections).toEqual([new Set(["ЮП-460", "ABC-100"])]);
  });
});

describe("текст в поповере фильтра", () => {
  it("непустой текст убирает список значений и снимает ранее выбранное", () => {
    // Контр-случай к двум следующим: молчание колонки, чей текст сужает
    // только список, должно объясняться `searchFiltersTable={false}`, а не тем,
    // что правило мертво. Пока идёт текстовый поиск, значения в списке не
    // выбирают: оставить при этом старое выбранным — показать в шапке фильтр,
    // которого в запросе нет.
    const { emittedSelections } = mountFilterPopover({ searchFiltersTable: true });
    fireEvent.click(screen.getByText("ЮП-460"));

    fireEvent.change(searchInput(), { target: { value: "460" } });

    expect(screen.queryByText("ABC-100")).toBeNull();
    expect(screen.getByText(/Список значений скрыт/)).toBeTruthy();
    expect(emittedSelections).toEqual([new Set(["ЮП-460"]), new Set()]);
  });

  it("у колонки, чей текст сужает только список, значения остаются на экране и выбор не снимается", () => {
    // «Размер» выбирается кликом по габариту, и её поиск ищет по списку, а не
    // по выборке. Выбранный габарит — часть этого списка: снять его текстом
    // значит стереть у оператора выбор, которого он не менял.
    const { emittedSelections } = mountFilterPopover({ searchFiltersTable: false });
    fireEvent.click(screen.getByText("ЮП-460"));

    fireEvent.change(searchInput(), { target: { value: "460" } });

    // Список на экране и сужен текстом: несовпавшее значение ушло из него.
    expect(screen.getByText("ЮП-460")).toBeTruthy();
    expect(screen.queryByText("ABC-100")).toBeNull();
    expect(screen.queryByText(/Список значений скрыт/)).toBeNull();
    expect(emittedSelections).toEqual([new Set(["ЮП-460"])]);
  });

  it("у колонки, чей текст сужает только список, значение под текстом всё ещё выбирается", () => {
    // Список, который нарисован, но не выбирается, обманывает хуже скрытого:
    // оператор кликает по габариту и не получает ничего.
    const { emittedSelections } = mountFilterPopover({ searchFiltersTable: false });

    fireEvent.change(searchInput(), { target: { value: "460" } });
    fireEvent.click(screen.getByText("ЮП-460"));

    expect(emittedSelections).toEqual([new Set(["ЮП-460"])]);
  });

  it("пробельный текст не считается непустым: список остаётся, выбор не снимается", () => {
    const { emittedSelections } = mountFilterPopover();
    fireEvent.click(screen.getByText("ЮП-460"));

    fireEvent.change(searchInput(), { target: { value: "   " } });

    expect(screen.getByText("ABC-100")).toBeTruthy();
    expect(emittedSelections).toEqual([new Set(["ЮП-460"])]);
  });

  it("Enter применяет набранный текст и закрывает поповер", () => {
    const { appliedQueries } = mountFilterPopover();
    fireEvent.change(searchInput(), { target: { value: "460" } });

    // Любая другая клавиша — это ещё печать, и применять нечего.
    fireEvent.keyDown(searchInput(), { key: "a" });
    expect(appliedQueries).toEqual([]);

    fireEvent.keyDown(searchInput(), { key: "Enter" });

    expect(appliedQueries).toEqual(["460"]);
    expect(screen.queryByPlaceholderText("Поиск...")).toBeNull();
  });

  it("кнопка «Готово» применяет набранный текст и закрывает поповер", () => {
    const { appliedQueries } = mountFilterPopover();
    fireEvent.change(searchInput(), { target: { value: "ЮП" } });

    fireEvent.click(screen.getByText("Готово"));

    expect(appliedQueries).toEqual(["ЮП"]);
    expect(screen.queryByPlaceholderText("Поиск...")).toBeNull();
  });
});