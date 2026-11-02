/**
 * Доска участка на телефоне — таблица, а не карточки (#345).
 *
 * Контракт: на узком экране доска рисует ту же таблицу (`MobileScrollTable`),
 * «SKU/профиль» закреплён слева, «Действия» справа, а поля идут в порядке
 * оператора: профиль → размер → остаток → план → «Годные» → «Брак» → действие,
 * вторичное — дальше по свайпу. Карточек задания больше нет: единственный
 * носитель строки — `<tr>`, и выбор строки работает тем же правилом.
 *
 * Групповое состояние (суммы, свёрнутость, выделение) — одно на обе раскладки:
 * шапка группы считает его через `buildTaskGroupView`, а не складывает
 * количества в разметке.
 */

import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { useBulkSelection } from "@/shared/bulk";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { stubViewportWidth } from "@/shared/lib/testViewport";
import type { BulkDraft } from "../lib/bulkDraft";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { SectionTasksBoard } from "./SectionTasksBoard";

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
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
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

function Harness({
  tasks,
  initialBulkMode = true,
}: {
  tasks: SectionBoardTask[];
  initialBulkMode?: boolean;
}) {
  const [draft, setDraft] = useState<BulkDraft>({});
  const [bulkMode, setBulkMode] = useState(initialBulkMode);
  const bulkSelection = useBulkSelection<number>();
  return (
    <>
      <button type="button" onClick={() => setBulkMode((prev) => !prev)}>
        {bulkMode ? "выйти из массового режима" : "включить массовый режим"}
      </button>
      <SectionTasksBoard
        tasks={tasks}
        total={tasks.length}
        isLoading={false}
        mode={{ active: true, waiting: true, completed: false }}
        onModeChange={vi.fn()}
        onAction={vi.fn()}
        // «Завершить группу» живёт в закреплённой колонке шапки: без колбэка
        // ячейка пустая, и правило пиктограммы (#345) проверить было бы не на
        // чём.
        onCompleteGroup={vi.fn()}
        profile={PROFILE}
        bulkMode={bulkMode}
        bulkSelection={bulkMode ? bulkSelection : undefined}
        bulkDraft={draft}
        onBulkDraftChange={setDraft}
        onVisibleTaskIdsChange={vi.fn()}
        page={1}
        setPage={vi.fn()}
        limit={50 as PageLimitOption}
        setLimit={vi.fn()}
        totalPages={1}
        rangeLabel=""
        onServerQueryChange={vi.fn()}
      />
      <output data-testid="draft">{JSON.stringify(draft)}</output>
    </>
  );
}

/** Отрисовка «как на телефоне»: порог телефона в проекте — 768px. */
function renderMobile(tasks: SectionBoardTask[], initialBulkMode = true) {
  stubViewportWidth(375);
  return render(<Harness tasks={tasks} initialBulkMode={initialBulkMode} />);
}

afterEach(() => {
  vi.restoreAllMocks();
});

/** Колонки первой строки задания в порядке разметки. */
function columnOrder(row: HTMLElement): string[] {
  return Array.from(row.querySelectorAll("td")).map(
    (cell) => cell.getAttribute("data-column") ?? "",
  );
}

describe("SectionTasksBoard на телефоне: таблица с закреплёнными колонками", () => {
  it("рисует таблицу, а не карточки: строка задания — это <tr>", () => {
    const { container } = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })]);

    expect(container.querySelectorAll("table")).toHaveLength(1);
    expect(container.querySelector('tr[data-task-id="1"]')).toBeTruthy();
    // Карточек задания больше нет: единственный носитель строки — таблица.
    expect(container.querySelector('div[data-task-id="1"]')).toBeNull();
  });

  it("профиль закреплён слева, действия — справа", () => {
    const { container } = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })]);
    const row = container.querySelector('tr[data-task-id="1"]') as HTMLElement;

    const profile = row.querySelector('td[data-sticky="profile"]') as HTMLElement;
    const actions = row.querySelector('td[data-sticky="actions"]') as HTMLElement;
    expect(profile, "закреплённый профиль строки").toBeTruthy();
    expect(actions, "закреплённые действия строки").toBeTruthy();
    expect(profile.getAttribute("data-column")).toBe("productSku");
    expect(actions.getAttribute("data-column")).toBe("actions");
    expect(profile.textContent).toContain("SKU-A");
    expect(within(actions).getByRole("button", { name: "Завершить" })).toBeTruthy();
  });

  it("поля идут в порядке оператора: размер, остаток, план, «Годные», «Брак», действие", () => {
    const { container } = renderMobile([
      makeTask({ id: 1, product_sku: "SKU-A", dimensions: { length_mm: 2700 } }),
    ]);
    const row = container.querySelector('tr[data-task-id="1"]') as HTMLElement;
    const order = columnOrder(row);

    expect(order.slice(0, 7)).toEqual([
      "productSku",
      "dimensions",
      "remainingQty",
      "plannedQty",
      "completedQty",
      "rejectedQty",
      "actions",
    ]);
    // Вторичное — после действия, по свайпу.
    expect(order).toContain("issuedQty");
    expect(order.indexOf("issuedQty")).toBeGreaterThan(order.indexOf("actions"));
  });
});

