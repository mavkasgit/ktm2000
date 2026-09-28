/**
 * Порядок строк доски при выбранной сортировке колонки.
 *
 * Регресс: группировка по профилю пересортировывала строки по количеству
 * и затирала выбранную сортировку (и серверную, и клиентскую) — шапка
 * показывала иконку, а порядок не менялся.
 */

import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { SectionTasksBoard } from "./SectionTasksBoard";
import type { GroupingProfile } from "../lib/groupingProfiles";

const PROFILE: GroupingProfile = { id: "sku", name: "sku", criteria: ["productSku"] };

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
  } as SectionBoardTask;
}

function renderBoard(tasks: SectionBoardTask[]) {
  return render(
    <SectionTasksBoard
      tasks={tasks}
      total={tasks.length}
      isLoading={false}
      mode={{ active: true, waiting: true, completed: false }}
      onModeChange={vi.fn()}
      onAction={vi.fn()}
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

/** Порядок строк доски по колонке «Артикул» (2-я ячейка). */
function renderedSkuOrder(): string[] {
  return [...document.querySelectorAll("tbody tr")]
    .map((row) => row.querySelectorAll("td")[1]?.textContent ?? "")
    .filter(Boolean);
}

/** Клик по кнопке сортировки колонки. Цикл: нет → убыв. → возр. → снять. */
function clickSort(field: string) {
  act(() => {
    screen.getByLabelText(new RegExp(`Сортировка по ${field}`)).click();
  });
}

/** Значения колонки «План» в порядке строк доски. */
function renderedPlanOrder(): string[] {
  return [...document.querySelectorAll("tbody tr")]
    .map((row) => row.querySelectorAll("td")[4]?.textContent ?? "")
    .filter(Boolean);
}

/** Значения колонки «Размер» в порядке строк доски. */
function renderedSizeOrder(): string[] {
  return [...document.querySelectorAll("tbody tr")]
    .map((row) => row.querySelectorAll("td")[2]?.textContent ?? "")
    .filter(Boolean);
}

describe("SectionTasksBoard: сортировка колонок", () => {
  it("серверный порядок по размеру не затирается группировкой", () => {
    // Задание с активной сортировкой «Размер» сервер отдаёт по размеру убыв.
    // (3 м → 2,7 м → 2 м), хотя количество убыв. даёт ровно обратный порядок.
    renderBoard([
      makeTask({ id: 1, product_sku: "BIG", dimensions: { length_mm: 3000 }, planned_quantity: "10" }),
      makeTask({ id: 2, product_sku: "MID", dimensions: { length_mm: 2700 }, planned_quantity: "500" }),
      makeTask({ id: 3, product_sku: "SML", dimensions: { length_mm: 2000 }, planned_quantity: "900" }),
    ]);
    clickSort("dimensions");

    expect(renderedSkuOrder()).toEqual(["BIG", "MID", "SML"]);
  });

  it("клиентская сортировка по «План» упорядочивает строки в обе стороны", () => {
    renderBoard([
      makeTask({ id: 1, product_sku: "A", planned_quantity: "10" }),
      makeTask({ id: 2, product_sku: "B", planned_quantity: "900" }),
      makeTask({ id: 3, product_sku: "C", planned_quantity: "500" }),
    ]);

    clickSort("plannedQty");
    expect(renderedSkuOrder()).toEqual(["B", "C", "A"]);

    clickSort("plannedQty");
    expect(renderedSkuOrder()).toEqual(["A", "C", "B"]);
  });

  it("клиентская сортировка по «План» упорядочивает строки одного артикула разных размеров", () => {
    // Артикул+размер — принудительный критерий группировки: строки одного
    // артикула разных размеров не склеиваются и сортируются независимо.
    renderBoard([
      makeTask({ id: 1, product_sku: "A", dimensions: { length_mm: 1000 }, planned_quantity: "10" }),
      makeTask({ id: 2, product_sku: "A", dimensions: { length_mm: 2000 }, planned_quantity: "900" }),
    ]);

    clickSort("plannedQty");
    clickSort("plannedQty"); // возрастание

    expect(renderedPlanOrder()).toEqual(["10", "900"]);
    expect(renderedSizeOrder()).toEqual(["1 м", "2 м"]);
  });

  it("клиентская сортировка накладывается поверх серверного порядка", () => {
    // Строки приходят отсортированными сервером по размеру (1 м → 2 м), а
    // выбранная «План» — клиентская колонка: порядок определяет она сама.
    renderBoard([
      makeTask({ id: 1, product_sku: "A", dimensions: { length_mm: 1000 }, planned_quantity: "900" }),
      makeTask({ id: 2, product_sku: "B", dimensions: { length_mm: 2000 }, planned_quantity: "10" }),
      makeTask({ id: 3, product_sku: "C", dimensions: { length_mm: 3000 }, planned_quantity: "500" }),
    ]);

    clickSort("plannedQty");

    expect(renderedSkuOrder()).toEqual(["A", "C", "B"]);
  });

  it("второй приоритет по клиентской колонке тоже применяется", () => {
    // Регресс: при двух выбранных колонках сортировалась только первая —
    // у строк с равным планом порядок оставался прежним, а бейдж «2» в шапке
    // обещал учёт второй колонки.
    renderBoard([
      makeTask({
        id: 1,
        product_sku: "A",
        planned_quantity: "100",
        cache: { ...makeTask().cache, issued_quantity: "5" },
      }),
      makeTask({
        id: 2,
        product_sku: "B",
        planned_quantity: "100",
        cache: { ...makeTask().cache, issued_quantity: "50" },
      }),
      makeTask({ id: 3, product_sku: "C", planned_quantity: "200" }),
    ]);

    clickSort("plannedQty");
    clickSort("issuedQty");

    // План убыв.: C(200), затем равные 100 — по «Выдано» убыв.: B(50) раньше A(5).
    expect(renderedSkuOrder()).toEqual(["C", "B", "A"]);
  });

  it("без сортировки — дефолт: количество убыв., при равных размер убыв.", () => {
    renderBoard([
      makeTask({ id: 1, product_sku: "A", planned_quantity: "10", dimensions: { length_mm: 3000 } }),
      makeTask({ id: 2, product_sku: "B", planned_quantity: "900", dimensions: { length_mm: 1000 } }),
      makeTask({ id: 3, product_sku: "C", planned_quantity: "10", dimensions: { length_mm: 2000 } }),
    ]);

    // 900 — первым; затем равные 10: 3 м раньше 2 м.
    expect(renderedSkuOrder()).toEqual(["B", "A", "C"]);
  });
});
