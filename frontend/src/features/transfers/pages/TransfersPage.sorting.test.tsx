/**
 * Порядок строк таблицы «Готово к передаче» при выбранной сортировке колонки.
 *
 * Регресс: ready-таблица рисует свёрнутые группы (`groupReadyTransfers`), а в
 * шапке группы печатается общий этап и СУММА «К передаче», а порядок групп —
 * порядок первого появления строки. Серверная сортировка по plan_position_id /
 * operation_name / transferable_qty до оператора не доходила: строки склеивались
 * обратно, и по напечатанным в ячейках значениям порядок не соответствовал.
 *
 * Тест смотрит на текст ячеек отрендеренных строк, а не на внутренние структуры.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  listReadyToTransfer: vi.fn(),
  listTransferHistory: vi.fn(),
}));

vi.mock("@/shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

import { getSpgList } from "@/shared/api/spg";
import {
  listReadyToTransfer,
  listTransferHistory,
  type IncomingTransfer,
  type ReadyToTransferListParams,
  type ReadyToTransferTask,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { TransfersPage } from "./TransfersPage";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: "010",
    operation_name: "Пила",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "100",
    completed_quantity: "100",
    already_transferred_quantity: "0",
    transferable_quantity: "100",
    has_next_step: true,
    next_section_id: 4,
    next_section_code: "SHOT_BLAST",
    next_section_name: "Дробеструй",
    next_operation_name: "Дробеструй",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

function makeHistoryTransfer(overrides: Partial<IncomingTransfer> = {}): IncomingTransfer {
  return {
    transfer_id: 1,
    transfer_no: "TR-1",
    status: "accepted",
    from_task_id: 1,
    to_task_id: 2,
    from_section_id: 1,
    from_section_code: "SAW",
    from_section_name: "Пила",
    to_section_id: 4,
    to_section_code: "SHOT_BLAST",
    to_section_name: "Дробеструй",
    from_operation_name: "Пила",
    to_operation_name: "Дробеструй",
    sent_quantity: "10",
    accepted_quantity: "10",
    rejected_quantity: "0",
    remaining_quantity: "0",
    comment: null,
    sent_at: "2026-09-01T10:00:00Z",
    created_at: "2026-09-01T10:00:00Z",
    is_post_factum: false,
    physical_handover_at: null,
    from_task_status: "in_progress",
    to_task_status: "pending",
    product_sku: "ЮП-2083",
    from_line_id: 1,
    from_line_sequence: 1,
    plan_position_id: 1,
    dimensions: null,
    ...overrides,
  };
}

/** Три задания одного артикула/участка/размера/адресата — они сворачиваются в группу. */
function makeGroupableTasks(): ReadyToTransferTask[] {
  return [
    makeTask({ task_id: 1, plan_position_id: 7, transferable_quantity: "30", operation_name: "Пила" }),
    makeTask({ task_id: 2, plan_position_id: 3, transferable_quantity: "70", operation_name: "Пила" }),
    makeTask({ task_id: 3, plan_position_id: 5, transferable_quantity: "50", operation_name: "Пила" }),
  ];
}

/**
 * Серверная сортировка ready: разбор строки `sort` (`field:order,...`) и тот
 * же порядок, что отдаёт бэкенд. Приоритеты применяются слева направо.
 */
