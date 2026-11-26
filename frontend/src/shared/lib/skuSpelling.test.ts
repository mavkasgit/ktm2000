import { describe, expect, it } from "vitest";

import { skuLoose } from "./skuSpelling";

describe("skuLoose: дефис между буквой и цифрой — оформление (#474)", () => {
  it("снимает дефис между буквой и цифрой", () => {
    expect(skuLoose("ALS-1103")).toBe("als1103");
    expect(skuLoose("ALS1103")).toBe("als1103");
    expect(skuLoose("ЮП–081")).toBe("юп081");
  });

  it("срезает пробелы и приводит регистр", () => {
    expect(skuLoose("  als 1103 ")).toBe("als1103");
    expect(skuLoose("ALS\u00A01103")).toBe("als1103");
  });

  it("дефис между цифрами — часть номера", () => {
    expect(skuLoose("12-34")).toBe("12-34");
    expect(skuLoose("ALS-11-03")).toBe("als11-03");
  });

  it("пустое значение безопасно", () => {
    expect(skuLoose("")).toBe("");
    expect(skuLoose("   ")).toBe("");
  });
});
