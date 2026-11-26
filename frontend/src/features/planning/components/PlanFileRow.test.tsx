import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { ImportFullItem } from "@/shared/api/imports";

import { ItemDetail } from "./PlanFileRow";

function item(overrides: Partial<ImportFullItem>): ImportFullItem {
  return {
    id: 1,
    source_row_number: 6,
    source_ref: "rows:6-7",
    source_sku: "ЮП-460",
    change_action: "create_position",
    status: "warning",
    warnings: [],
    errors: [],
    after_data: {
      source_sku: "ЮП-460",
      source_name: "Профиль ЮП-460",
      quantity: "144",
    },
    plan_position_id: null,
    ...overrides,
  };
}

/** Текст детализации без разметки и SSR-разделителей выражений. */
function detailText(overrides: Partial<ImportFullItem>): string {
  const html = renderToStaticMarkup(<ItemDetail item={item(overrides)} />);
  return html.replace(/<!-- -->/g, "").replace(/<[^>]*>/g, " ");
}

describe("PlanFileRow — детализация строки", () => {
  it("переводит параметризованное предупреждение по базе кода", () => {
    const text = detailText({ warnings: ["hanger_quantity_not_set:2,7"] });

    expect(text).toContain("Не задано количество на подвес");
    expect(text).toContain(": 2,7");
  });

  it("переводит предупреждение баланса раскроя вместе с параметрами", () => {
    // #473: подпись ищем по базе кода, а не по полной строке с параметрами.
    const text = detailText({
      warnings: ["plan_group_balance_mismatch:вход 360 м, выход 630 м (разница 270 м)"],
    });

    expect(text).toContain(
      "Баланс раскроя не сходится: вход 360 м, выход 630 м (разница 270 м)",
    );
  });
});
