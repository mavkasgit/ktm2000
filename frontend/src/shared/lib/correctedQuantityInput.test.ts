/**
 * Правило ввода количества при правке записанного факта (#200).
 *
 * Это НЕ то же правило, что в `quantityInput.ts`, и наоборот: там ноль
 * допустим, а здесь отклоняется; там дробь запрещена, а здесь законна.
 * Смешивать их в одном модуле нельзя — импортнётся не то.
 */
import { describe, expect, it } from "vitest";

import { normalizeCorrectedQuantityInput } from "./correctedQuantityInput";

describe("normalizeCorrectedQuantityInput", () => {
  it("пустое поле — отсутствие ввода, а не ноль", () => {
    expect(normalizeCorrectedQuantityInput("")).toEqual({ value: "", number: null, issue: null });
    expect(normalizeCorrectedQuantityInput("   ")).toEqual({ value: "", number: null, issue: null });
  });

  it("целое и дробное разбираются в число", () => {
    expect(normalizeCorrectedQuantityInput("5")).toEqual({ value: "5", number: 5, issue: null });
    expect(normalizeCorrectedQuantityInput("12")).toEqual({ value: "12", number: 12, issue: null });
  });

  it("дробь законна: домен передач Numeric(14,3)", () => {
    expect(normalizeCorrectedQuantityInput("0.5").number).toBe(0.5);
    expect(normalizeCorrectedQuantityInput("0,5").number).toBe(0.5);
    expect(normalizeCorrectedQuantityInput("2.75").number).toBe(2.75);
  });

  it("запятая и точка равны по значению — оператор не обязан знать, что ждёт Decimal", () => {
    // `Decimal("5,5")` на бэкенде бросает исключение: отправлять запятую
    // нельзя, но и ругать оператора за неё нельзя.
    expect(normalizeCorrectedQuantityInput("5,5").number).toBe(normalizeCorrectedQuantityInput("5.5").number);
  });

  it("поле сохраняет разделитель, который набрал оператор", () => {
    expect(normalizeCorrectedQuantityInput("5,5").value).toBe("5,5");
    expect(normalizeCorrectedQuantityInput("5.5").value).toBe("5.5");
  });

  // --- отклонения ---
  it("ноль отклоняется: сервер требует строго больше нуля", () => {
    const result = normalizeCorrectedQuantityInput("0");
    expect(result.number).toBeNull();
    expect(result.issue?.kind).toBe("zero");
  });

  it("ноль с дробной частью (`0.0`) — тоже ноль", () => {
    expect(normalizeCorrectedQuantityInput("0.0").issue?.kind).toBe("zero");
    expect(normalizeCorrectedQuantityInput("0,00").issue?.kind).toBe("zero");
  });

  it("минус отклоняется", () => {
    const result = normalizeCorrectedQuantityInput("-1");
    expect(result.issue?.kind).toBe("negative");
    expect(result.number).toBeNull();
  });

  it("буквы и мусор отклоняются, а не молча выкидываются", () => {
    const result = normalizeCorrectedQuantityInput("абв");
    expect(result.number).toBeNull();
    expect(result.issue?.kind).toBe("non-numeric");
    expect(result.issue?.text).toBeTruthy();
  });

  it("вторая десятичная запятая отклоняется", () => {
    expect(normalizeCorrectedQuantityInput("1,2,3").issue?.kind).toBe("decimal");
  });

  it("более трёх знаков после запятой отклоняются: иначе Numeric(14,3) округлит молча", () => {
    expect(normalizeCorrectedQuantityInput("1.2345").issue?.kind).toBe("precision");
    expect(normalizeCorrectedQuantityInput("1.234").number).toBe(1.234);
  });

  it("причина называется по первому недопустимому символу", () => {
    expect(normalizeCorrectedQuantityInput("а,5").issue?.kind).toBe("non-numeric");
    expect(normalizeCorrectedQuantityInput("-,5").issue?.kind).toBe("negative");
  });

  it("число равно null, пока ввод недопустим — отправлять нечего", () => {
    expect(normalizeCorrectedQuantityInput("5,,").number).toBeNull();
    expect(normalizeCorrectedQuantityInput("1.2345").number).toBeNull();
  });
});
