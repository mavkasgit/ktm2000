/**
 * Поповер фильтра артикула на доске участка (#211, ADR-0044).
 *
 * Значения серверной колонки приходят из справочника (`filterValueOptions`), а
 * не из строк текущей страницы: значение с соседней страницы в поповере видно.
 * Клиентские колонки продолжают брать значения со страницы — этот путь тоже
 * сторожится здесь.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { SectionTasksBoard } from "./SectionTasksBoard";
import type { GroupingProfile } from "../lib/groupingProfiles";

const PROFILE: GroupingProfile = { id: "sku", name: "Артикул", criteria: ["productSku"] };

const TASK: SectionBoardTask = {
  id: 1,
  product_id: 1,
  product_sku: "PAGE-ONLY",
  section_plan_line_id: 1,
  plan_position_id: 1,
  route_step_id: 1,
  sequence: 1,
  operation_code: "op",
  operation_name: "Операция",
  is_significant: true,
  planned_quantity: "10",
  status: "ready",
  cache: {
    available_quantity: "10",
    issued_quantity: "0",
    completed_quantity: "0",
    transferred_quantity: "0",
    received_quantity: "0",
    rejected_quantity: "0",
    remaining_quantity: "10",
  },
  previous_stage: null,
  next_task_id: null,
  next_task_status: null,
  next_operation_name: null,
  source_ref: null,
  source_payload: {},
  source_fingerprint: null,
  input_sku: "PAGE-ONLY",
  output_sku: "PAGE-ONLY",
  display_sku: "PAGE-ONLY",
  route_history: [],
  route_history_after: [],
  route_history_full: [],
  route_history_after_full: [],
  operation_codes: [],
  operation_names: [],
};

function renderBoard(filterValueOptions?: Partial<Record<"productSku", string[]>>) {
  return render(
    <SectionTasksBoard
      tasks={[TASK]}
      total={1}
      isLoading={false}
      mode={{ active: true, waiting: true, completed: false }}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
      profile={PROFILE}
      filterValueOptions={filterValueOptions}
      page={1}
      setPage={vi.fn()}
      limit={50 as PageLimitOption}
      setLimit={vi.fn()}
      totalPages={1}
      rangeLabel=""
      onServerQueryChange={vi.fn()}
    />
  );
}

afterEach(cleanup);

describe("поповер артикула: серверный справочник важнее страничного", () => {
  it("показывает серверные значения, которых нет на странице, и не подмешивает страничные", () => {
    renderBoard({ productSku: ["SERVER-A", "SERVER-B"] });
    const pageSkusBefore = screen.getAllByText("PAGE-ONLY").length;

    fireEvent.click(screen.getByText("Артикул"));

    expect(screen.getByText("SERVER-A")).toBeTruthy();
    expect(screen.getByText("SERVER-B")).toBeTruthy();
    // Страничное значение в поповер не попало: его копий столько же, сколько
    // в строках доски (ни одной сверх).
    expect(screen.getAllByText("PAGE-ONLY").length).toBe(pageSkusBefore);
  });

  it("без серверного справочника список строится по странице — прежнее поведение", () => {
    renderBoard();
    const pageSkusBefore = screen.getAllByText("PAGE-ONLY").length;

    fireEvent.click(screen.getByText("Артикул"));

    expect(screen.getAllByText("PAGE-ONLY").length).toBeGreaterThan(pageSkusBefore);
    expect(screen.queryByText("SERVER-A")).toBeNull();
  });
});
