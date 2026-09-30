import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import type { PlanPositionOut } from "@/shared/api/productionPlans"
import type { ProductionRoute } from "@/shared/api/routes"
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

/**
 * Строка позиции внутри таблицы.
 *
 * `PositionRow` возвращает `<tr>`, поэтому рендерить его в bare-`div` нельзя:
 * React ругается на `validateDOMNesting`, и тест проверял бы разметку, которой
 * на странице нет. Обёртка повторяет настоящую — `<table><tbody>`.
 */
function renderPositionRow(
  pos: PlanPositionOut,
  props?: { routes?: ProductionRoute[]; onAssignRoute?: (positionId: number, routeId: number | null) => void },
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <table>
        <tbody>
          <PositionRow pos={pos} onApprove={vi.fn()} onDelete={vi.fn()} {...props} />
        </tbody>
      </table>
    </QueryClientProvider>,
  )
}

/** Текст ячейки «Кол-во»: подпись итога лежит внутри неё. */
function qtyCellText(pos: PlanPositionOut): string {
  renderPositionRow(pos)
  return screen.getByTitle("Итог после округления на подвесы").parentElement?.textContent ?? ""
}

describe("PositionRow — ячейка «Кол-во»", () => {
  it("подвесы считаются от сырья, а не от итога", () => {
    const text = qtyCellText(
      position({
        quantity: "144",
        input_quantity: "100",
        quantity_per_hanger: 30,
        payload: { original_quantity: "100" },
      }),
    )
    // От сырья: ceil(100/30) = 4. От итога было бы ceil(144/30) = 5 — то есть
    // тест различает базу, а не подтверждает одно и то же число дважды.
    expect(text).toBe("100 (4П)-144")
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
    expect(text).toBe("100 (2П)-144")
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
  const { container } = renderPositionRow(pos)
  return container.querySelectorAll('[id^="plan-position-"] > td')[4] as HTMLElement
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

describe("PositionRow — состояние валидации", () => {
  it("перекрытая форс-аппрувом валидация видна подписью канона, а не сырым кодом", () => {
    const { container } = renderPositionRow(
      position({
        status: "approved",
        validation_status: "overridden",
        errors: ["route_contains_excluded_step: DRILLING"],
      }),
    )

    expect(container.textContent).toContain("Перекрыта")
    expect(container.textContent).not.toContain("overridden")
  })
})

/** Строка плана целиком: ячейки — прямые <td> внутри строки таблицы. */
function renderRow(pos: PlanPositionOut, props?: { routes: ProductionRoute[]; onAssignRoute: (positionId: number, routeId: number | null) => void }): HTMLElement {
  const { container } = renderPositionRow(pos, props)
  return container.querySelector('[id^="plan-position-"]') as HTMLElement
}

function cells(row: HTMLElement): HTMLElement[] {
  return Array.from(row.children) as HTMLElement[]
}

const ROUTE_CELL_INDEX = 6

function routeCell(row: HTMLElement): HTMLElement {
  return cells(row)[ROUTE_CELL_INDEX]
}

describe("PositionRow — ячейка «Маршрут» при невыбранном маршруте", () => {
  const conflictPosition = position({
    status: "invalid",
    validation_status: "invalid",
    route_id: null,
    route_name: "ЮП-460 резка",
    route_source: "dynamic_build",
    errors: ["route_signature_conflict"],
    // Номер подвеса нужен проверке места признака: он живёт в ячейке «Кол-во»,
    // а признак обязан стоять левее неё (в самом начале строки).
    input_quantity: "100",
    quantity_per_hanger: 30,
  })

  it("признак стоит в самом начале строки — перед номером подвеса", () => {
    const row = renderRow(conflictPosition)
    const markerCellIndex = cells(row).findIndex((cell) => cell.querySelector('[data-route-state="expected"]'))
    const hangerCellIndex = cells(row).findIndex((cell) => /\(\d+П\)/.test(cell.textContent ?? ""))

    expect(markerCellIndex).toBe(0)
    expect(hangerCellIndex).toBeGreaterThan(0)
    expect(markerCellIndex).toBeLessThan(hangerCellIndex)
    const marker = cells(row)[markerCellIndex].querySelector('[data-route-state="expected"]')
    expect(marker?.getAttribute("title")).toBe("маршрут не назначен: показано ожидаемое имя")
    // Имя остаётся видимым — контракт «страница плана = предпросмотр импорта».
    expect(routeCell(row).textContent).toContain("ЮП-460 резка")
  })

  it("признак ожидаемого имени — тот же красный, что у ошибок строки", () => {
    const row = renderRow(conflictPosition)
    const marker = row.querySelector('[data-route-state="expected"]')

    expect(marker?.querySelector("svg")?.getAttribute("class")).toEqual(
      expect.stringContaining("text-red-600"),
    )
    expect(routeCell(row).querySelector(".text-red-700")?.textContent).toBe("ЮП-460 резка")
  })

  it("назначенный маршрут помечен как обычный, строка не меняется", () => {
    const row = renderRow(
      position({ route_id: 42, route_name: "ЮП-460 резка", status: "valid" }),
    )

    expect(row.querySelector('[data-route-state="expected"]')).toBeNull()
    expect(routeCell(row).textContent).toContain("ЮП-460 резка")
    expect(routeCell(row).querySelector(".text-blue-700")?.textContent).toBe("ЮП-460 резка")
  })

  it("признак работает и в режиме выбора маршрута из выпадающего списка", () => {
    const row = renderRow(conflictPosition, {
      routes: [{ id: 42, code: "R-42", name: "ЮП-460 резка", description: null, is_active: true }],
      onAssignRoute: vi.fn(),
    })
    const markerCellIndex = cells(row).findIndex((cell) => cell.querySelector('[data-route-state="expected"]'))

    expect(markerCellIndex).toBe(0)
    expect(routeCell(row).textContent).toContain("ЮП-460 резка")
  })
})
