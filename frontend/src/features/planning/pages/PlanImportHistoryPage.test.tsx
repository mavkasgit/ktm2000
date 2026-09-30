// Страница «История импортов плана» (ADR-0054). Проверяем то, что появилось
// именно переносом таблицы файлов на отдельный экран: список кросс-плановый, а
// LIFO-гейт отката остался внутри плана. Глобальный «последний применённый»
// погасил бы откат у всех планов, кроме одного, — это и есть дефект, который
// такая страница вносит молча, если считать «последний» по всему списку.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  allPlanFiles: vi.fn(),
  hideImportBatch: vi.fn(),
  listPlans: vi.fn(),
}));

// Кнопка «Убрать из списка» рисуется по роли (ADR-0057), поэтому роль в тестах
// задаёт мок `useAuth` — так же, как на странице истории остатков.
vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));


import {
  allPlanFiles,
  hideImportBatch,
  listPlans,
  type PlanFileInfo,
  type PlanSummary,
} from "@/shared/api/productionPlans";
import { PlanImportHistoryPage } from "./PlanImportHistoryPage";
import { useAuth } from "@/features/auth/hooks/useAuth";
import type { AuthShellUser } from "@/features/auth/hooks/useAuth";

const asRole = (role: string) => {
  const user: AuthShellUser = { username: "u", full_name: "U", role };
  vi.mocked(useAuth).mockReturnValue({
    user,
    rolesCatalog: [],
    roleLabel: (r: string) => r,
    roleSections: () => [],
    isAuthenticated: true,
    isLoading: false,
    loginWithToken: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  });
};

function planFile(overrides: Partial<PlanFileInfo> = {}): PlanFileInfo {
  return {
    batch_id: 1,
    file_id: 1,
    production_plan_id: 1,
    change_set_id: 10,
    filename: "Упаковочный план.xlsx",
    extension: "xlsx",
    size_bytes: 1024,
    sheet_name: "totalplan",
    total_rows: 55,
    parsed_rows: 55,
    status: "parsed",
    created_at: "2026-09-01T10:00:00Z",
    applied_at: null,
    hidden: false,
    ...overrides,
  };
}

