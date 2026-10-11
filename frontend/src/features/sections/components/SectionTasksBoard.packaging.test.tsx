/**
 * Колонка «Упаковка» — только у участка с упаковочными операциями.
 *
 * Признак приходит пропом `hasPackaging` из справочника участков
 * (`Section.has_packaging`), считается по операциям участка на бэкенде.
 * Проверяется доска целиком: шапка, строка задания, шапка группы и карточка
 * узкого экрана берут один и тот же признак, и рассинхрон между ними —
 * единственный способ сломать правку незаметно.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { stubViewportWidth } from "@/shared/lib/testViewport";
import { SectionTasksBoard } from "./SectionTasksBoard";
import type { GroupingProfile } from "../lib/groupingProfiles";

const PROFILE: GroupingProfile = { id: "sku", name: "sku", criteria: ["productSku"] };

/** Задание с упаковочной операцией: колонка «Упаковка» несёт её название. */
function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "PACK_GLUE",
    operation_name: "Склейка",
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
    input_sku: "SKU-A",
    output_sku: "SKU-A",
    display_sku: "SKU-A",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: ["PACK_GLUE"],
    operation_names: ["Склейка"],
    ...overrides,
  } as SectionBoardTask;
}

function renderBoard(hasPackaging: boolean | undefined) {
  const tasks = [makeTask()];
  return render(
    <SectionTasksBoard
      tasks={tasks}
      total={tasks.length}
      isLoading={false}
      mode={{ active: true, waiting: true, completed: false }}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
      hasPackaging={hasPackaging}
      profile={PROFILE}
      page={1}
      setPage={vi.fn()}
      limit={50 as PageLimitOption}
      setLimit={vi.fn()}
      totalPages={1}
      rangeLabel=""
      onServerQueryChange={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * Доска под гейтом рисует один экран за раз: по умолчанию в тестах десктоп
 * (happy-dom — 1024px), мобильный — после `stubViewportWidth` перед рендером.
 */
function renderMobileBoard(hasPackaging: boolean | undefined) {
  cleanup();
  stubViewportWidth(375);
  return renderBoard(hasPackaging);
}

function bodyCells(selector: string): HTMLTableCellElement[][] {
  return [...document.querySelectorAll(selector)]
    .map((row) => [...row.querySelectorAll("td")])
    .filter((cells) => cells.length > 1);
}

describe("SectionTasksBoard: «Упаковка» только у участка с упаковочными операциями", () => {
  it("без упаковочных операций колонки нет ни в шапке, ни в теле, ни в карточке", () => {
    renderBoard(false);

    expect(screen.queryByText(/Упаковка/)).toBeNull();
    expect(screen.queryByText("Склейка")).toBeNull();

    renderMobileBoard(false);

    expect(screen.queryByText(/Упаковка/)).toBeNull();
    expect(screen.queryByText("Склейка")).toBeNull();
  });

  it("с упаковочными операциями шапка и строка задания несут значение на обоих экранах", () => {
    // Десктоп: колонка в шапке таблицы и значение в строке задания
    // (у одиночной группы шапки группы нет — ни на одном экране).
    renderBoard(true);
    expect(screen.getAllByText(/Упаковка/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Склейка").length).toBe(1);

    // Мобильный: та же колонка в карточке задания.
    renderMobileBoard(true);
    expect(screen.getAllByText(/Упаковка/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Склейка").length).toBe(1);
  });

  it("флаг не пришёл — колонка остаётся: ошибка справочника не прячет данные", () => {
    renderBoard(undefined);
    expect(screen.getAllByText("Склейка").length).toBe(1);

    renderMobileBoard(undefined);
    expect(screen.getAllByText("Склейка").length).toBe(1);
  });

  it("число ячеек строки совпадает с шапкой при любом флаге", () => {
    for (const hasPackaging of [true, false, undefined]) {
      const { unmount } = renderBoard(hasPackaging);
      const headerCells = document.querySelectorAll("thead th").length;
      for (const cells of bodyCells('tbody tr[data-row-kind="board-task"], tbody tr:not([data-row-kind])')) {
        expect(cells.length, `hasPackaging=${String(hasPackaging)}`).toBe(headerCells);
      }
      unmount();
    }
  });
});
