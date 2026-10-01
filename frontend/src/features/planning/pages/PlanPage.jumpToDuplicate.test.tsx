/**
 * Переход к позиции по дублю в колонке «Дубликат» (#270).
 *
 * Клик по «#id» раньше искал цель только в текущем списке (текущий фильтр и
 * текущая страница) и перефильтровывал таблицу молча, если цели там нет.
 * Вариант 2: цель догружается по точному id (`allPlanPositions({ plan_position_id })`),
 * карточка открывается независимо от фильтра и страницы, а пустой ответ даёт
 * тост. Скролл — после отрисовки строки, а не по `setTimeout(0)`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
  getErrorMessage: (e: unknown) => String(e),
}));

vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  listPlans: vi.fn(),
  allPlanPositions: vi.fn(),
  getPlanDuplicates: vi.fn(),
}));

vi.mock("@/shared/api/routes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/routes")>()),
  listRoutes: vi.fn(),
}));

vi.mock("@/shared/api/importTemplates", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/importTemplates")>()),
  listAllImportTemplates: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/ui/use-toast")>()),
  toast: vi.fn(),
}));

import { listAllImportTemplates } from "@/shared/api/importTemplates";
import {
  allPlanPositions,
  getPlanDuplicates,
  listPlans,
  type PlanPositionOut,
} from "@/shared/api/productionPlans";
import { listRoutes } from "@/shared/api/routes";
import { toast } from "@/shared/ui/use-toast";
import { PlanPage } from "./PlanPage";

const PLAN_ID = 1;

function position(overrides: Partial<PlanPositionOut>): PlanPositionOut {
  return {
    id: 5633,
    production_plan_id: PLAN_ID,
    source_sku: "ЮП-460",
    source_name: "Профиль ЮП-460",
    quantity: "100",
    status: "draft",
    validation_status: "valid",
    errors: [],
    warnings: [],
    source_row_number: 5,
    product_id: 10,
    route_id: null,
    route_profile_id: null,
    route_name: null,
    route_source: null,
    route_origin: null,
    route_match_quality: null,
    route_match_reason: null,
    route_assigned_at: null,
    route_manual_confirmed_at: null,
    route_error: null,
    raw_excel_row: null,
    ...overrides,
  };
}

function page(rows: PlanPositionOut[]) {
  return { positions: rows, total: rows.length, limit: 50, offset: 0 };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/plans"]}>
        <PlanPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(listPlans).mockResolvedValue([
    {
      id: PLAN_ID,
      plan_no: "PLAN-1",
      name: "План",
      status: "draft",
      total_positions: 2,
      draft_positions: 2,
      approved_positions: 0,
      released_positions: 0,
      created_at: "2026-05-01T00:00:00Z",
    },
  ]);
  vi.mocked(listRoutes).mockResolvedValue([]);
  vi.mocked(listAllImportTemplates).mockResolvedValue([]);
  // Позиции 1 и 2 — дубликат друг друга: у строки 1 появляется ссылка «#2».
  vi.mocked(getPlanDuplicates).mockResolvedValue([
    {
      source_fingerprint: "fp-1",
      positions: [
        { id: 1, source_sku: "A", source_name: "A", quantity: "1", source_row_number: 1, status: "draft", validation_errors: [] },
        { id: 2, source_sku: "B", source_name: "B", quantity: "1", source_row_number: 2, status: "draft", validation_errors: [] },
      ],
    },
  ]);
});

describe("PlanPage: переход к позиции по дублю", () => {
  it("догружает цель по id, если её нет на текущей странице, и открывает карточку", async () => {
    vi.mocked(allPlanPositions).mockImplementation(async (params = {}) =>
      params.plan_position_id === 2
        ? page([position({ id: 2, source_sku: "TARGET-2" })])
        : page([position({ id: 1 })]),
    );

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "#2" }));

    await waitFor(() =>
      expect(allPlanPositions).toHaveBeenCalledWith(
        expect.objectContaining({ plan_position_id: 2 }),
      ),
    );
    expect(await screen.findByText(/Позиция плана #2/)).toBeTruthy();
  });

  it("пустой ответ догрузки — тост «позиция не найдена», а не тишина", async () => {
    vi.mocked(allPlanPositions).mockImplementation(async (params = {}) =>
      params.plan_position_id === 2 ? page([]) : page([position({ id: 1 })]),
    );

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "#2" }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Позиция не найдена" }),
      ),
    );
    expect(screen.queryByText(/Позиция плана #2/)).toBeNull();
  });

  it("когда строка цели на текущей странице — прокручивает к ней", async () => {
    vi.mocked(allPlanPositions).mockImplementation(async () =>
      page([position({ id: 1 }), position({ id: 2, source_sku: "TARGET-2" })]),
    );

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "#2" }));

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
    // Догрузка не понадобилась: цель уже в списке.
    expect(allPlanPositions).not.toHaveBeenCalledWith(
      expect.objectContaining({ plan_position_id: 2 }),
    );
  });
});
