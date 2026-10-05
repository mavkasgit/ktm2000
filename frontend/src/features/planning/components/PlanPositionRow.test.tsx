import type { ComponentProps } from "react"

import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import type { PlanPositionOut } from "@/shared/api/productionPlans"
import type { ProductionRoute } from "@/shared/api/routes"
import { planColumns } from "../lib/planColumns"
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
  props?: Partial<ComponentProps<typeof PositionRow>>,
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
function renderRow(
  pos: PlanPositionOut,
  props?: Partial<ComponentProps<typeof PositionRow>>,
): HTMLElement {
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

/**
 * Пара «Ошибки»/«Предупр.»: какие ячейки строки пришлись на её слоты.
 * Ячейки берутся по месту — сразу за «Маршрутом» и перед «Действиями» с
 * уголком, — а не по цвету текста: перекрытая валидация и дубликат строки
 * печатаются в ячейке «Ошибки» не красным.
 */
function messageCells(
  pos: PlanPositionOut,
  props?: Partial<ComponentProps<typeof PositionRow>>,
) {
  const row = renderRow(pos, props)
  const all = cells(row)

  return { row, pair: all.slice(all.indexOf(routeCell(row)) + 1, -2) }
}

/** Сумма colSpan строки обязана равняться числу колонок таблицы. */
function slotsOf(row: HTMLElement): number {
  return cells(row).reduce((sum, cell) => sum + Number(cell.getAttribute("colspan") ?? 1), 0)
}

/** Колонки описания + «Действия» + уголок сброса. */
const PLAN_TABLE_COLUMNS = planColumns.length + 2

describe("PositionRow — пара «Ошибки»/«Предупр.»", () => {
  it("только предупреждение занимает обе колонки пары", () => {
    const { pair } = messageCells(position({ warnings: ["hanger_quantity_not_set:2.7"] }))

    expect(pair).toHaveLength(1)
    expect(pair[0].getAttribute("colspan")).toBe("2")
    expect(pair[0].textContent).toContain("Не задано количество на подвес")
  })

  it("только ошибка занимает обе колонки пары", () => {
    const { pair } = messageCells(position({ errors: ["product_not_found"] }))

    expect(pair).toHaveLength(1)
    expect(pair[0].getAttribute("colspan")).toBe("2")
    expect(pair[0].textContent).toContain("Продукт не найден")
  })

  it("оба типа — по одной колонке, у каждого блока свой title", () => {
    const { pair } = messageCells(
      position({
        errors: ["product_not_found", "quantity_must_be_positive"],
        warnings: ["hanger_quantity_not_set:2.7"],
      }),
    )

    expect(pair).toHaveLength(2)
    expect(pair[0].getAttribute("colspan")).toBe("1")
    expect(pair[1].getAttribute("colspan")).toBe("1")
    // Каждый код — свой элемент блока, а не склейка через запятую.
    const errorLines = pair[0].querySelector("[title]")!.children
    expect(Array.from(errorLines)).toHaveLength(2)
    expect(Array.from(errorLines).map((line) => line.textContent)).toEqual([
      "Продукт не найден",
      "Количество должно быть положительным",
    ])
    expect(pair[0].querySelector("[title]")?.getAttribute("title")).toContain("Продукт не найден")
    expect(pair[1].querySelector("[title]")?.getAttribute("title")).toContain("Не задано количество")
  })

  it("без сообщений пара не рисуется — слоты забирает «Маршрут»", () => {
    const { row, pair } = messageCells(position({}))

    expect(pair).toHaveLength(0)
    expect(routeCell(row).getAttribute("colspan")).toBe("3")
  })

  it("строка занимает все колонки при любом наборе сообщений", () => {
    const cases: Partial<PlanPositionOut>[] = [
      {},
      { warnings: ["hanger_quantity_not_set:2.7"] },
      { errors: ["product_not_found"] },
      { errors: ["product_not_found"], warnings: ["hanger_quantity_not_set:2.7"] },
      {
        status: "approved",
        validation_status: "overridden",
        errors: ["route_contains_excluded_step: DRILLING"],
      },
    ]

    for (const overrides of cases) {
      const { row, pair } = messageCells(position(overrides))
      const label = JSON.stringify(overrides)
      const rowCells = cells(row)
      const actions = rowCells[rowCells.length - 2]
      const corner = rowCells[rowCells.length - 1]

      expect(slotsOf(row), label).toBe(PLAN_TABLE_COLUMNS)
      // «Действия» и уголок сброса остаются на своих местах, а перед ними —
      // только слоты пары.
      expect(actions.textContent?.trim(), label).not.toBe("")
      expect(corner.getAttribute("class"), label).toContain("w-10")
      expect(pair.length, label).toBeLessThanOrEqual(2)
    }
  })

  it("дубликат строки Excel печатается в ячейке пары и тянет её на обе колонки", () => {
    const { pair } = messageCells(
      position({ status: "invalid", errors: [], warnings: [] }),
      {
        duplicateConflict: { fingerprint: "abc", conflictIds: [99] },
        onJumpToPosition: vi.fn(),
      },
    )

    expect(pair).toHaveLength(1)
    expect(pair[0].getAttribute("colspan")).toBe("2")
    expect(pair[0].textContent).toContain("Дубликат Excel-строки")
  })

  it("перекрытая валидация видна в паре и тянет её на обе колонки", () => {
    const { pair } = messageCells(
      position({
        status: "approved",
        validation_status: "overridden",
        errors: ["route_contains_excluded_step: DRILLING"],
      }),
    )

    expect(pair).toHaveLength(1)
    expect(pair[0].getAttribute("colspan")).toBe("2")
    expect(pair[0].textContent).toContain("Перекрыта")
  })
})

describe("PositionRow — связь пары в ячейке «Id»", () => {
  const link = (ordinal: number, total: number) => ({
    title: "Пара ЮП-2604+ЮП-2616 · 30 шт на подвес",
    ordinal,
    total,
  })

  /** Ячейка «Id» строки: в таблице это первая. */
  function idCell(props: Partial<ComponentProps<typeof PositionRow>>): HTMLElement {
    return cells(renderRow(position({}), props))[0]
  }

  it("показывает номер строки в паре и подпись пары в подсказке", () => {
    const badge = idCell({ rowLink: link(2, 2) }).querySelector("[data-pair-link]")

    expect(badge?.textContent).toBe("2/2")
    expect(badge?.getAttribute("title")).toContain("ЮП-2604+ЮП-2616")
    expect(badge?.getAttribute("title")).toContain("30 шт на подвес")
  })

  it("строка вне пары остаётся с голым номером", () => {
    // Пары нет — значит, связывать не с чем, а пустая ячейка с номером
    // читается как «здесь ничего особенного».
    const cell = idCell({})

    expect(cell.querySelector("[data-pair-link]")).toBeNull()
    expect(cell.textContent).toContain("#5633")
  })

  it("метка пары не вытесняет номер позиции", () => {
    // Номер позиции нужен оператору всегда: по нему открывают детали и по
    // нему же утверждают. Метка пары — дописка под ним, а не вместо него.
    const cell = idCell({ rowLink: link(1, 2) })

    expect(cell.textContent).toContain("#5633")
    expect(cell.textContent).toContain("1/2")
  })
})
