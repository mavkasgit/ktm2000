import { describe, expect, it } from "vitest";
import { compositionLabel } from "./compositionLabel";

describe("compositionLabel", () => {
  it("пустой состав → null", () => {
    expect(compositionLabel(null)).toBeNull();
    expect(compositionLabel(undefined)).toBeNull();
    expect(compositionLabel([])).toBeNull();
  });

  it("один компонент", () => {
    expect(compositionLabel([{ sku: "ЮП-100", quantity: 2 }])).toBe("ЮП-100×2");
  });

  it("два компонента через «;»", () => {
    expect(
      compositionLabel([
        { sku: "ЮП-100", quantity: 2 },
        { sku: "ЮП-200", quantity: 3 },
      ]),
    ).toBe("ЮП-100×2; ЮП-200×3");
  });

  it("дробное количество без хвостовых нулей", () => {
    expect(compositionLabel([{ sku: "ЮП-100", quantity: 2.5 }])).toBe("ЮП-100×2.5");
    expect(compositionLabel([{ sku: "ЮП-100", quantity: 2.500001 }])).toBe("ЮП-100×2.5");
    expect(compositionLabel([{ sku: "ЮП-100", quantity: 1.3333333 }])).toBe("ЮП-100×1.333");
  });
});
