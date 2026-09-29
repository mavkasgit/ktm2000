/**
 * Колонка «Следующий» таблицы «Готово к передаче» — одна строка по-русски.
 *
 * Регресс: ячейка печатала адресата двумя строками — операция и отдельно
 * `КОД_УЧАСТКА #N` (`next_section_code` + `next_step_sequence`). Оператору нужен
 * адрес, а не идентификатор маршрута, поэтому в ячейке остаётся только
 * `nextStepLabel(операция, участок)`: операция приоритетнее названия участка
 * («Хранение: Склад готовой продукции»), а у складских этапов операций нет —
 * там подписью остаётся название участка.
 *
 * Проверяем текст ОТРИСОВАННОЙ ячейки: он и есть контракт для оператора.
 * Позиция ячейки берётся из шапки по подписи «Следующий», а не зашитым
 * индексом — иначе тест проверял бы вёрстку, а не подпись.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
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
  type ReadyToTransferTask,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { TransfersPage } from "./TransfersPage";

/** Адресат передачи: склад с кодом участка и номером этапа — их в ячейке быть не должно. */
const NEXT_SECTION_CODE = "FINISHED_STOCK";
const NEXT_SECTION_NAME = "Склад готовой продукции";
const NEXT_STEP_SEQUENCE = 2;
const NEXT_OPERATION_NAME = "Хранение: Склад готовой продукции";

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
    next_section_id: 9,
    next_section_code: NEXT_SECTION_CODE,
    next_section_name: NEXT_SECTION_NAME,
    next_operation_name: NEXT_OPERATION_NAME,
    next_step_sequence: NEXT_STEP_SEQUENCE,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

/** Ответ сервера: одна выборка ready, без серверной сортировки. */
function mockReadyItems(items: ReadyToTransferTask[]) {
  vi.mocked(listReadyToTransfer).mockImplementation(async (params = {}) => ({
    items,
    total: items.length,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
    filters: { section_id: null, spg_id: null },
  }));
}

/** Индекс колонки «Следующий» в строке: подпись ищется в шапке, а не зашивается. */
function nextColumnIndex(): number {
  const headers = [...document.querySelectorAll("thead th")];
  const index = headers.findIndex((th) => (th.textContent ?? "").trim() === "Следующий");
  expect(index, "в шапке ready-таблицы нет колонки «Следующий»").toBeGreaterThanOrEqual(0);
  return index;
}

/** Подписи колонки «Следующий» отрисованных строк готовых передач. */
function renderedNextLabels(kind: "ready-task" | "ready-group"): string[] {
  const index = nextColumnIndex();
  return [...document.querySelectorAll(`tbody tr[data-row-kind="${kind}"]`)].map(
    (row) => (row.querySelectorAll("td")[index]?.textContent ?? "").trim(),
  );
}

async function waitForReadyRows(kind: "ready-task" | "ready-group", count: number) {
  await waitFor(() => {
    expect(document.querySelectorAll(`tbody tr[data-row-kind="${kind}"]`).length).toBe(count);
  });
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
});

describe("TransfersPage: колонка «Следующий»", () => {
  it.each<
    [string, Pick<ReadyToTransferTask, "next_operation_name" | "next_section_name">, string]
  >([
    [
      "операция есть — печатается только она",
      { next_operation_name: NEXT_OPERATION_NAME, next_section_name: NEXT_SECTION_NAME },
      NEXT_OPERATION_NAME,
    ],
    [
      "операции нет (складской этап) — печатается название участка",
      { next_operation_name: null, next_section_name: "Склад полуфабриката" },
      "Склад полуфабриката",
    ],
    [
      "ни операции, ни участка — печатается прочерк",
      { next_operation_name: null, next_section_name: null },
      "—",
    ],
  ])("в строке задания %s", async (_case, next, expected) => {
    // Один размер — иначе строки разошлись бы по группам, а не по строкам заданий.
    mockReadyItems([makeTask(next)]);

    renderPage();
    await waitForReadyRows("ready-task", 1);

    const [label] = renderedNextLabels("ready-task");
    // Точное равенство, а не «содержит»: код участка `FINISHED_STOCK` и номер
    // этапа `#2` в подписи быть не должны.
    expect(label).toBe(expected);
    expect(label).not.toContain(NEXT_SECTION_CODE);
    expect(label).not.toContain(`#${NEXT_STEP_SEQUENCE}`);
  });

  it("в строке-заголовке группы подпись общая на всю группу", async () => {
    // Три строки одного артикула/участка/размера/адресата — они сворачиваются
    // в группу, и ячейку «Следующий» рисует уже строка-заголовок.
    mockReadyItems(
      [1, 2, 3].map((taskId) =>
        makeTask({
          task_id: taskId,
          plan_position_id: taskId,
          transferable_quantity: "10",
          next_operation_name: NEXT_OPERATION_NAME,
        }),
      ),
    );

    renderPage();
    await waitForReadyRows("ready-group", 1);

    const [label] = renderedNextLabels("ready-group");
    expect(label).toBe(NEXT_OPERATION_NAME);
    expect(label).not.toContain(NEXT_SECTION_CODE);
    expect(label).not.toContain(`#${NEXT_STEP_SEQUENCE}`);
  });

  it("в строке-заголовке группы складского этапа печатается название участка", async () => {
    // Общий `next_operation_name` у строк группы — `null`: складских операций
    // в маршруте нет, и приоритет операции оставляет только название участка.
    mockReadyItems(
      [1, 2].map((taskId) =>
        makeTask({
          task_id: taskId,
          plan_position_id: taskId,
          transferable_quantity: "10",
          next_operation_name: null,
          next_section_name: "Склад полуфабриката",
        }),
      ),
    );

    renderPage();
    await waitForReadyRows("ready-group", 1);

    expect(renderedNextLabels("ready-group")).toEqual(["Склад полуфабриката"]);
  });
});
