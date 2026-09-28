import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositionSkuCell } from "./PositionSkuCell";

/**
 * Индикатор остатка в ячейке «Артикул» (#207): три числа с тремя именами.
 * Проверяем, что оператор видит ровно те числа и только их — «доступно»,
 * при расхождении «/ свободно», при нехватке «−дефицит», и молчит, когда
 * данных о наличии нет.
 */
describe("PositionSkuCell — индикатор остатка", () => {
  it("prints one number when free stock equals the available quantity", () => {
    render(
      <PositionSkuCell sku="КП-460" freeStockQuantity={1500} availableQuantity={1500} />,
    );

    expect(screen.queryByTestId("position-sku-free-stock")).toBeNull();
    expect(screen.getByTestId("position-sku-available").textContent).toBe("· 1500");
  });

  it("prefixes the free stock when a foreign position holds part of it", () => {
    render(
      <PositionSkuCell sku="КП-460" freeStockQuantity={1500} availableQuantity={1100} />,
    );

    expect(screen.getByTestId("position-sku-free-stock").textContent).toBe("/ 1500");
    expect(screen.getByTestId("position-sku-available").textContent).toBe("· 1100");
  });

  it("shows a real zero instead of hiding the indicator", () => {
    render(<PositionSkuCell sku="КП-460" freeStockQuantity={0} availableQuantity={0} />);

    expect(screen.getByTestId("position-sku-available").textContent).toBe("· 0");
  });

  it("marks the shortage only when the deficit is greater than zero", () => {
    const { rerender } = render(
      <PositionSkuCell
        sku="КП-460"
        freeStockQuantity={1500}
        availableQuantity={1500}
        deficitQuantity={12}
      />,
    );

    const deficit = screen.getByTestId("position-sku-deficit");
    expect(deficit.textContent).toBe("· −12");
    expect(deficit.className).toContain("text-amber-600");

    rerender(
      <PositionSkuCell
        sku="КП-460"
        freeStockQuantity={1500}
        availableQuantity={1500}
        deficitQuantity={0}
      />,
    );
    expect(screen.queryByTestId("position-sku-deficit")).toBeNull();
  });

  it("prints no indicator at all when there is no availability data", () => {
    render(
      <PositionSkuCell
        sku="КП-460"
        freeStockQuantity={null}
        availableQuantity={null}
        deficitQuantity={null}
      />,
    );

    expect(screen.queryByTestId("position-sku-available")).toBeNull();
    expect(screen.queryByTestId("position-sku-free-stock")).toBeNull();
    expect(screen.queryByTestId("position-sku-deficit")).toBeNull();
    expect(screen.getByText("КП-460")).toBeTruthy();
  });

  it("names both stock numbers and the shortage in the cell tooltip", () => {
    render(
      <PositionSkuCell
        sku="КП-460"
        freeStockQuantity={1500}
        availableQuantity={1500}
        deficitQuantity={12}
      />,
    );

    const container = screen.getByTestId("position-sku-available").parentElement;
    expect(container?.getAttribute("title")).toBe(
      "Свободно на складах: 1500 · Доступно для позиции: 1500 · Дефицит позиции: 12",
    );
  });

  it("says plainly that there is no availability data in the tooltip", () => {
    render(<PositionSkuCell sku="КП-460" availableQuantity={null} />);

    const container = screen.getByText("КП-460").parentElement;
    expect(container?.getAttribute("title")).toBe("Нет данных о наличии КП-460");
  });
});
