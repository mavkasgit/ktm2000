/**
 * Ручная корректировка остатка: путь запроса идёт БЕЗ префикса `/api`.
 *
 * `apiClient` уже несёт baseURL с `/api` (`DEFAULT_API_BASE_URL` в
 * `authHostConfig.ts`, `.env.dev` — `http://…:8012/api`), поэтому путь с
 * ведущим `/api` собирался в `/api/api/stock/adjustment` и получал 404
 * «Not Found»: диалог «Ручная операция со складом» не мог записать ни приход,
 * ни расход. Все остальные вызовы `stock.ts` — `/stock/…`, этот был один.
 *
 * Регрессия найдена при приёмке ADR-0055 (#244): без записи ручной проводки
 * не проверить списание строго из выбранной группы операций.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({
      data: { id: 1, reason: "manual_out", quantity: "100", created_at: null },
    }),
  },
}));

import { apiClient } from "./client";
import { postStockAdjustment } from "./stock";

describe("postStockAdjustment", () => {
  it("постит на /stock/adjustment, не дублируя префикс /api", async () => {
    await postStockAdjustment({
      product_id: 104,
      location_id: 1,
      quantity: 100,
      reason: "manual_out",
      quality_state: "GOOD",
      dimensions: { length_mm: 2700 },
      completed_operations: ["PRESS_WINDOW"],
    });

    const [url, body] = vi.mocked(apiClient.post).mock.calls[0];
    expect(url).toBe("/stock/adjustment");
    expect(url.startsWith("/api/")).toBe(false);
    expect(body).toEqual({
      product_id: 104,
      location_id: 1,
      quantity: 100,
      reason: "manual_out",
      quality_state: "good",
      dimensions: { length_mm: 2700 },
      completed_operations: ["PRESS_WINDOW"],
    });
  });
});