function serverSort(items: ReadyToTransferTask[], params: ReadyToTransferListParams = {}): ReadyToTransferTask[] {
  const clauses = (params.sort ?? "sequence:asc").split(",").map((part) => {
    const [field, order] = part.split(":");
    return { field: field ?? "sequence", order: order === "asc" ? 1 : -1 };
  });
  const key = (task: ReadyToTransferTask, field: string): number | string => {
    switch (field) {
      case "plan_position_id":
        return task.plan_position_id;
      case "transferable_qty":
        return parseFloat(task.transferable_quantity);
      case "operation_name":
        return task.operation_name ?? "";
      case "product_sku":
        return task.product_sku ?? "";
      default:
        return task.sequence;
    }
  };
  return [...items].sort((a, b) => {
    for (const { field, order } of clauses) {
      const ka = key(a, field);
      const kb = key(b, field);
      if (ka === kb) continue;
      return ka < kb ? -order : order;
    }
    return a.task_id - b.task_id;
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([
    {
      id: 1,
      code: "GP1",
      name: "ГХП №1",
      description: null,
      sort_order: 10,
      is_active: true,
      icon: null,
      icon_color: null,
      sections: [
        {
          section_id: 1,
          section_code: "SAW",
          section_name: "Пила",
          sort_order: 10,
          type: "production",
          icon: null,
          icon_color: null,
        },
      ],
    },
  ]);
  vi.mocked(listTransferHistory).mockResolvedValue({
    section_id: null,
    spg_id: null,
    transfers: [],
    total: 0,
    limit: 50,
    offset: 0,
  } satisfies TransferHistoryResponse);
  vi.mocked(listReadyToTransfer).mockImplementation(async (params = {}) => {
    const items = serverSort(makeGroupableTasks(), params);
    return {
      items,
      total: items.length,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      filters: { section_id: null, spg_id: null },
    };
  });
});

/**
 * Кнопка сортировки колонки: доступное имя собирается из подписи колонки
 * (#204), поэтому тест адресует кнопку по машинному полю в `data-sort-field`.
 */
function sortButton(field: string): HTMLElement {
  const button = document.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
  if (!button) throw new Error(`Не найдена кнопка сортировки колонки «${field}»`);
  return button;
}

/**
 * Клик по кнопке сортировки колонки ready-таблицы. Между кликами таблица
 * перезапрашивается, поэтому ждём возврата шапки.
 */
async function clickReadySort(field: string) {
  const button = await waitFor(() => sortButton(field));
  await act(async () => {
    fireEvent.click(button);
  });
}

/** Строки ready-таблицы в порядке отрисовки: [значение ячейки ID, значение «К передаче»]. */
function renderedReadyRows(): Array<{ id: string; qty: string }> {
  return [...document.querySelectorAll('tbody tr[data-row-kind="ready-task"]')].map((row) => {
    const cells = row.querySelectorAll("td");
    const qtyText = cells[4]?.textContent ?? "";
    return {
      id: (cells[0]?.textContent ?? "").trim(),
      qty: qtyText.split("шт.")[0]?.trim() ?? "",
    };
  });
}

/** Значения «К передаче» ready-таблицы в порядке строк (группы и одиночные). */
function renderedReadyQtyOrder(): string[] {
  return [...document.querySelectorAll("tbody tr[data-row-kind]")].map(
    (row) => (row.querySelectorAll("td")[4]?.textContent ?? "").split("шт.")[0]?.trim() ?? "",
  );
}

/** Ждём отрисовки ready-таблицы: есть либо группа, либо строки заданий. */
async function waitForReadyTable() {
  await waitFor(() => {
    expect(document.querySelectorAll("tbody tr[data-row-kind]").length).toBeGreaterThan(0);
  });
}

/** Ждём ровно `count` отрисованных строк заданий ready-таблицы. */
async function waitForReadyTaskRows(count: number) {
  await waitFor(() => {
    expect(document.querySelectorAll('tbody tr[data-row-kind="ready-task"]').length).toBe(count);
  });
}

describe("TransfersPage: сортировка таблицы «Готово к передаче»", () => {
  it("без сортировки сворачивает строки одного артикула в группу с суммой", async () => {
    renderPage();
    await waitForReadyTable();

    // Свёрнутая группа: шапка с суммой 30+70+50 = 150 и ни одной строки задания.
    expect(renderedReadyQtyOrder()).toEqual(["150"]);
    expect(document.querySelectorAll('tr[data-row-kind="ready-group"]').length).toBe(1);
  });

  it("сортировка по ID упорядочивает строки заданий, а не группы", async () => {
    renderPage();
    await waitForReadyTable();

    await clickReadySort("positionId"); // убыв.

    // Сервер отдал 7 → 5 → 3; без сортировки все три строки были бы одной группой.
    await waitForReadyTaskRows(3);
    expect(renderedReadyRows().map((row) => row.id)).toEqual(["#7", "#5", "#3"]);

    await clickReadySort("positionId"); // возрастание
    await waitForReadyTaskRows(3);
    expect(renderedReadyRows().map((row) => row.id)).toEqual(["#3", "#5", "#7"]);
  });

  it("сортировка по «К передаче» показывает построчные количества, а не сумму группы", async () => {
    renderPage();
    await waitForReadyTable();

    await clickReadySort("transferableQty"); // убыв. → 70, 50, 30

    await waitForReadyTaskRows(3);
    expect(renderedReadyRows().map((row) => row.qty)).toEqual(["70", "50", "30"]);
    // Строк-заданий ровно три — ни одна не спрятана в свёрнутую группу.
    expect(document.querySelectorAll('tr[data-row-kind="ready-group"]').length).toBe(0);
  });

  it("снятие сортировки возвращает свёрнутые группы", async () => {
    renderPage();
    await waitForReadyTable();

    await clickReadySort("positionId");
    await waitForReadyTaskRows(3);
    await clickReadySort("positionId"); // возрастание
    await clickReadySort("positionId"); // снять

    await waitFor(() => {
      expect(document.querySelectorAll('tr[data-row-kind="ready-group"]').length).toBe(1);
    });
    expect(renderedReadyQtyOrder()).toEqual(["150"]);
  });

  it("сортировка по «Этап» упорядочивает строки заданий", async () => {
    vi.mocked(listReadyToTransfer).mockImplementation(async (params = {}) => {
      const items = serverSort(
        [
          makeTask({ task_id: 1, plan_position_id: 7, operation_name: "Анодирование" }),
          makeTask({ task_id: 2, plan_position_id: 3, operation_name: "Дробеструй" }),
          makeTask({ task_id: 3, plan_position_id: 5, operation_name: "Пила" }),
        ],
        params,
      );
      return {
        items,
        total: items.length,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
        filters: { section_id: null, spg_id: null },
      };
    });

    renderPage();
    await waitForReadyTable();

    await clickReadySort("stage"); // убыв. по имени этапа: Пила → Дробеструй → Анодирование

    await waitForReadyTaskRows(3);
    const stageColumn = [...document.querySelectorAll('tbody tr[data-row-kind="ready-task"]')].map(
      (row) => (row.querySelectorAll("td")[3]?.textContent ?? "").split("#")[0]?.trim() ?? "",
    );
    expect(stageColumn).toEqual(["Пила", "Дробеструй", "Анодирование"]);
  });

  it("сортировка журнала передач по количеству не затрагивается", async () => {
    vi.mocked(listTransferHistory).mockImplementation(async (params = {}) => {
      const transfers = [
        makeHistoryTransfer({ transfer_id: 1, transfer_no: "TR-1", sent_quantity: "15" }),
        makeHistoryTransfer({ transfer_id: 2, transfer_no: "TR-2", sent_quantity: "40" }),
        makeHistoryTransfer({ transfer_id: 3, transfer_no: "TR-3", sent_quantity: "25" }),
      ];
      const direction = (params.sort ?? "created_at:desc").endsWith(":asc") ? 1 : -1;
      const sorted = [...transfers].sort(
        (a, b) => (parseFloat(a.sent_quantity) - parseFloat(b.sent_quantity)) * direction,
      );
      return {
        section_id: null,
        spg_id: null,
        transfers: sorted,
        total: sorted.length,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      };
    });

    renderPage();
    fireEvent.click(await screen.findByTitle("Открыть журнал передач"));

    const header = await waitFor(() => sortButton("quantity"));
    await act(async () => {
      fireEvent.click(header);
    });

    await waitFor(() => {
      expect(listTransferHistory).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "quantity:desc" }),
      );
    });
    // Журнал рисует строки передач как есть — порядок сервера доходит до ячеек.
    const journalRows = [...document.querySelectorAll('[role="dialog"] tbody tr')].map(
      (row) => (row.querySelectorAll("td")[5]?.textContent ?? "").trim(),
    );
    expect(journalRows).toEqual(["40", "25", "15"]);
  });

  it("в запрос уходят оба выбранных приоритета в порядке выбора", async () => {
    renderPage();
    await waitForReadyTable();

    await clickReadySort("positionId"); // приоритет 1: plan_position_id:desc
    await clickReadySort("transferableQty"); // приоритет 2: transferable_qty:desc

    // Регресс: раньше на сервер уходил только sortConfigs[0], а шапка второй
    // колонки уже показывала бейдж «2» — оператор кликал и не видел эффекта.
    await waitFor(() => {
      expect(listReadyToTransfer).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "plan_position_id:desc,transferable_qty:desc" }),
      );
    });
  });
});

