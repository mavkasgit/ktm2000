import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { QTY_EMPTY } from "@/shared/lib/quantityFormat";
import { PlanTaskTable } from "./PlanTaskTable";
import { buildPlanPairIndex, type PlanPairIndex } from "../lib/planTaskGroups";
import type { ProductPairCatalogEntry } from "@/shared/api/products";
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
 * Печатный лист участка: колонки `sku` + `hangers`. Служебная колонка отметки
 * строки внутри группы добавляется таблицей сама, поэтому в строке задания
 * третья ячейка — подвесы, а в шапке группы (она объединяет метки через
 * `colSpan`) вторая.
 */
const COLUMNS: PlanColumnKey[] = ["sku", "hangers"];

function render(
  tasks: SectionBoardTask[],
  pairs?: PlanPairIndex,
): HTMLTableRowElement[] {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <PlanTaskTable
      tasks={tasks}
      mode="article"
      hiddenGroupKeys={new Set()}
      onHideGroup={vi.fn()}
      columns={COLUMNS}
      pairs={pairs}
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

describe("лист плана: служебная колонка отметки строки", () => {
  function renderTable(tasks: SectionBoardTask[]) {
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
    return {
      headers: Array.from(host.querySelectorAll("thead th")),
      rows: Array.from(host.querySelectorAll("tbody tr")) as HTMLTableRowElement[],
    };
  }

  it("шапка «Группу» не подписывает: колонка — только отметка строки в группе", () => {
    const { headers } = renderTable([makeTask()]);

    expect(headers[0]?.textContent).toBe("");
    expect(headers.map((header) => header.textContent)).not.toContain("Группа");
  });

  it("колонка узкая, а «↳» стоит у строк внутри группы", () => {
    const { rows } = renderTable([
      makeTask({ id: 1, operation_name: "Операция 1" }),
      makeTask({ id: 2, operation_name: "Операция 2" }),
    ]);

    const markers = rows.slice(1).map((row) => row.querySelector("td"));

    expect(markers.map((cell) => cell?.textContent)).toEqual(["↳", "↳"]);
    // Ширину задаёт класс колонки: без него подпись «Группа» растягивала её
    // до половины листа и съедала место у печатных колонок.
    expect(markers[0]?.className).toContain("w-7");
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

describe("лист плана: единый подвес пары (#312)", () => {
  /** Пара 2604/2616 (id артикулов 11 и 12), ручная N=8 на длине 2700. */
  const PAIR: ProductPairCatalogEntry = {
    id: 7,
    product_a_id: 11,
    product_b_id: 12,
    lengths: [2700],
    quantity_per_hanger: { "2700": { auto: null, manual: 8 } },
  };
  const pairs: PlanPairIndex = buildPlanPairIndex([PAIR]);

  function pairTasks(): SectionBoardTask[] {
    return [
      makeTask({
        id: 1,
        product_id: 11,
        product_sku: "ЮП-2604",
        operation_name: "Анодирование",
        dimensions: { length_mm: 2700 },
        hanger_count: 19,
        quantity_per_hanger: 8,
        planned_quantity: "150",
      }),
      makeTask({
        id: 2,
        product_id: 12,
        product_sku: "ЮП-2616",
        operation_name: "Анодирование",
        dimensions: { length_mm: 2700 },
        hanger_count: 19,
        quantity_per_hanger: 8,
        planned_quantity: "150",
      }),
    ];
  }

  it("шапка группы печатает один подвес на пару, а не сумму по артикулам", () => {
    const [header] = render(pairTasks(), pairs);

    // 150 ÷ 8 = 18,75 → 19 подвесов. Сумма по строкам дала бы 38 — подвеса,
    // которого физически нет: на крюке едут оба артикула сразу.
    expect(cellTexts(header)[1]).toBe("19");
    expect(cellTexts(header)[0]).toContain("ЮП-2604+ЮП-2616");
  });

  it("колонка «Кол-во на подвес» печатает норму с обоими артикулами", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <PlanTaskTable
        tasks={pairTasks()}
        mode="article"
        hiddenGroupKeys={new Set()}
        onHideGroup={vi.fn()}
        columns={["sku", "hangers", "perHanger"]}
        pairs={pairs}
      />,
    );

    const header = host.querySelector("tbody tr") as HTMLTableRowElement;
    expect(cellTexts(header)[2]).toBe("8×ЮП-2604 + 8×ЮП-2616");
  });

  it("без каталога пар строки печатаются раздельно и суммируются как раньше", () => {
    const [headerA, headerB] = render(pairTasks());

    expect(cellTexts(headerA).slice(0, 3)).toEqual(["", "ЮП-2604", "19"]);
    expect(cellTexts(headerB).slice(0, 3)).toEqual(["", "ЮП-2616", "19"]);
  });
});
