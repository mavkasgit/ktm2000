import { beforeEach, describe, expect, it, vi } from "vitest";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { post } }));

import { takeToWork, type IssueSelection } from "./productionPlans";

describe("takeToWork — автоподбор источника выдачи (#282)", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ data: { results: [], issue_summary: null } });
  });

  it("групповой запуск идёт подбором без галочек: `auto: true`, снятых id нет", async () => {
    await takeToWork([1, 2], undefined, undefined, {
      auto: true,
      idempotency_key: "bulk-1",
    } satisfies IssueSelection);

    const payload = post.mock.calls[0]?.[1] as {
      position_ids: number[];
      issue?: { auto?: boolean; excluded_balance_ids?: number[] };
    };
    expect(payload.position_ids).toEqual([1, 2]);
    expect(payload.issue?.auto).toBe(true);
    // Галочки принадлежат конкретной позиции: в групповом payload их нет.
    expect(payload.issue?.excluded_balance_ids ?? []).toEqual([]);
  });

  it("ручной выбор одной позиции отправляет снятые галочки и стратегию", async () => {
    await takeToWork([1], undefined, undefined, {
      excluded_balance_ids: [7, 9],
      shortage_strategy: "fail",
      auto: false,
      idempotency_key: "manual-1",
    } satisfies IssueSelection);

    expect(post).toHaveBeenCalledWith(
      "/production-planning/rows/take-to-work",
      expect.objectContaining({
        position_ids: [1],
        issue: expect.objectContaining({
          excluded_balance_ids: [7, 9],
          shortage_strategy: "fail",
          auto: false,
        }),
      }),
    );
  });

  it("снятые галочки на нескольких позициях отклоняются до HTTP", async () => {
    await expect(
      takeToWork([1, 2], undefined, undefined, {
        excluded_balance_ids: [7],
        shortage_strategy: "partial",
        auto: false,
      } satisfies IssueSelection),
    ).rejects.toThrow(/для одной позиции/);
    expect(post).not.toHaveBeenCalled();
  });
});
