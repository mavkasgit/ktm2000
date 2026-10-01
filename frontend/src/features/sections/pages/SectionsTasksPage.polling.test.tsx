import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import type * as SectionsApi from "@/shared/api/sections";
import type * as ShopfloorApi from "@/shared/api/shopfloor";

// Интервал опроса подменяем коротким: проверяем не число, а то, что доска
// действительно перечитывается сама, без действия пользователя (#206). Реальное
// значение сторожит `shared/api/operationalPolling.test.ts`, коридор 10–15 с —
// доска с 40 мс ждать 12 с не даёт.
vi.mock("@/shared/api/operationalPolling", () => ({
  OPERATIONAL_POLL_INTERVAL_MS: 40,
  operationalPollingOptions: { refetchInterval: 40, refetchIntervalInBackground: false },
}));

vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { id: 1, email: "a@b.c", full_name: "A", role: "admin", section_id: null, is_active: true },
    }),
  },
  getErrorMessage: (e: unknown) => String(e),
}));

vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof SectionsApi>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/shopfloor", async (importOriginal) => ({
  ...(await importOriginal<typeof ShopfloorApi>()),
  getSectionBoard: vi.fn(),
  getSectionsSummary: vi.fn(),
  listDailyPlans: vi.fn(),
  getSectionDailyStats: vi.fn(),
}));

import { listSections, type Section } from "@/shared/api/sections";
import {
  getSectionBoard,
  getSectionsSummary,
  listDailyPlans,
  getSectionDailyStats,
  type SectionBoardResponse,
} from "@/shared/api/shopfloor";
import { SectionsTasksPage } from "./SectionsTasksPage";

const section = (id: number, name: string): Section => ({
  id,
  code: `S${id}`,
  name,
  description: null,
  sort_order: id,
  is_active: true,
  type: "production",
  icon: null,
  icon_color: null,
});

const board = (sectionId: number): SectionBoardResponse => ({
  section_id: sectionId,
  tasks: [],
  available_operations: [],
  total: 0,
  limit: 50,
  offset: 0,
});

function renderPage(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/section-tasks", element: <SectionsTasksPage /> },
      { path: "/section-tasks/:sectionId", element: <SectionsTasksPage /> },
    ],
    { initialEntries: [initialEntry] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([section(2, "Пила")]);
  vi.mocked(getSectionBoard).mockImplementation(async (id: number) => board(id));
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 0, daily_stats: [] });
});

describe("SectionsTasksPage: опрос доски", () => {
  it("перечитывает доску сама, без действия пользователя", async () => {
    renderPage("/section-tasks/2");
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledTimes(1));

    // Никаких кликов и ввода: второй вызов возможен только по таймеру опроса.
    await waitFor(() => expect(vi.mocked(getSectionBoard).mock.calls.length).toBeGreaterThan(1), {
      timeout: 2_000,
    });
  });
});
