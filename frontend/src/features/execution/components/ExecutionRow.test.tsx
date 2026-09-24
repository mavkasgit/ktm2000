import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProductionPlanningRow } from "@/shared/api/productionPlans";

import { executionTableColumns, getExecutionTableColumns } from "./execution-table-columns";
import { ExecutionRow } from "./ExecutionRow";

const row: ProductionPlanningRow = {
  plan_position_id: 101,
  production_plan_id: 21,
  source_row_number: 5,
  source_sku: "SKU-101",
  source_name: "Деталь",
  quantity: 10,
  dimensions: null,
  cut_layout: null,
  quantity_per_hanger: null,
  original_quantity: "10",
  position_status: "approved",
  validation_status: "valid",
  route_id: 3,
  route_name: "Маршрут",
  route_source: null,
  route_origin: null,
  route_match_quality: null,
  route_match_reason: null,
  route_assigned_at: null,
  route_manual_confirmed_at: null,
  route_error: null,
  is_released: false,
  has_tasks: false,
  is_completed: false,
  current_stage_section_id: null,
  current_stage_sequence: null,
  current_stage_operation: null,
  current_stage_section_code: null,
  current_stage_section_name: null,
  current_stage_task_status: null,
  available_remainder_quantity: null,
};

describe("ExecutionRow", () => {
  it("renders the source row and plan preview as one configured column", () => {
    const rowColumn = executionTableColumns.find((column) => column.id === "row");
    expect(rowColumn).toEqual(
      expect.objectContaining({ id: "row", label: "№ / План", width: "110px" }),
    );
    expect(getExecutionTableColumns(false).filter((column) => column.id === "row")).toHaveLength(1);
    expect(executionTableColumns.some((column) => column.id === "plan")).toBe(false);

    render(
      <table>
        <tbody>
          <ExecutionRow
            row={row}
            columns={rowColumn ? [rowColumn] : []}
            bulkMode={false}
            isSelected={false}
            sectionMetaById={new Map()}
            onToggleSelect={vi.fn()}
            onOpenDetail={vi.fn()}
            onSingleLaunch={vi.fn()}
            onManualPass={vi.fn()}
            onCancel={vi.fn()}
            onRestore={vi.fn()}
            onSoftDelete={vi.fn()}
            onSkuClick={vi.fn()}
          />
        </tbody>
      </table>,
    );

    const planLink = screen.getByRole("link", { name: "План 21" });
    const rowCell = planLink.closest("td");
    expect(rowCell?.textContent).toMatch(/^#5\s*·\s*План 21$/);
    expect(planLink.getAttribute("href")).toBe("/plans/21/preview");
    expect(planLink.getAttribute("target")).toBe("_blank");
  });
});
