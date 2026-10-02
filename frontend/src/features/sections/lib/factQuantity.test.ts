import { describe, expect, it } from "vitest";

import {
  FACT_BELOW_RECORDED_REASON,
  factPortion,
  isFactInputApplicable,
  resolveFactQuantity,
} from "./factQuantity";

describe("resolveFactQuantity: «+100» — добавить", () => {
  it("порция — введённое число, итог — записанное плюс порция", () => {
    expect(resolveFactQuantity("+100", 400)).toEqual({
      kind: "write",
      mode: "add",
      quantity: 100,
      target: 500,
    });
  });

  it("ноль в режиме добавления — законная порция (ноль допустим)", () => {
    expect(resolveFactQuantity("+0", 400)).toEqual({
      kind: "write",
      mode: "add",
      quantity: 0,
      target: 400,
    });
  });
});

describe("resolveFactQuantity: «500» — факт станет 500", () => {
  it("порция — разница с записанным", () => {
    expect(resolveFactQuantity("500", 400)).toEqual({
      kind: "write",
      mode: "set",
      quantity: 100,
      target: 500,
    });
  });

  it("равно записанному — писать нечего, порция ноль", () => {
    expect(resolveFactQuantity("400", 400)).toEqual({
      kind: "write",
      mode: "set",
      quantity: 0,
      target: 400,
    });
  });

  it("меньше записанного — ввод не применяется, причина из словаря", () => {
    expect(resolveFactQuantity("300", 400)).toEqual({
      kind: "invalid",
      reason: FACT_BELOW_RECORDED_REASON,
    });
  });

  it("записанного нет — любое число становится порцией целиком", () => {
    expect(resolveFactQuantity("300", 0)).toEqual({
      kind: "write",
      mode: "set",
      quantity: 300,
      target: 300,
    });
  });
});

describe("resolveFactQuantity: отсутствие ввода", () => {
  it("пустое поле и один знак режима — ввода нет", () => {
    expect(resolveFactQuantity("", 400)).toEqual({ kind: "none" });
    expect(resolveFactQuantity("+", 400)).toEqual({ kind: "none" });
  });
});

describe("factPortion и isFactInputApplicable", () => {
  it("порция: добавка, разница, ноль для отклонённого и пустого", () => {
    expect(factPortion("+100", 400)).toBe(100);
    expect(factPortion("500", 400)).toBe(100);
    expect(factPortion("300", 400)).toBe(0);
    expect(factPortion("", 400)).toBe(0);
  });

  it("отклонённый ввод отличается от пустого: пустое поле — не ошибка", () => {
    expect(isFactInputApplicable("300", 400)).toBe(false);
    expect(isFactInputApplicable("", 400)).toBe(true);
    expect(isFactInputApplicable("+100", 400)).toBe(true);
  });
});
