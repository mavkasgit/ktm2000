/**
 * URL запроса доски участка: сортировка уходит строкой `sort`.
 *
 * Это единственное место, где параметры превращаются в query string, поэтому
 * контракт `?sort=field:order,...` проверяется именно здесь: строка собирается
 * вручную через URLSearchParams, и потерянный `sort` не поймал бы ни один
 * тест уровнем выше.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue({ data: { tasks: [], groups: [], totals: {} } }) },
  makeRequestConfig: undefined,
}));

import { apiClient } from "./client";
import { getSectionBoard } from "./shopfloor";

function requestedUrl(): string {
  return vi.mocked(apiClient.get).mock.calls[0][0] as string;
}

describe("getSectionBoard: сортировка в URL", () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockClear();
  });

  it("мультисортировка уезжает одной строкой sort, по приоритетам", async () => {
    await getSectionBoard(7, { sort: "product_sku:asc,status:desc,dimensions:asc" });
    expect(requestedUrl()).toContain("sort=product_sku%3Aasc%2Cstatus%3Adesc%2Cdimensions%3Aasc");
  });

  it("без сортировки параметр sort не отправляется — дефолт сервера", async () => {
    await getSectionBoard(7, { limit: 50, offset: 0 });
    const url = requestedUrl();
    expect(url).not.toContain("sort");
  });

  it("сортировка уезжает только в sort, а не в устаревшие sort_by/sort_order", async () => {
    await getSectionBoard(7, { sort: "sequence:asc" });
    const url = requestedUrl();
    expect(url).toContain("sort=");
    expect(url).not.toContain("sort_by");
    expect(url).not.toContain("sort_order");
  });
});
