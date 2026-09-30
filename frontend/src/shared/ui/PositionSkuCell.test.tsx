import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositionSkuCell } from "./PositionSkuCell";

/**
 * Индикатор остатка в ячейке «Артикул» (#207): два числа, отвечающие на
 * вопрос «хватит ли сырья этой позиции» — сколько доступно и на сколько не
 * хватает. Проверяем, что видны ровно эти два числа без разделителей, что
 * нулевой остаток печатается, а молчат они только когда данных нет.
 */
describe("PositionSkuCell — индикатор остатка", () => {
  it("prints only the available quantity when nothing is missing", () => {
    render(<PositionSkuCell sku="КП-460" availableQuantity={1500} />);

    expect(screen.getByTestId("position-sku-available").textContent).toBe("1500");
    expect(screen.queryByTestId("position-sku-deficit")).toBeNull();
  });

  it("does not print the free stock of the warehouse", () => {
    render(<PositionSkuCell sku="КП-460" availableQuantity={1100} />);

    // Свойство склада, а не позиции: в строке рядом с количеством позиции
    // оно читалось как «втрое больше» и мешало увидеть дефицит.
    expect(screen.queryByTestId("position-sku-free-stock")).toBeNull();
    expect(screen.getByTestId("position-sku-available").textContent).toBe("1100");
  });

  it("shows a real zero instead of hiding the indicator", () => {
    render(<PositionSkuCell sku="КП-460" availableQuantity={0} />);

    expect(screen.getByTestId("position-sku-available").textContent).toBe("0");
  });

  it("marks the shortage only when the deficit is greater than zero", () => {
    const { rerender } = render(
      <PositionSkuCell sku="КП-460" availableQuantity={492} deficitQuantity={12} />,
    );

    const deficit = screen.getByTestId("position-sku-deficit");
    expect(deficit.textContent).toBe("−12");
    expect(deficit.className).toContain("text-amber-600");
    expect(screen.getByTestId("position-sku-available").textContent).toBe("492");

    rerender(<PositionSkuCell sku="КП-460" availableQuantity={492} deficitQuantity={0} />);
    expect(screen.queryByTestId("position-sku-deficit")).toBeNull();
  });

  it("prints no indicator at all when there is no availability data", () => {
    render(
      <PositionSkuCell
        sku="КП-460"
        availableQuantity={null}
        deficitQuantity={null}
      />,
    );

    expect(screen.queryByTestId("position-sku-available")).toBeNull();
    expect(screen.queryByTestId("position-sku-deficit")).toBeNull();
    expect(screen.getByText("КП-460")).toBeTruthy();
  });

  it("names both numbers so the operator reads them without guessing", () => {
    render(
      <PositionSkuCell sku="КП-460" availableQuantity={492} deficitQuantity={12} />,
    );

    expect(screen.getByTestId("position-sku-available").getAttribute("title")).toBe(
      "Доступно для позиции КП-460: 492 шт.",
    );
    expect(screen.getByTestId("position-sku-deficit").getAttribute("title")).toBe(
      "Не хватает 12 шт. до планового количества",
    );
  });
});