function plan(overrides: Partial<PlanSummary> = {}): PlanSummary {
  return {
    id: 1,
    plan_no: "ПЛ-1",
    name: "Сентябрь",
    status: "approved",
    total_positions: 55,
    draft_positions: 0,
    approved_positions: 55,
    released_positions: 0,
    created_at: "2026-09-01T09:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <PlanImportHistoryPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("PlanImportHistoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // По умолчанию — admin: у него видна кнопка «Убрать из списка», и кейсы
    // про LIFO/подписи плана не зависят от роли.
    asRole("admin");
  });

  it("показывает батчи всех планов, а не только первого", async () => {
    vi.mocked(listPlans).mockResolvedValue([
      plan(),
      plan({ id: 2, plan_no: "ПЛ-2", name: "Октябрь" }),
    ]);
    vi.mocked(allPlanFiles).mockResolvedValue([
      planFile({ batch_id: 5, filename: "сентябрь.xlsx" }),
      planFile({ batch_id: 6, production_plan_id: 2, filename: "октябрь.xlsx" }),
    ]);

    renderPage();

    expect(await screen.findByText("сентябрь.xlsx")).toBeTruthy();
    expect(screen.getByText("октябрь.xlsx")).toBeTruthy();
    expect(screen.getByText("ПЛ-1 · Сентябрь")).toBeTruthy();
    expect(screen.getByText("ПЛ-2 · Октябрь")).toBeTruthy();
  });

  it("гасит откат только у не-последнего батча своего плана", async () => {
    vi.mocked(listPlans).mockResolvedValue([
      plan(),
      plan({ id: 2, plan_no: "ПЛ-2", name: "Октябрь" }),
    ]);
    // В первом плане применены два батча (откат — только у свежего, batch 11),
    // во втором — один (его откат жив, хотя применён раньше всех).
    vi.mocked(allPlanFiles).mockResolvedValue([
      planFile({ batch_id: 10, status: "applied", applied_at: "2026-09-02T10:00:00Z" }),
      planFile({ batch_id: 11, status: "applied", applied_at: "2026-09-03T10:00:00Z" }),
      planFile({
        batch_id: 12,
        production_plan_id: 2,
        status: "applied",
        applied_at: "2026-09-01T10:00:00Z",
      }),
    ]);

    renderPage();

    await screen.findAllByText(/\.xlsx$/);
    const rollbackButtons = screen.getAllByRole("button", { name: /Откатить/ });
    const enabled = rollbackButtons.filter((button) => !(button as HTMLButtonElement).disabled);
    // По одному живому откату на план: batch 11 (план 1) и batch 12 (план 2).
    expect(enabled).toHaveLength(2);
    expect(rollbackButtons).toHaveLength(3);
  });

  it("подписывает план, которого нет в списке планов", async () => {
    vi.mocked(listPlans).mockResolvedValue([]);
    vi.mocked(allPlanFiles).mockResolvedValue([
      planFile({ batch_id: 7, production_plan_id: 42, filename: "сирота.xlsx" }),
    ]);

    renderPage();

    expect(await screen.findByText("сирота.xlsx")).toBeTruthy();
    // Гонка двух запросов: батч пришёл, план ещё нет. Пустой ячейки быть не
    // должно — адрес действия всё равно ведёт в верный план.
    expect(screen.getByText("План #42")).toBeTruthy();
  });

  it("убирает батч из списка скрытием, а не удалением", async () => {
    vi.mocked(listPlans).mockResolvedValue([plan()]);
    vi.mocked(allPlanFiles).mockResolvedValue([
      planFile({ batch_id: 8, filename: "август.xlsx" }),
    ]);
    vi.mocked(hideImportBatch).mockResolvedValue({ hidden: true, batch_id: 8 });

    renderPage();

    const row = (await screen.findByText("август.xlsx")).closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: /Убрать из списка/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Убрать из списка" }));

    await waitFor(() => {
      expect(hideImportBatch).toHaveBeenCalledWith(1, 8);
    });
    // Скрытие не удаляет: физическое удаление — отдельная кнопка и отдельный вызов.
    expect(within(row as HTMLElement).getByRole("button", { name: /Удалить/ })).toBeTruthy();
  });

  it("тумблер возвращает убранную строку с пометкой", async () => {
    vi.mocked(listPlans).mockResolvedValue([plan()]);
    const hiddenFile = planFile({ batch_id: 9, filename: "июль.xlsx", hidden: true });
    const visibleFile = planFile({ batch_id: 10, filename: "сентябрь.xlsx" });
    // Сервер сам решает, что видно: клиент лишь просит `include_hidden`.
    vi.mocked(allPlanFiles).mockImplementation(async (params) =>
      params?.includeHidden ? [hiddenFile, visibleFile] : [visibleFile],
    );

    renderPage();

    expect(await screen.findByText("сентябрь.xlsx")).toBeTruthy();
    expect(screen.queryByText("июль.xlsx")).toBeNull();

    fireEvent.click(screen.getByLabelText("Показывать убранные из списка"));

    expect(await screen.findByText("июль.xlsx")).toBeTruthy();
    expect(screen.getByText("Убрана из списка")).toBeTruthy();
    // У скрытого батча кнопки скрытия нет: вернуть его нельзя.
    const hiddenRow = screen.getByText("июль.xlsx").closest("tr") as HTMLElement;
    expect(within(hiddenRow).queryByRole("button", { name: /Убрать из списка/ })).toBeNull();
  });

  it("зрителю не рисует скрытие: сервер всё равно отдаст 403", async () => {
    asRole("viewer");
    vi.mocked(listPlans).mockResolvedValue([plan()]);
    vi.mocked(allPlanFiles).mockResolvedValue([
      planFile({ batch_id: 11, filename: "май.xlsx" }),
    ]);

    renderPage();

    const row = (await screen.findByText("май.xlsx")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button", { name: /Убрать из списка/ })).toBeNull();
  });
});