describe("SectionTasksBoard на телефоне: выделение и ввод в строке", () => {
  it("тап по строке открывает поля «Годные»/«Брак» и пишет в черновик", () => {
    const { container } = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })]);
    const row = container.querySelector('tr[data-task-id="1"]') as HTMLElement;

    expect(within(row).queryByLabelText("SKU-A: годные")).toBeNull();
    fireEvent.click(row);

    const good = within(row).getByLabelText("SKU-A: годные");
    fireEvent.change(good, { target: { value: "4" } });

    expect(screen.getByTestId("draft").textContent).toBe('{"1":{"good":"4","defect":""}}');
  });

  it("клавиатура строки работает тем же правилом, что на десктопе", () => {
    const { container } = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })], false);
    const row = container.querySelector('tr[data-task-id="1"]') as HTMLElement;
    fireEvent.click(screen.getByRole("button", { name: "включить массовый режим" }));

    fireEvent.keyDown(row, { key: "Enter" });

    expect(within(row).getByLabelText("SKU-A: годные")).toBeTruthy();
  });
});

describe("SectionTasksBoard на телефоне: группа заданий", () => {
  const pair = () => [
    makeTask({
      id: 1,
      product_sku: "SKU-A",
      cache: { ...makeTask().cache, issued_quantity: "10", completed_quantity: "4", transferred_quantity: "3", remaining_quantity: "6" },
    }),
    makeTask({
      id: 2,
      product_sku: "SKU-A",
      cache: { ...makeTask().cache, issued_quantity: "20", completed_quantity: "6", transferred_quantity: "7", remaining_quantity: "11" },
    }),
  ];

  it("шапка группы показывает суммы, посчитанные один раз", () => {
    const { container } = renderMobile(pair(), false);
    const header = container.querySelector('tr[data-row-kind="board-group"]') as HTMLElement;

    expect(header).toBeTruthy();
    expect(header.querySelector('[data-column="remainingQty"]')?.textContent).toBe("17");
    expect(header.querySelector('[data-column="plannedQty"]')?.textContent).toBe("20");
    expect(header.querySelector('[data-column="completedQty"]')?.textContent).toBe("10");
    // Суммы нет второй копией в той же шапке (ревью #283 п. 2): у колонки
    // ровно одна ячейка.
    expect(header.querySelectorAll('[data-column="remainingQty"]')).toHaveLength(1);
  });

  it("групповой ввод остаётся в шапке и раскладывается по строкам", () => {
    // Записанного факта нет: «12» — цель группы, и она раскладывается по
    // потолкам строк (10 и доступное во второй), как на десктопе (#283).
    const rowsForInput = [
      makeTask({ id: 1, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "10" } }),
      makeTask({ id: 2, product_sku: "SKU-A", cache: { ...makeTask().cache, issued_quantity: "20" } }),
    ];
    const { container } = renderMobile(rowsForInput);

    const groupInput = within(container).getByLabelText("SKU-A: годные группы");
    fireEvent.change(groupInput, { target: { value: "12" } });

    const rows = within(container).getAllByLabelText("SKU-A: годные") as HTMLInputElement[];
    expect(rows.map((input) => input.value)).toEqual(["10", "2"]);
  });

  /**
   * На телефоне подпись кнопки закреплённого действия свёрнута в пиктограмму:
   * с текстом причины недоступности рядом колонка не оставляет полосы
   * прокрутки и наезжает на закреплённый профиль (#345). Слово обязано
   * пережить сворачивание — доступное имя задаётся `aria-label`, а не только
   * написанным на кнопке текстом.
   */
  it("закреплённое действие остаётся названным словом, когда подпись свёрнута", () => {
    const row = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })]);
    const group = renderMobile(pair(), false);

    const rowButton = within(
      row.container.querySelector('tr[data-task-id="1"] td[data-sticky="actions"]') as HTMLElement,
    ).getByRole("button", { name: "Завершить" });
    const groupButton = within(
      group.container.querySelector(
        'tr[data-row-kind="board-group"] td[data-sticky="actions"]',
      ) as HTMLElement,
    ).getByRole("button", { name: "Завершить группу" });

    expect(rowButton.getAttribute("aria-label"), "имя кнопки строки").toBe("Завершить");
    expect(groupButton.getAttribute("aria-label"), "имя кнопки группы").toBe("Завершить группу");
  });

  it("тап по шеврону в профиле раскрывает группу и прячет снова", () => {
    const { container } = renderMobile(pair(), false);
    const groupRowSelector = 'tr[data-row-kind="board-group"]';
    const profile = container.querySelector(
      `${groupRowSelector} [data-sticky="profile"]`,
    ) as HTMLElement;

    // Свёрнутая группа: строк заданий нет, есть только её шапка.
    expect(container.querySelectorAll("tr[data-task-id]")).toHaveLength(0);
    fireEvent.click(within(profile).getByRole("button"));
    expect(container.querySelectorAll("tr[data-task-id]")).toHaveLength(2);
    fireEvent.click(within(profile).getByRole("button"));
    expect(container.querySelectorAll("tr[data-task-id]")).toHaveLength(0);
  });
});

describe("SectionTasksBoard: сброс фильтров в ряду фильтров", () => {
  it("на телефоне поиск и «Сбросить» доступны, сброс очищает введённое", () => {
    const { container } = renderMobile([makeTask({ id: 1, product_sku: "SKU-A" })]);
    const search = within(container).getByPlaceholderText("Поиск") as HTMLInputElement;

    // Имя точное: у скрытой на телефоне колонки сброса в шапке таблицы имя
    // «Сбросить фильтры», и подстрокой тест прошёл бы по ней, а не по ряду
    // фильтров (#341, п. 3).
    expect(within(container).getByRole("button", { name: "Сбросить" })).toBeTruthy();
    fireEvent.change(search, { target: { value: "SKU-A" } });
    expect(search.value).toBe("SKU-A");

    fireEvent.click(within(container).getByRole("button", { name: "Сбросить" }));
    expect(search.value).toBe("");
  });
});
