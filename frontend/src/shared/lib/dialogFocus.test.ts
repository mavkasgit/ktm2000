import { beforeEach, describe, expect, it } from "vitest";

import {
  installDialogFocusTracker,
  resetDialogTrigger,
  takeDialogTrigger,
} from "./dialogFocus";

/** Слушатели ставятся один раз на модуль, состояние сбрасываем между проверками. */
function press(target: Element, type: "pointerdown" | "keydown" = "pointerdown") {
  target.dispatchEvent(new Event(type, { bubbles: true }));
}

describe("takeDialogTrigger", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    resetDialogTrigger();
    installDialogFocusTracker();
  });

  it("до нажатия источника нет", () => {
    expect(takeDialogTrigger()).toBeNull();
  });

  it("запоминает элемент, которым открыли окно", () => {
    const button = document.createElement("button");
    document.body.append(button);

    press(button);
    expect(takeDialogTrigger()).toBe(button);
  });

  it("запоминает и по нажатию с клавиатуры", () => {
    const button = document.createElement("button");
    document.body.append(button);

    press(button, "keydown");
    expect(takeDialogTrigger()).toBe(button);
  });

  it("источник забирается один раз: повторный вызов пуст", () => {
    const button = document.createElement("button");
    document.body.append(button);

    press(button);
    expect(takeDialogTrigger()).toBe(button);
    expect(takeDialogTrigger()).toBeNull();
  });

  it("закрытие по Escape не подменяет источник кнопкой внутри окна", () => {
    // Кнопка, открывшая окно.
    const opener = document.createElement("button");
    document.body.append(opener);
    press(opener);

    // Закрытие по Escape: событие приходит с элемента внутри окна, который к
    // моменту возврата уже отсоединён.
    const inside = document.createElement("button");
    document.body.append(inside);
    press(inside, "keydown");
    inside.remove();

    expect(takeDialogTrigger()).toBe(opener);
  });

  it("вложенное окно возвращает фокус на кнопку внутри родительского окна", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    press(opener);

    // Кнопка «Печать» внутри окна плана — она остаётся жива при закрытии превью.
    const print = document.createElement("button");
    document.body.append(print);
    press(print);

    expect(takeDialogTrigger()).toBe(print);
    // Затем закрывается окно плана — оно возвращает фокус на свою кнопку.
    expect(takeDialogTrigger()).toBe(opener);
  });

  it("все элементы отсоединены — возвращать некуда", () => {
    const first = document.createElement("button");
    const second = document.createElement("button");
    document.body.append(first, second);
    press(first);
    press(second);
    first.remove();
    second.remove();

    expect(takeDialogTrigger()).toBeNull();
  });

  it("повторное нажатие на тот же элемент не дублирует его в стеке", () => {
    const button = document.createElement("button");
    document.body.append(button);

    press(button);
    press(button);
    expect(takeDialogTrigger()).toBe(button);
    expect(takeDialogTrigger()).toBeNull();
  });
});
