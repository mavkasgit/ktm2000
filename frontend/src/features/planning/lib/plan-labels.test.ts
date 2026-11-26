import { describe, expect, it } from "vitest";

import { errorLabels } from "@/shared/lib/generated-labels";

import { translatePlanImportError } from "./plan-labels";

const LABEL = errorLabels["normal_length_not_found"];

describe("translatePlanImportError", () => {
  it("сырьевая длина из файла — совет исправить файл, а не карточку", () => {
    expect(translatePlanImportError("normal_length_not_found:raw:2,75:2,7", errorLabels)).toBe(
      `${LABEL} — 2,75 это сырьё для 2,7; укажите 2,7 в «Длина, м»`,
    );
  });

  it("неизвестная длина сырья — совет добавить в справочник сырья", () => {
    expect(translatePlanImportError("normal_length_not_found:missing:raw:2,8", errorLabels)).toBe(
      `${LABEL} — 2,8 нет в справочнике сырья; добавьте, если это нормальная длина`,
    );
  });

  it("неизвестная длина продукта — совет добавить в справочник продуктов", () => {
    expect(
      translatePlanImportError("normal_length_not_found:missing:product:2,8", errorLabels),
    ).toBe(`${LABEL} — 2,8 нет в справочнике продуктов; добавьте, если это нормальная длина`);
  });

  it("код без параметров остаётся нейтральным", () => {
    expect(translatePlanImportError("normal_length_not_found", errorLabels)).toBe(LABEL);
  });

  it("чужие коды с параметрами не меняются", () => {
    expect(translatePlanImportError("sku_matched_by_part:1875", errorLabels)).toBe(
      "sku_matched_by_part: 1875",
    );
  });
});
