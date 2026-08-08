import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import { calcHanger } from "./hangerCalc";

const HANGER = { area_limit_m2: 13, rod_length_mm: 1450, gap_mm: 20, rod_count: 2 };

describe("calcHanger (POST /hanger-calc)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("отправляет items и возвращает results в порядке items", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: {
        results: [
          { by_area: 72, by_size: 72, total: 72, limiter: "area", area_m2: 0.17976, is_calculable: true },
          { by_area: null, by_size: null, total: null, limiter: null, area_m2: null, is_calculable: false },
        ],
        hanger: HANGER,
      },
    });

    const items = [
      { perimeter_mm: 64.2, mount_width_mm: 19.35, length_mm: 2800 },
      { perimeter_mm: null, mount_width_mm: null, length_mm: null },
    ];
    const resp = await calcHanger(items);

    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toBe("/hanger-calc");
    expect(post.mock.calls[0][1]).toEqual({ items });
    expect(resp.results).toHaveLength(2);
    expect(resp.results[0].total).toBe(72);
    expect(resp.results[1].is_calculable).toBe(false);
    expect(resp.hanger).toEqual(HANGER);
  });

  it("пустой items — допустимо (запрос констант подвеса)", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { results: [], hanger: HANGER },
    });
    const resp = await calcHanger([]);
    expect(post.mock.calls[0][1]).toEqual({ items: [] });
    expect(resp.results).toEqual([]);
    expect(resp.hanger).toEqual(HANGER);
  });

  it("кастомные константы передаются в теле запроса", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { results: [], hanger: { ...HANGER, area_limit_m2: 10 } },
    });
    await calcHanger([], { area_limit_m2: 10 });
    expect(post.mock.calls[0][1]).toEqual({ items: [], hanger: { area_limit_m2: 10 } });
  });
});
