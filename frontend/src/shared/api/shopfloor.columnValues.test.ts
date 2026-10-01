/**
 * URL запроса справочника значений колонки доски (#211).
 *
 * Параметры превращаются в query string ровно в одном месте, поэтому контракт
 * проверяется здесь: `column` обязателен, фильтры доски уезжают как есть,
 * отсутствующие не отправляются вовсе.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { column: "product_sku", values: [], limit: 200, truncated: false },
    }),
  },
  makeRequestConfig: undefined,
}));

import { apiClient } from "./client";
import { getSectionBoardColumnValues } from "./shopfloor";

describe("getSectionBoardColumnValues: параметры в URL", () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockClear();
  });

  it("колонка и фильтры доски уезжают в query string", async () => {
    await getSectionBoardColumnValues(7, {
      column: "product_sku",
      date_from: "2026-06-01T00:00:00",
      date_to: "2026-06-01T23:59:59",
      status: "ready",
      search: "ЮП",
      product_sku: "ЮП-2630",
      dimensions: '{"length_mm":2700}',
      limit: 200,
    });

    const url = vi.mocked(apiClient.get).mock.calls[0][0] as string;
    expect(url).toContain("/shopfloor/sections/7/board/column-values?");
    expect(url).toContain("column=product_sku");
    expect(url).toContain("date_from=2026-06-01T00%3A00%3A00");
    expect(url).toContain("status=ready");
    expect(url).toContain("search=%D0%AE%D0%9F");
    expect(url).toContain("product_sku=%D0%AE%D0%9F-2630");
    expect(url).toContain("dimensions=%7B%22length_mm%22%3A2700%7D");
    expect(url).toContain("limit=200");
  });

  it("незаданные фильтры в запрос не попадают — сервер понимает их как «фильтра нет»", async () => {
    await getSectionBoardColumnValues(7, { column: "product_sku" });

    const url = vi.mocked(apiClient.get).mock.calls[0][0] as string;
    expect(url).toContain("column=product_sku");
    expect(url).not.toContain("date_from");
    expect(url).not.toContain("status");
    expect(url).not.toContain("search");
    expect(url).not.toContain("product_sku=");
    expect(url).not.toContain("dimensions");
    expect(url).not.toContain("limit");
  });
});
