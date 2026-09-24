import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QuantityRangeCell } from "./QuantityRangeCell";

describe("QuantityRangeCell — подвесы для трансформации", () => {
  it("отображает подвесы по количеству до резки между входом и итогом", () => {
    const { container } = render(
      <QuantityRangeCell
        quantity={250}
        inputQuantity={150}
        quantityPerHanger={50}
      />,
    );

    expect(container.textContent).toMatch(/^150\s*\(3П\)\s*-\s*250$/);
  });

  it("оставляет суффикс П серым и обычным с диапазоном и без него", () => {
    const withRange = render(
      <QuantityRangeCell
        quantity={250}
        inputQuantity={150}
        quantityPerHanger={50}
      />,
    );
    const withoutRange = render(
      <QuantityRangeCell quantity={50} quantityPerHanger={50} />,
    );

    const withRangeSuffix = [...withRange.container.querySelectorAll("span")].find(
      (element) => element.textContent === " (3П)",
    );
    const withoutRangeSuffix = [...withoutRange.container.querySelectorAll("span")].find(
      (element) => element.textContent === " (1П)",
    );

    expect(withRangeSuffix?.getAttribute("class")).toBe(
      "font-normal text-muted-foreground",
    );
    expect(withoutRangeSuffix?.getAttribute("class")).toBe(
      "font-normal text-muted-foreground",
    );
  });
});
