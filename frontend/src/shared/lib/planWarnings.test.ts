/**
 * Предупреждения позиции читаются только с `validation_warnings` (#334).
 *
 * Legacy-фолбэка на `warnings` из PlanChangeItem больше нет: исторические
 * строки закрыл бэкфилл миграции 082, а API прежнее поле не отдаёт.
 */
import { describe, expect, it } from "vitest"

import { positionWarnings } from "./planWarnings"

describe("positionWarnings", () => {
  it("возвращает персистированные предупреждения позиции", () => {
    expect(positionWarnings({ validation_warnings: ["product_name_missing"] })).toEqual([
      "product_name_missing",
    ])
  })

  it("пустой список остаётся пустым", () => {
    expect(positionWarnings({ validation_warnings: [] })).toEqual([])
  })

  it("отсутствующее поле не роняет строку", () => {
    expect(positionWarnings({})).toEqual([])
    expect(positionWarnings({ validation_warnings: null })).toEqual([])
  })

  it("legacy-поле warnings не читается", () => {
    const legacy = {
      validation_warnings: [],
      warnings: ["hanger_quantity_not_set:2.7"],
    }

    expect(positionWarnings(legacy)).toEqual([])
  })
})
