/**
 * Шапка таблиц деталей строки собирается из описания колонок.
 *
 * Регресс, которого стоит ждать при переносе шапки в описание: служебные
 * колонки («Детали», «Этап», числа, «%») теряются, потому что у них нет
 * `filterField`, и `map` по описанию их не рисует, — а тело таблицы их
 * по-прежнему рисует. Тогда колонки шапки разъезжаются с колонками строк
 * ровно на одну. Проверяем поэтому не только текст подписи, но и совпадение
 * числа колонок шапки и ячеек строки.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProductionPlanningStage, StatusHistoryEntry } from "@/shared/api/productionPlans";
import { TABLE_CORNER_RESET_TH_CLASS } from "@/shared/ui";

import { ExecutionEventsTable } from "./ExecutionEventsTable";
import { ExecutionStagesTable } from "./ExecutionStagesTable";

vi.mock("@/shared/api/sections", () => ({
  listSections: vi.fn().mockResolvedValue([]),
}));

const EVENT_LABELS = ["Дата", "Тип", "Событие", "Откуда", "Куда", "Кол-во", "Детали"];
const STAGE_LABELS = [
  "Этап",
  "Участок",
  "Статус этапа",
  "План",
  "Получено",
  "Годные",
  "Брак",
  "Выдано",
  "Остаток",
  "%",
];

function makeStage(overrides: Partial<ProductionPlanningStage> = {}): ProductionPlanningStage {
  return {
    flow_events: [],
    route_step_id: 1,
    section_id: 1,
    section_code: "S1",
    section_name: "Раскрой",
    section_icon: null,
    section_icon_color: null,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    planned_quantity: 10,
    completed_quantity: 0,
    transferred_quantity: 0,
    rejected_quantity: 0,
    execution_percent: 0,
    transfer_percent: 0,
    reject_percent: 0,
    task_status: "in_progress",
    not_started: false,
    issued_qty: 0,
    issued_last_at: null,
    accounted_good_qty: 0,
    accounted_reject_qty: 0,
    accounted_total_qty: 0,
    accounted_last_at: null,
    sent_qty: 0,
    sent_last_at: null,
    accepted_by_next_qty: 0,
    accepted_by_next_last_at: null,
    ...overrides,
  };
}

const STATUS_HISTORY: StatusHistoryEntry[] = [
  {
    id: 1,
    from_status: "new",
    to_status: "in_progress",
    changed_by: null,
    changed_at: "2026-01-02T10:00:00",
    reason: null,
  },
];

function renderEvents() {
  return render(
    <ExecutionEventsTable
      stages={[makeStage({ route_step_id: 2, section_name: "Сборка", sequence: 2 })]}
      statusHistory={STATUS_HISTORY}
    />,
  );
}

function renderStages() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExecutionStagesTable
        stages={[
          makeStage({ route_step_id: 2, section_name: "Сборка", sequence: 2 }),
          makeStage({ route_step_id: 1, section_name: "Раскрой", sequence: 1 }),
        ]}
      />
    </QueryClientProvider>,
  );
}

const table = () => screen.getAllByRole("table")[0];

function headerCells(): HTMLElement[] {
  return within(table().querySelector("thead")!).getAllByRole("columnheader");
}

function bodyRowCells(rowIndex: number): HTMLElement[] {
  const rows = table().querySelectorAll<HTMLElement>("tbody tr");
  return within(rows[rowIndex]!).getAllByRole("cell");
}

/** Служебный угол сброса рисуется вне описания колонок и в подписях не значим. */
const dataHeaderCells = () => headerCells().filter((cell) => !cell.className.includes(TABLE_CORNER_RESET_TH_CLASS));

const headerLabels = () => dataHeaderCells().map((cell) => cell.textContent?.replace(/Сортировка по.*/, "").trim() ?? "");

/** Строка списка значений живёт в поповере, а не в теле таблицы. */
const filterOption = (value: string) => within(screen.getByRole("dialog")).getByText(value);

const rowTexts = (rowIndex: number) => bodyRowCells(rowIndex).map((cell) => cell.textContent?.trim() ?? "");

function columnHeader(label: string): HTMLElement {
  const cell = dataHeaderCells().find((candidate) => candidate.textContent?.startsWith(label));
  if (!cell) throw new Error(`Не найдена ячейка шапки «${label}»`);
  return cell;
}

/** Кнопка с подписью колонки открывает поповер фильтра; рядом стоит кнопка сортировки. */
const filterTrigger = (label: string) => within(columnHeader(label)).getByRole("button", { name: label });

describe("ExecutionEventsTable: шапка из описания колонок", () => {
  it("рисует столько же колонок, сколько ячеек в строке", () => {
    renderEvents();
    // Служебная «Детали» объявлена в описании без `filterField`: потеряв её
    // в `map`, шапка стала бы на колонку уже тела.
    expect(headerLabels()).toHaveLength(rowTexts(0).length - 1);
  });

  it("сохраняет порядок и подписи колонок журнала", () => {
    renderEvents();
    expect(headerLabels()).toEqual(EVENT_LABELS);
  });

  it("фильтрует строки по выбранному значению колонки", () => {
    renderEvents();

    fireEvent.click(filterTrigger("Тип"));
    fireEvent.click(filterOption("Статус"));

    expect(table().querySelectorAll("tbody tr")).toHaveLength(1);
    // Осталась строка события со сменой статуса, а не событие маршрута.
    expect(rowTexts(0)[1]).toBe("Статус");
  });
});

describe("ExecutionStagesTable: шапка из описания колонок", () => {
  it("рисует столько же колонок, сколько ячеек в строке", () => {
    renderStages();
    // Девять числовых колонок и «Этап» объявлены без `filterField`; потеря
    // любой из них в `map` съехала бы шапку влево относительно тела.
    expect(headerLabels()).toHaveLength(rowTexts(0).length - 1);
  });

  it("сохраняет порядок и подписи колонок этапов", () => {
    renderStages();
    expect(headerLabels()).toEqual(STAGE_LABELS);
  });

  it("переставляет строки по возрастанию участка", () => {
    renderStages();
    // Исходный порядок — порядок этапов маршрута, а не алфавитный.
    expect(rowTexts(0)[1]).toBe("Сборка");

    const sortButton = within(columnHeader("Участок")).getByRole("button", { name: /Участок, сортировка/ });
    fireEvent.click(sortButton);
    fireEvent.click(sortButton);

    expect(rowTexts(0)[1]).toBe("Раскрой");
  });

  it("фильтрует строки по выбранному значению колонки", () => {
    renderStages();

    fireEvent.click(filterTrigger("Участок"));
    fireEvent.click(filterOption("Раскрой"));

    expect(table().querySelectorAll("tbody tr")).toHaveLength(1);
    expect(rowTexts(0)[1]).toBe("Раскрой");
  });

  it("не рисует сортировку у числовой колонки, которой нечем сортировать", () => {
    renderStages();
    for (const label of ["План", "Получено", "Годные", "Брак", "Выдано", "Остаток", "%", "Этап"]) {
      expect(
        within(columnHeader(label)).queryByRole("button", { name: /, сортировка/ }),
        `у колонки «${label}» не должно быть кнопки сортировки`,
      ).toBeNull();
    }
  });
});
