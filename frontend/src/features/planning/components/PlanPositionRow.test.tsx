import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import type { PlanPositionOut } from "@/shared/api/productionPlans"
import { PositionRow } from "./PlanPositionRow"

function position(overrides: Partial<PlanPositionOut>): PlanPositionOut {
  return {
    id: 5633,
    production_plan_id: 1,
    source_sku: "ЮП-460",
    source_name: "Профиль ЮП-460",
    quantity: "100",
    status: "draft",
    validation_status: "valid",
    errors: [],
    warnings: [],
    source_row_number: 5,
    product_id: 10,
    route_id: null,
    route_profile_id: null,
    route_name: null,
    route_source: null,
    route_origin: null,
    route_match_quality: null,
    route_match_reason: null,
    route_assigned_at: null,
    route_manual_confirmed_at: null,
    route_error: null,
    raw_excel_row: null,
    ...overrides,
  }
}

/** Текст ячейки «Кол-во»: подпись итога лежит внутри неё. */
function qtyCellText(pos: PlanPositionOut): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <PositionRow pos={pos} onApprove={vi.fn()} onDelete={vi.fn()} />
    </QueryClientProvider>,
  )
  return screen.getByTitle("Итог по длинам (после пилы)").parentElement?.textContent ?? ""
}

describe("PositionRow — ячейка «Кол-во»", () => {
  it("сырьё → итог, подвесы считаются от итога", () => {
    const text = qtyCellText(
      position({
        quantity: "144",
        input_quantity: "100",
        quantity_per_hanger: 72,
        payload: { original_quantity: "100" },
      }),
    )
    expect(text).toBe("100-144 (2П)")
    expect(text).not.toContain("ГП")
  })

  it("без сырья, но с округлением до подвесов — план → итог", () => {
    const text = qtyCellText(
      position({
        quantity: "144",
        quantity_per_hanger: 72,
        payload: { original_quantity: "100" },
      }),
    )
    expect(text).toBe("100-144 (2П)")
  })

  it("без изменений количества показывает одно число с подвесами", () => {
    expect(qtyCellText(position({ quantity: "144", quantity_per_hanger: 72 }))).toBe("144 (2П)")
  })

  it("подвесы не бывают дробными — количество округляется вверх", () => {
    expect(qtyCellText(position({ quantity: "100", quantity_per_hanger: 72 }))).toBe("100 (2П)")
  })

  it("без нормы на подвес подвесы не показываются", () => {
    expect(qtyCellText(position({ quantity: "144" }))).toBe("144")
  })

  it("равные сырьё и итог одним числом", () => {
    expect(qtyCellText(position({ quantity: "50", input_quantity: "50", quantity_per_hanger: 50 }))).toBe("50 (1П)")
  })
})

/** Ячейка «Размер» отрендеренной строки. */
function sizeCell(pos: PlanPositionOut): HTMLElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={client}>
      <PositionRow pos={pos} onApprove={vi.fn()} onDelete={vi.fn()} />
    </QueryClientProvider>,
  )
  return container.querySelectorAll('[id^="plan-position-"] > div')[4] as HTMLElement
}

describe("PositionRow — ячейка «Размер»", () => {
  it("раскрой: вход со стрелкой слева, каждый распил с новой строки", () => {
    const cell = sizeCell(
      position({
        quantity: "250",
        cut_layout: { input: "2,75", outputs: ["0,9×50", "1,35×100", "1,8×50", "2,7×50"] },
      }),
    )

    expect(cell.textContent).toContain("2,75 →")
    const lines = Array.from(cell.querySelectorAll('[class*="flex-col"] > span')).map((el) => el.textContent)
    expect(lines).toEqual(["0,9×50", "1,35×100", "1,8×50", "2,7×50"])
  })

  it("одиночный габарит без распилов", () => {
    const cell = sizeCell(
      position({ quantity: "144", cut_layout: { input: "2,75 м", outputs: [] } }),
    )

    expect(cell.textContent).toBe("2,75 м")
  })

  it("без раскроя показывает габарит задания", () => {
    const cell = sizeCell(position({ quantity: "144", dimensions_label: "2,75 м" }))

    expect(cell.textContent).toBe("2,75 м")
  })
})
