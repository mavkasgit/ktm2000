import { describe, expect, it } from "vitest";

import { parseNumericInput } from "./parseNumericInput";

describe("parseNumericInput: пустая строка", () => {
  it("пустая строка — null", () => {
    expect(parseNumericInput("")).toBeNull();
  });

  it("пробелы/табуляция — null", () => {
    expect(parseNumericInput("   ")).toBeNull();
    expect(parseNumericInput("\t ")).toBeNull();
  });
});

describe("parseNumericInput: обычные числа", () => {
  it("целое", () => {
    expect(parseNumericInput("12")).toBe(12);
  });

  it("десятичное с точкой", () => {
    expect(parseNumericInput("12.5")).toBe(12.5);
  });

  it("пробелы вокруг числа обрезаются", () => {
    expect(parseNumericInput("  12.5  ")).toBe(12.5);
  });

  it("отрицательные и ноль — числа", () => {
    expect(parseNumericInput("0")).toBe(0);
    expect(parseNumericInput("-5.5")).toBe(-5.5);
  });

  it("экспоненциальная запись", () => {
    expect(parseNumericInput("1e3")).toBe(1000);
  });
});

describe("parseNumericInput: запятая", () => {
  it("без allowComma запятая — мусор (null)", () => {
    expect(parseNumericInput("12,5")).toBeNull();
  });

  it("с allowComma запятая — десятичный разделитель", () => {
    expect(parseNumericInput("12,5", { allowComma: true })).toBe(12.5);
  });

  it("с allowComma замена первой запятой", () => {
    expect(parseNumericInput("1,234", { allowComma: true })).toBe(1.234);
  });

  it("с allowComma пустая строка — null", () => {
    expect(parseNumericInput("", { allowComma: true })).toBeNull();
  });
});

describe("parseNumericInput: мусор", () => {
  it("текст — null", () => {
    expect(parseNumericInput("abc")).toBeNull();
  });

  it("число с хвостом — null (строгое чтение)", () => {
    expect(parseNumericInput("12abc")).toBeNull();
  });

  it("текст с числом внутри — null", () => {
    expect(parseNumericInput("abc12")).toBeNull();
  });

  it("NaN/Infinity — null", () => {
    expect(parseNumericInput("NaN")).toBeNull();
    expect(parseNumericInput("Infinity")).toBeNull();
    expect(parseNumericInput("-Infinity")).toBeNull();
  });

  it("мусор при allowComma — null", () => {
    expect(parseNumericInput("abc", { allowComma: true })).toBeNull();
    expect(parseNumericInput("1,2abc", { allowComma: true })).toBeNull();
  });
});
