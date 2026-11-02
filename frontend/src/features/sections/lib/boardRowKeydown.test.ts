/**
 * Клавиатура выбора на доске участка (#283, ревью п. 5).
 *
 * Контракт, который защищает тест: Enter и пробел на строке (или шапке группы)
 * переключают выделение, а клавиша, нажатая внутри строки — в её поле или
 * кнопке, — строку не трогает: Enter на кнопке «Завершить» обязан открыть
 * диалог. Один обработчик на все три места доски, поэтому правило проверяется
 * здесь, а не трижды через разметку.
 */

import { describe, expect, it, vi } from "vitest";

import { toggleSelectionOnRowKey } from "./boardRowKeydown";

function keydown(key: string, options: { fromInnerControl?: boolean } = {}) {
  const row = document.createElement("div");
  const target = options.fromInnerControl ? document.createElement("input") : row;
  const preventDefault = vi.fn();
  const toggle = vi.fn();
  return {
    event: { key, target, currentTarget: row, preventDefault },
    preventDefault,
    toggle,
  };
}

describe("boardRowKeydown: Enter/Space — тумблер выделения строки", () => {
  it.each(["Enter", " "])("%s на самой строке переключает выделение", (key) => {
    const { event, preventDefault, toggle } = keydown(key);

    expect(toggleSelectionOnRowKey(event, toggle)).toBe(true);
    expect(toggle).toHaveBeenCalledTimes(1);
    // Пробел не прокручивает страницу, Enter не нажимает «первую» кнопку.
    expect(preventDefault).toHaveBeenCalledTimes(1);
  });

  it("клавиша из поля или кнопки внутри строки не переключает выделение", () => {
    const { event, preventDefault, toggle } = keydown("Enter", { fromInnerControl: true });

    expect(toggleSelectionOnRowKey(event, toggle)).toBe(false);
    expect(toggle).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it("остальные клавиши строка не перехватывает", () => {
    const { event, preventDefault, toggle } = keydown("Tab");

    expect(toggleSelectionOnRowKey(event, toggle)).toBe(false);
    expect(toggle).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
