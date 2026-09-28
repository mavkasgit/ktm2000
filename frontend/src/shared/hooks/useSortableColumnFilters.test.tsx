// @vitest-environment happy-dom

/**
 * Пауза перед запросом живёт здесь, а не на каждом экране (ADR-0044): текст,
 * набранный в поповере, — это параметр запроса, и уехать он должен последним
 * вводом, а не отдельным запросом на каждый символ.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { SEARCH_DEBOUNCE_MS } from "@/shared/lib/useDebouncedValue";

import { useSortableColumnFilters } from "./useSortableColumnFilters";

type Field = "name" | "status";

/** Хук дженерик по имени колонки — на уровне поля теста он уже конкретный. */
type BoundHook = ReturnType<typeof useSortableColumnFilters<Field>>;

interface HarnessResult {
  bindColumn: BoundHook["bindColumn"];
  buildFilterPredicate: BoundHook["buildFilterPredicate"];
  onColumnSearchChange: BoundHook["onColumnSearchChange"];
  onColumnFilterChange: BoundHook["onColumnFilterChange"];
  columnSearchQueries: Partial<Record<Field, string>>;
  debouncedColumnSearchQueries: Partial<Record<Field, string>>;
}

// Без этого флага React 18 считает act(...) ненастоящим и предупреждает на
// каждом тике вместо того, чтобы гарантировать, что состояние обновилось.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function mountHarness() {
  const container = document.createElement("div");
  const root: Root = createRoot(container);
  const state: { current: HarnessResult | null } = { current: null };
  /**
   * Что попадало в отложенное значение, по порядку коммитов. Повторный рендер
   * с тем же значением коммитом не считается: иначе список разросся бы от
   * перерисовок и перестал бы отвечать на вопрос «сколько раз ушёл запрос».
   */
  const commits: Partial<Record<Field, string>>[] = [];
  let lastCommit = "";

  function Harness() {
    const hook = useSortableColumnFilters<Field>();
    state.current = {
      bindColumn: hook.bindColumn,
      buildFilterPredicate: hook.buildFilterPredicate,
      onColumnSearchChange: hook.onColumnSearchChange,
      onColumnFilterChange: hook.onColumnFilterChange,
      columnSearchQueries: hook.columnSearchQueries,
      debouncedColumnSearchQueries: hook.debouncedColumnSearchQueries,
    };
    const snapshot = JSON.stringify(hook.debouncedColumnSearchQueries);
    if (snapshot !== lastCommit) {
      lastCommit = snapshot;
      commits.push(hook.debouncedColumnSearchQueries);
    }
    return null;
  }

  act(() => {
    root.render(<Harness />);
  });

  const getResult = () => {
    if (!state.current) {
      throw new Error("Hook result was not captured");
    }
    return state.current;
  };

  return {
    getResult,
    commits,
    unmount: () => {
      act(() => {
        root.unmount();
      });
    },
  };
}

/** Один тик ввода: оператор нажал клавишу — компонент отрисовался. */
function type(harness: ReturnType<typeof mountHarness>, field: Field, query: string) {
  act(() => {
    harness.getResult().onColumnSearchChange(field, query);
  });
}

function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("useSortableColumnFilters", () => {
  it("bindColumn reflects search and filter state for the field", () => {
    const harness = mountHarness();

    act(() => {
      const { onColumnSearchChange, onColumnFilterChange } = harness.getResult();
      onColumnSearchChange("name", "abc");
      onColumnFilterChange("name", new Set(["x"]));
    });

    const bound = harness.getResult().bindColumn("name");

    expect(bound.searchQuery).toBe("abc");
    expect(bound.selectedValues).toEqual(new Set(["x"]));

    harness.unmount();
  });

  it("buildFilterPredicate can omit fields from predicate", () => {
    const harness = mountHarness();

    act(() => {
      const { onColumnSearchChange, onColumnFilterChange } = harness.getResult();
      onColumnSearchChange("name", "abc");
      onColumnFilterChange("status", new Set(["open"]));
    });

    type Row = { name: string; status: string };
    const predicate = harness.getResult().buildFilterPredicate<Row>(
      (row, field) => (field === "name" ? row.name : row.status),
      ["status"],
    );

    expect(predicate).not.toBeNull();
    expect(predicate!({ name: "abc", status: "closed" })).toBe(true);
    expect(predicate!({ name: "xyz", status: "closed" })).toBe(false);

    harness.unmount();
  });

  it("поле отдаёт сырое значение сразу — первый ввод не должен пропасть", () => {
    const harness = mountHarness();

    type(harness, "name", "абв");

    expect(harness.getResult().bindColumn("name").searchQuery).toBe("абв");
    // А в запрос уходит не то, что на экране: отложенное значение ещё пустое.
    expect(harness.getResult().debouncedColumnSearchQueries).toEqual({});

    harness.unmount();
  });

  it("до истечения паузы отложенное значение прежнее, после — последний ввод", () => {
    const harness = mountHarness();

    type(harness, "name", "абв");
    wait(SEARCH_DEBOUNCE_MS - 1);

    expect(harness.getResult().debouncedColumnSearchQueries).toEqual({});

    wait(1);

    expect(harness.getResult().debouncedColumnSearchQueries).toEqual({ name: "абв" });

    harness.unmount();
  });

  it("серия быстрых вводов уезжает в запрос один раз и последним текстом", () => {
    const harness = mountHarness();

    // Каждая буква — отдельный тик, как в живом вводе: если бы паузы не было,
    // в запрос уехали бы все три промежуточных значения.
    type(harness, "name", "а");
    wait(50);
    type(harness, "name", "аб");
    wait(50);
    type(harness, "name", "абв");
    wait(SEARCH_DEBOUNCE_MS);

    expect(harness.commits).toEqual([{}, { name: "абв" }]);

    harness.unmount();
  });

  it("onApplySearch применяет набранное, минуя остаток паузы", () => {
    const harness = mountHarness();

    type(harness, "name", "абв");
    // «Готово» нажали, не дожидаясь паузы: оператор сказал «искать сейчас».
    wait(SEARCH_DEBOUNCE_MS - 100);
    expect(harness.getResult().debouncedColumnSearchQueries).toEqual({});

    act(() => {
      harness.getResult().bindColumn("name").onApplySearch();
    });

    expect(harness.getResult().debouncedColumnSearchQueries).toEqual({ name: "абв" });

    harness.unmount();
  });
});
