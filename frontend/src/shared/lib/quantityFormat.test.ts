import { describe, expect, it } from "vitest";

import { QTY_EMPTY, fmtQty, fmtQtyPrecise, toQtyInteger } from "./quantityFormat";

describe("fmtQty — целые штуки", () => {
  it("дробь округляется, целое не трогается", () => {
    expect(fmtQty(8)).toBe("8");
    expect(fmtQty(2.4)).toBe("2");
    expect(fmtQty(2.5)).toBe("3");
    expect(fmtQty(0)).toBe("0");
  });

  it("строка из БД разбирается, хвостовые нули Decimal не печатаются", () => {
    expect(fmtQty("200.0")).toBe("200");
    expect(fmtQty("12.500")).toBe("13");
    expect(fmtQty(" 7 ")).toBe("7");
  });

  it("разделитель тысяч не появляется: e2e читает количество как (\\d+)\\s*шт", () => {
    expect(fmtQty(1000)).toBe("1000");
    expect(fmtQty("1234567")).toBe("1234567");
  });

  it("не-число — это отсутствие значения, а не ноль", () => {
    for (const value of [null, undefined, "", "   ", "abc", "2,5", NaN, Infinity]) {
      expect(fmtQty(value)).toBe(QTY_EMPTY);
      expect(fmtQty(value)).not.toBe("0");
    }
  });
});

describe("fmtQtyPrecise — дробь живая", () => {
  it("дробь не теряется, хвостовые нули срезаются", () => {
    expect(fmtQtyPrecise(2.5)).toBe("2,5");
    expect(fmtQtyPrecise(2)).toBe("2");
    expect(fmtQtyPrecise("2.500")).toBe("2,5");
    expect(fmtQtyPrecise(2.0004)).toBe("2");
  });

  it("точность ограничена тремя знаками, как Numeric(14, 3)", () => {
    expect(fmtQtyPrecise(2.5004)).toBe("2,5");
    expect(fmtQtyPrecise(1.2346)).toBe("1,235");
    expect(fmtQtyPrecise(0.001)).toBe("0,001");
  });

  it("разделитель дробной части — запятая, как у размера (ADR-0035)", () => {
    expect(fmtQtyPrecise(2.5)).not.toContain(".");
    expect(fmtQtyPrecise(2.5)).toBe(fmtQtyPrecise("2.50"));
  });

  it("разделитель тысяч не появляется", () => {
    expect(fmtQtyPrecise(1500.25)).toBe("1500,25");
  });

  it("не-число — это отсутствие значения, а не ноль", () => {
    for (const value of [null, undefined, "", "abc", NaN]) {
      expect(fmtQtyPrecise(value)).toBe(QTY_EMPTY);
      expect(fmtQtyPrecise(value)).not.toBe("0");
    }
  });
});

describe("toQtyInteger — обратная сторона fmtQty", () => {
  it("разбирает значение БД в целые штуки числом", () => {
    expect(toQtyInteger("200.0")).toBe(200);
    expect(toQtyInteger(2.4)).toBe(2);
    expect(toQtyInteger("12.500")).toBe(13);
    expect(toQtyInteger(-3)).toBe(-3);
  });

  it("печать и разбор не расходятся на целых штуках", () => {
    for (const value of ["0", "1", "8", "999", "200.0"]) {
      expect(String(toQtyInteger(value))).toBe(fmtQty(value));
    }
  });

  it("не-разбираемое значение даёт ноль: вызывающий считает «сколько добавить»", () => {
    for (const value of ["", "  ", "abc", "шт"]) {
      expect(toQtyInteger(value)).toBe(0);
    }
  });

  it("запятая не мешает разбору: parseFloat берёт целую часть, как и прежде", () => {
    // В отличие от fmtQty, «2,5» здесь — это 2, а не «—»: значение нужно числом
    // для арифметики по задачам, и молча подставить ноль значило бы занизить итог.
    expect(toQtyInteger("2,5")).toBe(2);
  });
});
