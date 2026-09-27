/**
 * URL запросов складских и передачных эндпоинтов: сортировка уходит строкой
 * `sort`, а превью импорта остатков — полем `sort` в теле FormData.
 *
 * Строка собирается вручную через URLSearchParams и FormData, поэтому
 * потерянный `sort` не поймал бы ни один тест уровнем выше: компонент видит
 * уже готовые параметры.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: { balances: [], transactions: [], items: [], transfers: [] } }),
    post: vi.fn().mockResolvedValue({ data: { items: [], summary: {} } }),
  },
}));

import { apiClient } from "./client";
import { getStockBalances, getStockTransactions, previewRemaindersExcel } from "./stock";
import { listReadyToTransfer, listTransferHistory } from "./transfers";

/** URL последнего GET: в одном тесте бывают два разных запроса. */
function requestedUrl(): string {
  const calls = vi.mocked(apiClient.get).mock.calls;
  return calls[calls.length - 1][0] as string;
}

function lastFormData(): FormData {
  const calls = vi.mocked(apiClient.post).mock.calls;
  return calls[calls.length - 1][1] as FormData;
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockClear();
  vi.mocked(apiClient.post).mockClear();
});

describe("остатки и история транзакций: сортировка в URL", () => {
  it("мультисортировка уезжает одной строкой sort, по приоритетам", async () => {
    await getStockBalances({ sort: "location:desc,quantity:asc" });
    expect(requestedUrl()).toContain("sort=location%3Adesc%2Cquantity%3Aasc");

    await getStockTransactions({ sort: "quantity:desc,comment:asc" });
    expect(requestedUrl()).toContain("sort=quantity%3Adesc%2Ccomment%3Aasc");
  });

  it("сортировка уезжает только в sort, а не в устаревшие sort_by/sort_order", async () => {
    await getStockBalances({ sort: "sku:asc" });
    const balanceUrl = requestedUrl();
    expect(balanceUrl).toContain("sort=");
    expect(balanceUrl).not.toContain("sort_by");
    expect(balanceUrl).not.toContain("sort_order");

    await getStockTransactions({ sort: "created_at:desc" });
    const txUrl = requestedUrl();
    expect(txUrl).toContain("sort=");
    expect(txUrl).not.toContain("sort_by");
    expect(txUrl).not.toContain("sort_order");
  });
});

describe("передачи: сортировка в URL", () => {
  it("мультисортировка уезжает одной строкой sort, по приоритетам", async () => {
    await listReadyToTransfer({ sort: "plan_position_id:desc,transferable_qty:desc" });
    expect(requestedUrl()).toContain("sort=plan_position_id%3Adesc%2Ctransferable_qty%3Adesc");

    await listTransferHistory({ sort: "status:asc,quantity:desc" });
    expect(requestedUrl()).toContain("sort=status%3Aasc%2Cquantity%3Adesc");
  });

  it("сортировка уезжает только в sort, а не в устаревшие sort_by/sort_order", async () => {
    await listReadyToTransfer({ sort: "sequence:asc" });
    const readyUrl = requestedUrl();
    expect(readyUrl).toContain("sort=");
    expect(readyUrl).not.toContain("sort_by");
    expect(readyUrl).not.toContain("sort_order");

    await listTransferHistory({ sort: "created_at:desc" });
    const historyUrl = requestedUrl();
    expect(historyUrl).toContain("sort=");
    expect(historyUrl).not.toContain("sort_by");
    expect(historyUrl).not.toContain("sort_order");
  });
});

describe("превью импорта остатков: сортировка в теле запроса", () => {
  it("строка sort уходит в FormData полем sort, а не в query", async () => {
    await previewRemaindersExcel(
      { kind: "clipboard", clipboardText: "SKU\tQty" },
      { sort: "sku:asc,row:desc" },
    );

    const url = vi.mocked(apiClient.post).mock.calls[0][0] as string;
    const form = lastFormData();
    expect(form.get("sort")).toBe("sku:asc,row:desc");
    expect(form.get("sort_by")).toBeNull();
    expect(form.get("sort_order")).toBeNull();
    expect(url).not.toContain("sort");
  });

  it("без сортировки уходит дефолт превью — строки файла сверху", async () => {
    await previewRemaindersExcel({ kind: "clipboard", clipboardText: "SKU\tQty" });
    expect(lastFormData().get("sort")).toBe("row:asc");
  });
});
