import { describe, expect, it } from "vitest"

import type { PlanPositionOut } from "@/shared/api/productionPlans"
import { planRowLinks } from "./planRowLinks"

function row(overrides: Partial<PlanPositionOut>): PlanPositionOut {
  return {
    id: 1,
    production_plan_id: 23,
    source_sku: "ЮП-0000",
    quantity: "100",
    status: "draft",
    validation_status: "valid",
    errors: [],
    warnings: [],
    ...overrides,
  } as PlanPositionOut
}

/** Позиция, которую импорт связал с парой `pair_id`. */
function pairedRow(
  id: number,
  pairId: number,
  pairName: string,
  overrides: Partial<PlanPositionOut> = {},
): PlanPositionOut {
  return row({
    id,
    source_sku: pairName.split("+")[0],
    payload: {
      product_pair: {
        resolved: true,
        pair_id: pairId,
        pair_name: pairName,
        quantity_per_hanger: 30,
      },
    },
    ...overrides,
  })
}

describe("planRowLinks", () => {
  it("связывает две позиции одной пары и нумерует их по порядку", () => {
    const links = planRowLinks([
      pairedRow(1446, 1, "ЮП-2604+ЮП-2616"),
      pairedRow(1447, 1, "ЮП-2604+ЮП-2616"),
    ])

    expect(links.get(1446)).toEqual({
      title: "Пара ЮП-2604+ЮП-2616 · 30 шт на подвес",
      ordinal: 1,
      total: 2,
    })
    expect(links.get(1447)).toMatchObject({ ordinal: 2, total: 2 })
  })

  it("одиночная позиция пары не связывается: связывать не с чем", () => {
    // Видна только одна сторона пары — вторая отфильтрована или на другой
    // странице. Подпись «1/1» в колонке «Id» ввела бы в заблуждение.
    expect(planRowLinks([pairedRow(1446, 1, "ЮП-2604+ЮП-2616")]).size).toBe(0)
  })

  it("пара, помеченная импортом как неразрешённая, парой не считается", () => {
    // `no_paired_row` — одиночная строка артикула, у которого партнёра нет.
    const solo = row({
      id: 1343,
      payload: {
        product_pair: {
          resolved: false,
          reason: "no_paired_row",
          pair_id: 1,
          pair_name: "ЮП-2604+ЮП-2616",
          quantity_per_hanger: null,
        },
      },
    })

    expect(planRowLinks([solo, solo]).size).toBe(0)
  })

  it("одинаковая пара из разных планов не склеивается в одну", () => {
    const links = planRowLinks([
      pairedRow(1, 1, "ЮП-2604+ЮП-2616", { production_plan_id: 23 }),
      pairedRow(2, 1, "ЮП-2604+ЮП-2616", { production_plan_id: 24 }),
    ])

    expect(links.size).toBe(0)
  })

  it("нумерация идёт по порядку строк на экране, а не по id", () => {
    // Сортировка по количеству переставила строки: видная первой — 1447,
    // и подпись «1/2» обязана достаться ей, иначе она врёт оператору.
    const links = planRowLinks([
      pairedRow(1447, 1, "ЮП-2604+ЮП-2616"),
      pairedRow(1446, 1, "ЮП-2604+ЮП-2616"),
    ])

    expect(links.get(1447)?.ordinal).toBe(1)
    expect(links.get(1446)?.ordinal).toBe(2)
  })

  it("распил одной заготовки связываться не должен: это одна позиция", () => {
    // Одна заготовка, распиленная на две длины, — одна позиция с двумя
    // выходами (ADR-0003), а не две позиции. Если бы импорт когда-нибудь отдал
    // их раздельно, связать их всё равно было бы враньём: на пиле это две
    // самостоятельные операции, и оператор сложил бы загрузку вдвое.
    const links = planRowLinks([
      row({
        id: 1,
        source_sku: "ЮП-2627",
        input_quantity: "100",
        input_dimensions: { length_mm: 2700 },
        outputs: [{ quantity: "100", dimensions: { length_mm: 900 } }],
      }),
      row({
        id: 2,
        source_sku: "ЮП-2627",
        input_quantity: "100",
        input_dimensions: { length_mm: 2700 },
        outputs: [{ quantity: "100", dimensions: { length_mm: 1800 } }],
      }),
    ])

    expect(links.size).toBe(0)
  })

  it("позиция без пары остаётся без метки", () => {
    const links = planRowLinks([row({ id: 1438 }), pairedRow(1446, 1, "A+B"), pairedRow(1447, 1, "A+B")])

    expect(links.has(1438)).toBe(false)
    expect(links.size).toBe(2)
  })

  it("пустой список не роняет разметку", () => {
    expect(planRowLinks([]).size).toBe(0)
  })
})
