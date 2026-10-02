import { describe, expect, it } from "vitest";

import { normalizeQuantityInput, parseQuantityInput, QUANTITY_INPUT_ISSUE_TEXT } from "./quantityInput";

describe("normalizeQuantityInput: обычный ввод", () => {
  it("цифры проходят без причины", () => {
    expect(normalizeQuantityInput("12")).toEqual({ value: "12", mode: "set", issue: null });
    expect(normalizeQuantityInput("0")).toEqual({ value: "0", mode: "set", issue: null });
  });
  it("недопустимый символ отделён от допустимых, чтобы вызывающий мог его не применить", () => {
    // Вызывающий не применяет `value`, если `issue` не null: символ не должен
    // попасть в поле (ADR-0032), иначе `1,5` тихо превратится в `15`.
    const r = normalizeQuantityInput("1,5");
    expect(r.issue).not.toBeNull();
    expect(r.value).toBe("15");
  });

  it("допустимый ввод проходит без причины — поле применяет значение и снимает причину", () => {
    expect(normalizeQuantityInput("15").issue).toBeNull();
    expect(normalizeQuantityInput("").issue).toBeNull();
  });

  it("ноль допустим: он не превышение, а ноль", () => {
    expect(normalizeQuantityInput("0").issue).toBeNull();
  });

  it("пустой ввод — отсутствие ввода, а не ноль", () => {
    expect(normalizeQuantityInput("")).toEqual({ value: "", mode: "set", issue: null });
  });

  it("ведущие нули сохраняются как набраны", () => {
    expect(normalizeQuantityInput("007").value).toBe("007");
  });
});

describe("normalizeQuantityInput: десятичный разделитель", () => {
  it("запятая отклоняется с видимой причиной", () => {
    const r = normalizeQuantityInput("1,5");
    expect(r.value).toBe("15");
    expect(r.issue).toEqual({ kind: "decimal", text: QUANTITY_INPUT_ISSUE_TEXT.decimal });
  });

  it("точка отклоняется той же причиной", () => {
    expect(normalizeQuantityInput("1.5").issue?.kind).toBe("decimal");
    expect(normalizeQuantityInput("1.5").value).toBe("15");
  });

  it("разделитель тысяч не читается как дробь: 1,234 — это 1234 с предупреждением", () => {
    const r = normalizeQuantityInput("1,234");
    expect(r.value).toBe("1234");
    expect(r.issue?.kind).toBe("decimal");
  });
});

describe("normalizeQuantityInput: минус", () => {
  it("минус отклоняется, а не молча теряется", () => {
    const r = normalizeQuantityInput("-5");
    expect(r.value).toBe("5");
    expect(r.issue).toEqual({ kind: "negative", text: QUANTITY_INPUT_ISSUE_TEXT.negative });
  });

  it("отрицательное не превращается в положительное молча", () => {
    expect(normalizeQuantityInput("-120").issue?.kind).toBe("negative");
  });
});

describe("normalizeQuantityInput: прочий мусор", () => {
  it("текст отклоняется с указанием на цифры", () => {
    const r = normalizeQuantityInput("12abc");
    expect(r.value).toBe("12");
    expect(r.issue).toEqual({ kind: "non-digit", text: QUANTITY_INPUT_ISSUE_TEXT["non-digit"] });
  });

  it("пробелы отклоняются, а не склеивают цифры", () => {
    expect(normalizeQuantityInput("1 2").value).toBe("12");
    expect(normalizeQuantityInput("1 2").issue?.kind).toBe("non-digit");
  });

  it("причина называется по первому недопустимому символу и не меняется на ходу набора", () => {
    expect(normalizeQuantityInput("1,5-").issue?.kind).toBe("decimal");
    expect(normalizeQuantityInput("a,5").issue?.kind).toBe("non-digit");
  });
});

describe("normalizeQuantityInput: границы", () => {
  it("только недопустимые символы дают пустое значение с причиной", () => {
    const r = normalizeQuantityInput(",.-");
    expect(r.value).toBe("");
    expect(r.issue?.kind).toBe("decimal");
  });

  it("нормализация идемпотентна: результат можно пропустить через себя же", () => {
    const once = normalizeQuantityInput("1,5");
    expect(normalizeQuantityInput(once.value)).toEqual({ value: "15", mode: "set", issue: null });
  });

  it("каждая причина — непустой текст", () => {
    for (const text of Object.values(QUANTITY_INPUT_ISSUE_TEXT)) {
      expect(text.length).toBeGreaterThan(0);
    }
  });
});

describe("normalizeQuantityInput: ведущий «+» — режим, а не знак числа", () => {
  it("«+100» — добавление, знак остаётся в значении", () => {
    expect(normalizeQuantityInput("+100")).toEqual({ value: "+100", mode: "add", issue: null });
  });

  it("без знака — установка факта", () => {
    expect(normalizeQuantityInput("500").mode).toBe("set");
  });

  it("«+» не первым символом — тот же недопустимый символ, что буква", () => {
    const r = normalizeQuantityInput("1+0");
    expect(r.value).toBe("10");
    expect(r.mode).toBe("set");
    expect(r.issue?.kind).toBe("non-digit");
  });

  it("второй «+» отбрасывается с причиной, а не читается как знак", () => {
    const r = normalizeQuantityInput("++100");
    expect(r.value).toBe("+100");
    expect(r.mode).toBe("add");
    expect(r.issue?.kind).toBe("non-digit");
  });

  it("один знак без цифр — режим набран, числа нет", () => {
    expect(normalizeQuantityInput("+")).toEqual({ value: "+", mode: "add", issue: null });
  });

  it("причина называет «+» в начале, а не «только цифры»", () => {
    expect(QUANTITY_INPUT_ISSUE_TEXT["non-digit"]).toContain("первым символом");
  });
});

describe("parseQuantityInput: разбор сохранённого ввода", () => {
  it("читает режим и число", () => {
    expect(parseQuantityInput("+100")).toEqual({ mode: "add", quantity: 100 });
    expect(parseQuantityInput("500")).toEqual({ mode: "set", quantity: 500 });
  });

  it("пустое поле и один знак — числа нет", () => {
    expect(parseQuantityInput("")).toEqual({ mode: "set", quantity: null });
    expect(parseQuantityInput("+")).toEqual({ mode: "add", quantity: null });
  });

  it("ведущие нули — то же число", () => {
    expect(parseQuantityInput("007")).toEqual({ mode: "set", quantity: 7 });
  });
});