/**
 * Идентичность строк ready-таблицы: пара «задание × размер», а не task_id.
 *
 * Трансформирующая задача (#91, резка) отдаёт по строке на КАЖДЫЙ выход
 * спецификации: task_id у всех выходов ОДИН И ТОТ ЖЕ, различаются только
 * dimensions. Единица передачи — именно эта пара (см. `groupReadyTransfers`),
 * поэтому task_id как React-ключ не годится: строки одного задания делят
 * ключ, React переиспользует узлы и в DOM оказывается больше <tr>, чем
 * строк отдала страница (оператор видит дубли, E2E падает в strict mode).
 *
 * Проверяем ровно этот контраст: сколько строк пришло из данных — столько
 * оказалось в DOM, и у каждой свой `data-row-key`.
 */
describe("TransfersPage: идентичность строк ready-таблицы", () => {
  it("выходы одной трансформирующей задачи не дублируются в DOM", async () => {
    // Три выхода резки одного задания (task_id 1) плюс обычная строка (task_id 2).
    // Размер входит в ключ группировки, поэтому строки одного задания с
    // разными размерами не схлопываются в группу-заголовок.
    const full = [900, 1350, 1800].map((lengthMm) =>
      makeTask({
        task_id: 1,
        plan_position_id: 7,
        operation_name: "Резка",
        dimensions: { length_mm: lengthMm },
        dimensions_label: `${lengthMm / 1000} м`,
        transferable_quantity: "30",
      }),
    );
    const plain = makeTask({
      task_id: 2,
      plan_position_id: 3,
      operation_name: "Пила",
      dimensions: { length_mm: 2200 },
      dimensions_label: "2,2 м",
      transferable_quantity: "40",
    });
    const all = [...full, plain];

    // Ответ сервера меняется: задание могли частично передать, и следующая
    // выборка уже короче. Смена набора — обычное дело, дублирующийся ключ
    // проявляется именно на ней: React не может отличить одну строку от
    // другой и оставляет в DOM лишний <tr>.
    let items = all;
    let calls = 0;
    vi.mocked(listReadyToTransfer).mockImplementation(async () => {
      calls += 1;
      return {
        items: serverSort(items, { sort: "plan_position_id:desc" }),
        total: items.length,
        limit: 50,
        offset: 0,
        filters: { section_id: null, spg_id: null },
      };
    });

    renderPage();
    await waitForReadyTaskRows(all.length);

    items = [full[1], plain];
    await clickReadySort("positionId");
    await waitFor(() => {
      expect(calls).toBeGreaterThan(1);
    });

    // Столько строк отдал сервер — столько и осталось в DOM, и ключи у них
    // попарно различны: с `key={task_id}` здесь оставалось три <tr>, два из
    // которых были копиями одной строки 1350 мм.
    await waitFor(() => {
      expect(document.querySelectorAll('tr[data-row-kind="ready-task"]').length).toBe(items.length);
    });
    const keys = [...document.querySelectorAll('tr[data-row-kind="ready-task"]')].map((row) =>
      row.getAttribute("data-row-key"),
    );
    expect(new Set(keys).size).toBe(items.length);
  });
});
