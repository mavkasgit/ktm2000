import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ACTION_REASON_TEXT, type ActionReasonCode } from "@/shared/lib/actionReasons";

import { ActionWithReason } from "./ActionWithReason";

const ACTION = <button type="button">Завершить</button>;

/**
 * Причина недоступности видна без наведения мыши (#193).
 *
 * Проверяем две стороны контракта: причина напечатана текстом рядом с кнопкой
 * (для каждого кода из словаря — свой текст, тот же, что в `title`), а
 * доступное действие остаётся чистой кнопкой без обёртки и без подсказок.
 * Формулировки не пиню: текст берётся из `ACTION_REASON_TEXT`.
 */
describe("ActionWithReason — причина видна на экране", () => {
  it.each(Object.keys(ACTION_REASON_TEXT) as ActionReasonCode[])(
    "код %s печатается текстом рядом с кнопкой и дублируется в title",
    (code) => {
      const expected = ACTION_REASON_TEXT[code];
      render(<ActionWithReason reason={code}>{ACTION}</ActionWithReason>);

      const button = screen.getByRole("button");
      const reason = screen.getByText(expected);

      // Причина — отдельный элемент рядом с кнопкой, а не подсказка на ней:
      // title на самой кнопке оператор без мыши не увидит.
      expect(reason).not.toBe(button);
      expect(reason.getAttribute("title")).toBe(expected);
      // Кнопка на месте и прежняя: причина добавляется, а не заменяет действие.
      expect(button.textContent).toBe("Завершить");
      // Одна строка целиком: и кнопка, и текст в одном общем контейнере,
      // иначе строка таблицы растёт и ломает виртуализацию.
      expect(reason.parentElement).toBe(button.parentElement);
    },
  );

  it("доступное действие остаётся кнопкой: ни текста причины, ни лишней обёртки", () => {
    const { container } = render(<ActionWithReason reason={null}>{ACTION}</ActionWithReason>);

    expect(container.textContent).toBe("Завершить");
    expect(container.querySelector("[title]")).toBeNull();
    expect(container.querySelector("div")).toBeNull();
    expect(container.firstElementChild?.tagName).toBe("BUTTON");
  });
});
