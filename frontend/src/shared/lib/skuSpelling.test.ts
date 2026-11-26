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

  it("срезает только пробел и NBSP, как серверный normalize_sku (#474)", () => {
    // Таб и перевод строки внутри артикула — данные, а не оформление:
    // Python `normalize_sku` снимает ровно ` ` и `\u00A0`, и фронт обязан
    // видеть те же два написания одним артикулом.
    expect(skuLoose("ALS\t1103")).toBe("als\t1103");
    expect(skuLoose("ALS\n1103")).toBe("als\n1103");
    expect(skuLoose("ALS\r\n1103")).toBe("als\r\n1103");
    // Края обрезает `.trim()`, поэтому хвостовой таб исчезает, как в Python.
    expect(skuLoose("ALS1103\t")).toBe("als1103");
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
