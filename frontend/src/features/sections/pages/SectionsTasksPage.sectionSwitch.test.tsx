import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { id: 1, email: "a@b.c", full_name: "A", role: "admin", section_id: null, is_active: true },
    }),
  },
  getErrorMessage: (e: unknown) => String(e),
}));

vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/shopfloor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/shopfloor")>()),
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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  vi.mocked(listSections).mockResolvedValue([section(2, "Пила"), section(8, "Упаковка")]);
  vi.mocked(getSectionBoard).mockImplementation(async (id: number) => board(id));
  vi.mocked(getSectionsSummary).mockResolvedValue({ sections: [] });
  vi.mocked(listDailyPlans).mockResolvedValue([]);
  vi.mocked(getSectionDailyStats).mockResolvedValue({ section_id: 0, daily_stats: [] });
});

describe("SectionsTasksPage: смена участка плиткой", () => {
  it("не возвращает доску к прежнему участку после переключения", async () => {
    renderPage("/section-tasks/2");
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));

    const before = vi.mocked(getSectionBoard).mock.calls.length;
    fireEvent.click(await screen.findByRole("button", { name: /Упаковка/ }));

    // Ждём, пока роутер докоммитит location (он в transition) и отработают
    // эффекты, — и проверяем, что за это время прежний участок не запрашивался
    // повторно: его доска не должна возвращаться на экран между прежним и новым.
    await waitFor(async () => {
      await delay(100);
      expect(vi.mocked(getSectionBoard).mock.calls.slice(before).map((c) => c[0])).toEqual([8]);
    });
  });

  it("не переносит поиск прежнего участка на новый", async () => {
    renderPage("/section-tasks/2");
    await waitFor(() => expect(getSectionBoard).toHaveBeenCalledWith(2, expect.anything(), undefined));

    const searchOf = (call: Parameters<typeof getSectionBoard>): string | undefined => call[1]?.search;
    fireEvent.change(await screen.findByPlaceholderText("Поиск"), { target: { value: "ZZZ" } });
    await waitFor(() =>
      expect(vi.mocked(getSectionBoard).mock.calls.some((c) => searchOf(c) === "ZZZ")).toBe(true),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Упаковка/ }));
    await waitFor(() => expect(vi.mocked(getSectionBoard).mock.calls.some((c) => c[0] === 8)).toBe(true));
    await waitFor(async () => {
      await delay(100);
      // Ни один запрос нового участка не несёт поиск прежнего, и поле пусто:
      // строка, набранная на прежнем участке, сужала бы выборку нового.
      const forNew = vi.mocked(getSectionBoard).mock.calls.filter((c) => c[0] === 8);
      expect(forNew.every((c) => searchOf(c) === undefined)).toBe(true);
      expect((screen.getByPlaceholderText("Поиск") as HTMLInputElement).value).toBe("");
    });
  });
});
