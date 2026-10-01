import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { SectionTasksBoard, type TaskBoardViewMode } from "./SectionTasksBoard";
import type { GroupingProfile } from "../lib/groupingProfiles";

const PROFILE: GroupingProfile = {
  id: "sku",
  name: "Артикул + размер",
  criteria: ["productSku"],
};

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

function renderBoard(
  tasks: SectionBoardTask[],
  mode: TaskBoardViewMode = { active: true, waiting: true, completed: false },
  onSelectAllVisible?: (ids: number[]) => void,
) {
  return renderToStaticMarkup(
    <SectionTasksBoard
      tasks={tasks}
      total={tasks.length}
      isLoading={false}
      mode={mode}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
      profile={PROFILE}
      onSelectAllVisible={onSelectAllVisible}
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

describe("SectionTasksBoard: блок «В ожидании»", () => {
  it("ставит активные задания выше разделителя, ожидающие — ниже", () => {
    const html = renderBoard([
      makeTask({ id: 1, product_sku: "SKU-ACTIVE", sequence: 1, status: "ready" }),
      makeTask({ id: 2, product_sku: "SKU-WAIT", sequence: 2, status: "waiting_previous" }),
    ]);

    const activeAt = html.indexOf("SKU-ACTIVE");
    const dividerAt = html.indexOf("В ожидании");
    const waitingAt = html.indexOf("SKU-WAIT");

    expect(activeAt).toBeGreaterThan(-1);
    expect(dividerAt).toBeGreaterThan(activeAt);
    expect(waitingAt).toBeGreaterThan(dividerAt);
  });

  it("разделяет смешанную группу: активные строки в верхнем блоке, ожидающие — в нижнем", () => {
    const html = renderBoard([
      makeTask({ id: 1, product_sku: "SKU-MIX", sequence: 1, status: "ready" }),
      makeTask({ id: 2, product_sku: "SKU-MIX", sequence: 2, status: "waiting_previous" }),
      makeTask({ id: 3, product_sku: "SKU-MIX", sequence: 3, status: "ready" }),
    ]);

    const dividerAt = html.indexOf("В ожидании");
    expect(dividerAt).toBeGreaterThan(-1);
    // Активные задания обе до разделителя, ожидающее — после.
    expect(html.indexOf("SKU-MIX")).toBeLessThan(dividerAt);
    expect(html.lastIndexOf("SKU-MIX")).toBeGreaterThan(dividerAt);
    // Ожидающих ровно одно — столько же показано в разделителе.
    expect(html).toMatch(/В ожидании<\/span><span class="[^"]*">1</);
  });

  it("не показывает разделитель, когда ожидающих нет", () => {
    const html = renderBoard([makeTask({ id: 1, product_sku: "SKU-ONLY", status: "ready" })]);

    expect(html).toContain("SKU-ONLY");
    expect(html).not.toContain("В ожидании");
  });

  it("показывает разделитель первым, если активных заданий нет", () => {
    const html = renderBoard([
      makeTask({ id: 1, product_sku: "SKU-WAIT-1", sequence: 1, status: "waiting_previous" }),
      makeTask({ id: 2, product_sku: "SKU-WAIT-2", sequence: 2, status: "pending" }),
    ]);

    const dividerAt = html.indexOf("В ожидании");
    expect(dividerAt).toBeGreaterThan(-1);
    expect(html.indexOf("SKU-WAIT-1")).toBeGreaterThan(dividerAt);
    expect(html.indexOf("SKU-WAIT-2")).toBeGreaterThan(dividerAt);
  });

  it("фильтрует ожидающие по обоим блокам: скрытая категория исчезает вместе с разделителем", () => {
    const tasks = [
      makeTask({ id: 1, product_sku: "SKU-ACTIVE", status: "ready" }),
      makeTask({ id: 2, product_sku: "SKU-WAIT", status: "waiting_previous" }),
    ];

    const onlyActive = renderBoard(tasks, { active: true, waiting: false, completed: false });
    expect(onlyActive).toContain("SKU-ACTIVE");
    expect(onlyActive).not.toContain("SKU-WAIT");
    expect(onlyActive).not.toContain("В ожидании");

    const onlyWaiting = renderBoard(tasks, { active: false, waiting: true, completed: false });
    expect(onlyWaiting).not.toContain("SKU-ACTIVE");
    expect(onlyWaiting).toContain("SKU-WAIT");
    expect(onlyWaiting).toContain("В ожидании");
  });

  it("пустое состояние остаётся, когда фильтр не нашёл ни задания в одном блоке", () => {
    const html = renderBoard([makeTask({ id: 1, product_sku: "SKU-A", status: "ready" })]);

    expect(html).toContain("SKU-A");
    expect(html).not.toContain("Нет задач, соответствующих фильтру");
  });
  it("счётчик «Выделить все» считает только активные задания", () => {
    const html = renderBoard(
      [
        makeTask({ id: 1, product_sku: "SKU-A1", sequence: 1, status: "ready" }),
        makeTask({ id: 2, product_sku: "SKU-A2", sequence: 2, status: "in_work" }),
        makeTask({ id: 3, product_sku: "SKU-W1", sequence: 3, status: "waiting_previous" }),
        makeTask({ id: 4, product_sku: "SKU-W2", sequence: 4, status: "pending" }),
      ],
      { active: true, waiting: true, completed: false },
      vi.fn(),
    );

    expect(html).toContain("Выделить все (2)");
  });
});

describe("SectionTasksBoard: колонка «Операция» несёт размеры, а не имя операции", () => {
  const boardTask = (overrides: Partial<SectionBoardTask> = {}) =>
    makeTask({
      product_sku: "SKU-SAW",
      operation_code: "SAW",
      operation_name: "Резка на пиле",
      operation_codes: ["SAW"],
      operation_names: ["Резка на пиле"],
      ...overrides,
    });

  it("без реальной резки показывает один итоговый размер", () => {
    const html = renderBoard([
      boardTask({ transforms_dimensions: true, cut_layout: { input: "2,5 м", outputs: [] } }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    expect(table.split("2,5 м").length - 1).toBe(1);
    expect(table).not.toContain("Резка на пиле");
  });

  it("с реальной резкой показывает вход, выходы и их количество", () => {
    const html = renderBoard([
      boardTask({
        transforms_dimensions: true,
        cut_layout: { input: "2,75", outputs: ["0,9×50", "1,35×100"] },
      }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    expect(table).toContain("2,75 →");
    expect(table).toContain("0,9×50");
    expect(table).toContain("1,35×100");
    expect(table).not.toContain("Резка на пиле");
  });

  it("нетрансформирующее задание несёт операции участка, а не размер", () => {
    const html = renderBoard([
      boardTask({
        operation_code: "ANOD_05",
        operation_name: "Чёрный",
        operation_codes: ["ANOD_05", "PACK_SPUNBOND"],
        operation_names: ["Чёрный", "Спанбонд"],
        dimensions: { length_mm: 2700 },
      }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    // Цвет — операция участка, упаковка уходит в свою колонку, размер остаётся
    // только в «Размере».
    expect(table).toContain("Чёрный");
    expect(table.split("2,7 м").length - 1).toBe(1);
  });

  it("несколько операций участка идут списком", () => {
    const html = renderBoard([
      boardTask({
        operation_code: "PRESS_WINDOW",
        operation_name: "Окно",
        operation_codes: ["PRESS_WINDOW", "PRESS_COMB", "PACK_STRETCH"],
        operation_names: ["Окно", "Гребенка", "Стрейч"],
      }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    expect(table).toContain("Окно · Гребенка");
  });

  it("прогресс по выходам на доске не рисуется", () => {
    const html = renderBoard([
      boardTask({
        transforms_dimensions: true,
        cut_layout: { input: "2,5 м", outputs: [] },
        outputs_progress: [
          { dimensions: { length_mm: 2500 }, quantity: "700", produced_quantity: "0" },
        ],
      }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    expect(table).not.toContain("0/700");
  });

  it("свёрнутая группа несёт тот же ярлык в шапке", () => {
    const html = renderBoard([
      boardTask({ id: 1, transforms_dimensions: true, cut_layout: { input: "2,5 м", outputs: [] } }),
      boardTask({ id: 2, transforms_dimensions: true, cut_layout: { input: "2,5 м", outputs: [] } }),
    ]);
    const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"));

    // Группы по умолчанию свёрнуты: видна только шапка — и несёт тот же размер.
    expect(table.split("2,5 м").length - 1).toBe(1);
    expect(table).not.toContain("Резка на пиле");
  });
});
