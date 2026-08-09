import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CatalogExcelApplyResult } from "@/shared/api/products";
import { ImportResultStep } from "./ImportResultStep";

const makeResult = (overrides: Partial<CatalogExcelApplyResult> = {}): CatalogExcelApplyResult => ({
  imported: 2,
  updated: 1,
  skipped: 3,
  errors: [],
  ...overrides,
});

describe("ImportResultStep", () => {
  it("renders the import statistics on success", () => {
    render(<ImportResultStep result={makeResult()} />);

    expect(screen.getByText("Создано: 2")).toBeTruthy();
    expect(screen.getByText("Обновлено: 1")).toBeTruthy();
    expect(screen.getByText("Пропущено: 3")).toBeTruthy();
    expect(screen.queryByText("Ошибки строк (строки пропущены):")).toBeNull();
  });

  it("renders the row errors report on partial failure", () => {
    const result = makeResult({
      imported: 1,
      updated: 0,
      skipped: 0,
      errors: [
        { row: 7, sku: "SKU-BAD", message: "нет длины" },
        { row: 9, sku: "SKU-BAD2", message: "дубликат артикула" },
      ],
    });
    render(<ImportResultStep result={result} />);

    expect(screen.getByText("Создано: 1")).toBeTruthy();
    expect(screen.getByText("Ошибки строк (строки пропущены):")).toBeTruthy();
    expect(screen.getByText("Строка 7 — SKU-BAD: нет длины")).toBeTruthy();
    expect(screen.getByText("Строка 9 — SKU-BAD2: дубликат артикула")).toBeTruthy();
  });

  it("renders zero statistics and all row errors on full rejection", () => {
    const result = makeResult({
      imported: 0,
      updated: 0,
      skipped: 0,
      errors: [{ row: 1, sku: "SKU-ALL", message: "нет длины" }],
    });
    render(<ImportResultStep result={result} />);

    expect(screen.getByText("Создано: 0")).toBeTruthy();
    expect(screen.getByText("Обновлено: 0")).toBeTruthy();
    expect(screen.getByText("Пропущено: 0")).toBeTruthy();
    expect(screen.getByText("Строка 1 — SKU-ALL: нет длины")).toBeTruthy();
  });
});
