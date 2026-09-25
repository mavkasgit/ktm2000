import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { DeletePlanConfirmDialog } from "./DeletePlanConfirmDialog"

const preview = {
  plan_id: 7,
  plan_no: "PLAN-2026-001",
  positions: 12,
  work_tasks: 4,
  transfers: 1,
  ledger_entries: 8,
  active_actions: 3,
  used_positions: [
    { position_id: 11, source_sku: "FG-001", status: "released", task_count: 2, action_count: 2 },
  ],
  cancellations: {
    positions: 12,
    work_tasks: 4,
    transfers: 1,
    defects: 0,
    rework_tasks: 0,
    daily_plan_items: 2,
  },
  stock_effects: [
    {
      transaction_id: 31,
      action_id: 41,
      product_id: 3,
      product_sku: "FG-001",
      reason: "final_release",
      quantity: "10",
      dimensions: { length_mm: 2700 },
      from_location: "Готовая продукция",
      to_location: "Отправлено",
      effect: "reverse" as const,
    },
  ],
  blockers: [],
}

describe("DeletePlanConfirmDialog", () => {
  it("requires an exact plan number and a reason before confirming", () => {
    const onConfirm = vi.fn()
    render(
      <DeletePlanConfirmDialog
        open
        planNo="PLAN-2026-001"
        planName="Сентябрьский план"
        preview={preview}
        previewLoading={false}
        deleting={false}
        onOpenChange={vi.fn()}
        onConfirm={onConfirm}
      />,
    )

    expect(screen.getByText("Уже задействованные строки")).toBeTruthy()
    expect(screen.getAllByText("FG-001")).toHaveLength(2)
    expect(screen.getByText("Что отменится")).toBeTruthy()
    expect(screen.getByText("Что откатится на остатках")).toBeTruthy()

    const confirm = screen.getByRole("button", {
      name: "Удалить план целиком",
    }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)

    fireEvent.change(screen.getByPlaceholderText("Например: ошибочно импортированный план"), {
      target: { value: "Ошибочный импорт" },
    })
    fireEvent.change(screen.getByDisplayValue(""), {
      target: { value: "PLAN-2026-001" },
    })

    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith("Ошибочный импорт")
  })
})
