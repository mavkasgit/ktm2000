import { describe, expect, it } from "vitest";

import {
  OPTIMAL_COLUMN_WIDTHS_ENV,
  OPTIMAL_COLUMN_WIDTHS_QUERY,
  isOptimalColumnWidthsEnabled,
} from "./optimalColumnWidthsFlag";

describe("флаг рантайм-ширин", () => {
  it("без флага выключен", () => {
    expect(isOptimalColumnWidthsEnabled({}, "")).toBe(false);
  });

  it("включается переменной окружения", () => {
    expect(isOptimalColumnWidthsEnabled({ [OPTIMAL_COLUMN_WIDTHS_ENV]: "1" }, "")).toBe(true);
    expect(isOptimalColumnWidthsEnabled({ [OPTIMAL_COLUMN_WIDTHS_ENV]: "0" }, "")).toBe(false);
  });

  it("включается query-параметром, чужие значения не считаются", () => {
    expect(
      isOptimalColumnWidthsEnabled({}, `?${OPTIMAL_COLUMN_WIDTHS_QUERY}=optimal`),
    ).toBe(true);
    expect(isOptimalColumnWidthsEnabled({}, `?${OPTIMAL_COLUMN_WIDTHS_QUERY}=1`)).toBe(false);
    expect(isOptimalColumnWidthsEnabled({}, "?other=optimal")).toBe(false);
  });
});
