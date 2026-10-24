import { beforeEach, describe, expect, it, vi } from "vitest"

const { post } = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock("@/shared/api/client", () => ({ apiClient: { post } }))

import { takeToWork } from "./productionPlans"

const allocation = [{ balance_id: 10, quantity: 5 }]

describe("takeToWork — источник только для одной позиции", () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: { ok: true } })
  })

  it("массовый запрос с источником отклоняется до HTTP", async () => {
    await expect(takeToWork([1, 2], allocation)).rejects.toThrow(
      "Источник выдачи выбирается только для одной позиции",
    )
    expect(post).not.toHaveBeenCalled()
  })

  it("одиночный запуск с источником уходит на сервер", async () => {
    await takeToWork([1], allocation)

    expect(post).toHaveBeenCalledWith(
      "/production-planning/rows/take-to-work",
      expect.objectContaining({ position_ids: [1], remainder_allocation: allocation }),
    )
  })

  it("массовый запуск без источника уходит на сервер", async () => {
    await takeToWork([1, 2])

    expect(post).toHaveBeenCalledWith(
      "/production-planning/rows/take-to-work",
      expect.objectContaining({ position_ids: [1, 2] }),
    )
  })

  it("пустой список источника массовый запуск не блокирует", async () => {
    await takeToWork([1, 2], [])

    expect(post).toHaveBeenCalledTimes(1)
  })
})
