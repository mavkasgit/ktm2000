/**
 * Причина «количества» для передачи (#193, ревью #341 п. 7).
 *
 * Строка, шапка группы и футер массового ввода решают одно и то же: пока
 * введённое число не больше нуля, передавать нечего. Раньше это правило было
 * написано трижды, и расхождение в нём означало бы, что одна из трёх сторон
 * показывает оператору другую причину. Остальные причины (строка уже
 * отправляется, нет исполнителя) остаются на своих местах — здесь только
 * «число → причина».
 */

import { describe, expect, it } from "vitest";

import { zeroQuantityReason } from "./transferReasons";

describe("zeroQuantityReason", () => {
  it("введённого количества нет — передача не нажимается по причине zero_quantity", () => {
    // `parseFloat("")` даёт NaN, поэтому пустое поле обязано попадать в ту же
    // причину, что и ноль: иначе кнопка стала бы нажиматься без числа.
    expect(zeroQuantityReason(0)).toBe("zero_quantity");
    expect(zeroQuantityReason(Number.NaN)).toBe("zero_quantity");
    expect(zeroQuantityReason(-3)).toBe("zero_quantity");
  });

  it("положительное количество — причины нет", () => {
    expect(zeroQuantityReason(0.5)).toBeNull();
    expect(zeroQuantityReason(10)).toBeNull();
  });
});
