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

/** Порядок строк доски по колонке «Артикул». */
function renderedSkuOrder(): string[] {
  return renderedColumnOrder("Артикул");
}

/**
 * Кнопка сортировки колонки: доступное имя собирается из подписи колонки
 * (#204), поэтому тест адресует кнопку по машинному полю в `data-sort-field`.
 */
function sortButton(field: string): HTMLElement {
  const button = document.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
  if (!button) throw new Error(`Не найдена кнопка сортировки колонки «${field}»`);
  return button;
}

/** Клик по кнопке сортировки колонки. Цикл: нет → убыв. → возр. → снять. */
function clickSort(field: string) {
  act(() => {
    sortButton(field).click();
  });
}

/**
 * Значения колонки по её заголовку, только по строкам заданий.
 *
 * Индексы ячеек — не контракт: добавление колонки сдвигает их все, и тест
 * падал бы на разметке, а не на сортировке. Ищем колонку по подписи, а строки
 * берём помеченные: шапка группы и строка «В ожидании» тоже живут в tbody.
 */
function renderedColumnOrder(label: string): string[] {
  const headers = [...document.querySelectorAll("thead th")];
  const index = headers.findIndex((cell) => cell.textContent?.trim().startsWith(label));
  if (index < 0) throw new Error(`На доске нет колонки «${label}»`);
  return [...document.querySelectorAll('tbody tr[data-row-kind="board-task"]')]
    .map((row) => row.querySelectorAll("td")[index]?.textContent ?? "")
    .filter(Boolean);
}

/** Значения колонки в строках шапок групп (агрегаты по всей группе). */
function renderedGroupColumnOrder(label: string): string[] {
  const headers = [...document.querySelectorAll("thead th")];
  const index = headers.findIndex((cell) => cell.textContent?.trim().startsWith(label));
  if (index < 0) throw new Error(`На доске нет колонки «${label}»`);
  return [...document.querySelectorAll("tbody tr")]
    .filter((row) => !row.matches('[data-row-kind="board-task"]'))
    .filter((row) => row.querySelectorAll("td").length > 1)
    .map((row) => row.querySelectorAll("td")[index]?.textContent ?? "")
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

    expect(renderedColumnOrder("План")).toEqual(["10", "900"]);
    expect(renderedColumnOrder("Размер")).toEqual(["1 м", "2 м"]);
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

describe("SectionTasksBoard: колонки «Операция» и «Упаковка»", () => {
  it("цвет позиции стоит в «Операции», упаковка — в своей колонке", () => {
    // Регресс #210: участок с двумя группами (цвет + упаковка) отдавал в
    // «Операции» весь список через «+», и цвет позиции тонул рядом с видом
    // упаковки.
    renderBoard([
      makeTask({
        id: 1,
        operation_code: "ANOD_05",
        operation_name: "Чёрный",
        operation_codes: ["ANOD_05", "PACK_SPUNBOND"],
        operation_names: ["Чёрный", "Спанбонд"],
      }),
    ]);

    expect(renderedColumnOrder("Операция")).toEqual(["Чёрный"]);
    expect(renderedColumnOrder("Упаковка")).toEqual(["Спанбонд"]);
  });

  it("участок без упаковочной операции показывает прочерк в «Упаковке»", () => {
    renderBoard([
      makeTask({
        id: 1,
        operation_code: "SAW",
        operation_name: "Резка на пиле",
        operation_codes: ["SAW"],
        operation_names: ["Резка на пиле"],
      }),
    ]);

    expect(renderedColumnOrder("Упаковка")).toEqual(["—"]);
  });

  it("упаковка первой операцией в «Операции» не дублируется", () => {
    // На упаковке единственная операция участка — сама упаковка. Печатный
    // лист это уже учёл (в профиле PACKING колонки «Операция» нет); доска
    // показывала одно и то же значение дважды.
    renderBoard([
      makeTask({
        id: 1,
        operation_code: "PACK",
        operation_name: "Упаковка",
        operation_codes: ["PACK"],
        operation_names: ["Упаковка"],
      }),
    ]);

    expect(renderedColumnOrder("Операция")).toEqual(["—"]);
    expect(renderedColumnOrder("Упаковка")).toEqual(["Упаковка"]);
  });
});
