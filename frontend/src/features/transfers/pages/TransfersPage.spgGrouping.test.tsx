/**
 * «Все ГХП»: строки раскладываются блоками по ГХП.
 *
 * Регресс: сервер сортирует ready по `sequence` маршрута, и строки разных ГХП
 * шли вперемешку — одинаковые этапы рядом, хотя группы разные. Тест смотрит на
 * порядок отрисованных строк: шапка ГХП, строки только этого ГХП, следующая
 * шапка — и так до конца.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
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

import { getSpgList, type SpgOut, type SpgSectionOut } from "@/shared/api/spg";
import {
  listReadyToTransfer,
  listTransferHistory,
  type ReadyToTransferListParams,
  type ReadyToTransferTask,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { TransfersPage } from "./TransfersPage";

function makeSection(sectionId: number, sectionCode: string, sectionName: string): SpgSectionOut {
  return {
    section_id: sectionId,
    section_code: sectionCode,
    section_name: sectionName,
    sort_order: sectionId * 10,
    type: "production",
    icon: null,
    icon_color: null,
  };
}

function makeSpg(
  id: number,
  name: string,
  sections: SpgSectionOut[],
  iconColor: string | null = null,
): SpgOut {
  return {
    id,
    code: `GP${id}`,
    name,
    description: null,
    sort_order: id * 10,
    is_active: true,
    icon: null,
    icon_color: iconColor,
    sections,
  };
}

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

/**
 * Сервер отдаёт строки вперемешку: этап у всех первый, поэтому ГХП чередуются.
 * Внутри ГХП артикулы разные — каждая строка остаётся одиночной, и порядок
 * задаёт только раскладка по ГХП и количеству.
 */
const interleavedTasks: ReadyToTransferTask[] = [
  makeTask({ task_id: 1, plan_position_id: 10, section_id: 5, product_sku: "ББ-2", transferable_quantity: "30" }),
  makeTask({ task_id: 2, plan_position_id: 20, section_id: 1, product_sku: "АА-1", transferable_quantity: "10" }),
  makeTask({ task_id: 3, plan_position_id: 30, section_id: 5, product_sku: "ГГ-4", transferable_quantity: "20" }),
  makeTask({ task_id: 4, plan_position_id: 40, section_id: 1, product_sku: "ВВ-3", transferable_quantity: "5" }),
];

function serverSort(tasks: ReadyToTransferTask[], params: ReadyToTransferListParams): ReadyToTransferTask[] {
  const sort = params.sort;
  if (!sort?.startsWith("plan_position_id:")) return tasks;
  const direction = sort.endsWith(":asc") ? 1 : -1;
  return [...tasks].sort((a, b) => (a.plan_position_id - b.plan_position_id) * direction);
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

/** Типы отрисованных строк ready-таблицы в порядке появления. */
function renderedRowKinds(): Array<string | null> {
  return [...document.querySelectorAll("tbody tr[data-row-kind]")].map((row) =>
    row.getAttribute("data-row-kind"),
  );
}

/** Артикулы строк заданий в порядке отрисовки. */
function renderedSkuOrder(): string[] {
  return [...document.querySelectorAll('tbody tr[data-row-kind="ready-task"]')].map(
    (row) => (row.querySelectorAll("td")[1]?.textContent ?? "").trim(),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([
    makeSpg(
      1,
      "ГХП №1",
      [makeSection(1, "SAW", "Пила"), makeSection(2, "PRESS", "Пресс")],
      "#06B6D4",
    ),
    makeSpg(
      2,
      "ГХП №2",
      [makeSection(5, "ANODE", "Анод"), makeSection(6, "PACK", "Упаковка")],
      "#10B981",
    ),
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
    const items = serverSort(interleavedTasks, params);
    return {
      items,
      total: items.length,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      filters: { section_id: null, spg_id: null },
    };
  });
});

describe("TransfersPage: раскладка «Готово к передаче» по ГХП", () => {
  it("на «Все ГХП» строки идут блоками по ГХП, а не вперемешку", async () => {
    renderPage();

    await waitFor(() => {
      expect(document.querySelectorAll("tbody tr[data-row-kind]").length).toBe(6);
    });

    // Две шапки ГХП и по две строки под каждой — группы не пересекаются.
    expect(renderedRowKinds()).toEqual([
      "ready-spg",
      "ready-task",
      "ready-task",
      "ready-spg",
      "ready-task",
      "ready-task",
    ]);
    const headers = [...document.querySelectorAll('tr[data-row-kind="ready-spg"]')].map(
      (row) => (row.textContent ?? "").trim(),
    );
    expect(headers).toEqual(["ГХП №1", "ГХП №2"]);

    // Цвет шапки — справочный `icon_color`, а не позиция в палитре:
    // «Анодирование» светло-голубое и не должно зеленеть.
    const headerRails = [...document.querySelectorAll<HTMLTableCellElement>('tr[data-row-kind="ready-spg"] td')].map(
      (cell) => cell.style.borderLeft.toLowerCase(),
    );
    expect(headerRails).toEqual(["4px solid #06b6d4", "4px solid #10b981"]);

    // Внутри ГХП — прежний порядок по количеству; ГХП идут по справочнику.
    expect(renderedSkuOrder()).toEqual(["АА-1", "ВВ-3", "ББ-2", "ГГ-4"]);
  });

  it("сортировка по колонке рисует строки сервера как есть, без шапок ГХП", async () => {
    renderPage();
    await waitFor(() => {
      expect(document.querySelectorAll("tbody tr[data-row-kind]").length).toBe(6);
    });

    const button = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>('button[data-sort-field="positionId"]');
      if (!found) throw new Error("нет кнопки сортировки «ID»");
      return found;
    });
    await act(async () => {
      fireEvent.click(button);
    });

    await waitFor(() => {
      expect(document.querySelectorAll('tr[data-row-kind="ready-spg"]').length).toBe(0);
    });
    // Порядок задаёт сервер: ID убыв. (40 → 10), без перегруппировки по ГХП.
    expect(renderedSkuOrder()).toEqual(["ВВ-3", "ГГ-4", "АА-1", "ББ-2"]);
  });
});
