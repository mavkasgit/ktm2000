import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { QTY_EMPTY } from "@/shared/lib/quantityFormat";
import { PlanTaskTable } from "./PlanTaskTable";
import type { PlanColumnKey } from "../lib/planPrintSettings";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Полировка",
    is_significant: true,
    planned_quantity: "20",
    status: "ready",
    cache: {
      available_quantity: "20",
      issued_quantity: "0",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "20",
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
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

/**
 * Печатный лист участка: колонки `sku` + `hangers`. Служебная колонка
 * «Группа» добавляется таблицей сама, поэтому в строке задания третья ячейка
 * — подвесы, а в шапке группы (она объединяет метки через `colSpan`) вторая.
 */
const COLUMNS: PlanColumnKey[] = ["sku", "hangers"];

function render(tasks: SectionBoardTask[]): HTMLTableRowElement[] {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <PlanTaskTable
      tasks={tasks}
      mode="article"
      hiddenGroupKeys={new Set()}
      onHideGroup={vi.fn()}
      columns={COLUMNS}
    />,
  );
  return Array.from(host.querySelectorAll("tbody tr"));
}

function cellTexts(row: HTMLTableRowElement): string[] {
  return Array.from(row.querySelectorAll("td")).map((td) => td.textContent ?? "");
}

describe("лист плана: колонка «Подвесы» (T17)", () => {
  it("без данных от бэкенда печатает «—», а не выдуманную единицу", () => {
    const [row] = render([
      makeTask({ hanger_count: null, quantity_per_hanger: null, source_payload: {} }),
    ]);

    const hangers = cellTexts(row)[2];
    expect(hangers).toBe(QTY_EMPTY);
    expect(hangers).not.toBe("1");
    expect(hangers).not.toBe("0");
  });

  it("неположительная норма — тоже отсутствие значения, а не один подвес", () => {
    for (const quantityPerHanger of [null, 0, -5]) {
      const [row] = render([
        makeTask({ hanger_count: undefined, quantity_per_hanger: quantityPerHanger }),
      ]);

      expect(cellTexts(row)[2]).toBe(QTY_EMPTY);
    }
  });

  it("неположительное количество при известной норме — «—»", () => {
    const [row] = render([
      makeTask({ hanger_count: null, quantity_per_hanger: 8, planned_quantity: "0" }),
    ]);

    expect(cellTexts(row)[2]).toBe(QTY_EMPTY);
  });

  it("известная норма: подвесы считаются вверх, дробный остаток не теряется", () => {
    const [row] = render([
      makeTask({ hanger_count: null, quantity_per_hanger: 8, planned_quantity: "20" }),
    ]);

    expect(cellTexts(row)[2]).toBe("3");
  });

  it("норма из снапшота пары считается, если у задания своего поля нет", () => {
    const [row] = render([
      makeTask({
        hanger_count: undefined,
        quantity_per_hanger: null,
        source_payload: { product_pair: { resolved: true, quantity_per_hanger: 8 } },
      }),
    ]);

    expect(cellTexts(row)[2]).toBe("3");
  });

  it("готовый hanger_count бэкенда приоритетнее локального счёта", () => {
    const [row] = render([
      makeTask({ hanger_count: 7, quantity_per_hanger: 8, planned_quantity: "20" }),
    ]);

    expect(cellTexts(row)[2]).toBe("7");
  });
});

describe("лист плана: шапка группы и пропуск в сумме (T17)", () => {
  /** Две строки одной группы: разная операция разносит их по разным строкам. */
  function groupTasks(overrides: Partial<SectionBoardTask>[]): SectionBoardTask[] {
    return overrides.map((extra, index) =>
      makeTask({
        id: index + 1,
        operation_name: `Операция ${index + 1}`,
        ...extra,
      }),
    );
  }

  it("все строки известны — шапка печатает сумму", () => {
    const rows = render(
      groupTasks([
        { hanger_count: 2, quantity_per_hanger: 8, planned_quantity: "20" },
        { hanger_count: 3, quantity_per_hanger: 8, planned_quantity: "20" },
      ]),
    );

    expect(cellTexts(rows[0])[1]).toBe("5");
  });

  it("пропуск в одной строке не превращается в заниженную сумму шапки", () => {
    const [header, ...dataRows] = render(
      groupTasks([
        { hanger_count: 2, quantity_per_hanger: 8, planned_quantity: "20" },
        { hanger_count: null, quantity_per_hanger: null, planned_quantity: "20" },
      ]),
    );

    // Строка без данных честно печатает «—» …
    expect(dataRows.map((row) => cellTexts(row)[2])).toEqual(["2", QTY_EMPTY]);
    // … и шапка не выдаёт за сумму только известные строки.
    expect(cellTexts(header)[1]).toBe(QTY_EMPTY);
    expect(cellTexts(header)[1]).not.toBe("2");
  });
});
