import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { id: 1, email: "a@b.c", full_name: "A", role: "admin", section_id: null, is_active: true },
    }),
  },
  getErrorMessage: (e: unknown) => String(e),
}));

vi.mock("@/shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getStockBalances: vi.fn(),
}));

import { getSpgList, type SpgOut } from "@/shared/api/spg";
import { getStockBalances } from "@/shared/api/stock";
import { SpgSnapshotPage } from "./SpgSnapshotPage";

const spgWithoutSections: SpgOut = {
  id: 7,
  code: "SPG7",
  name: "Без участков",
  description: null,
  sort_order: 1,
  is_active: true,
  icon: null,
  icon_color: null,
  sections: [],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/spg"]}>
        <SpgSnapshotPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([spgWithoutSections]);
  vi.mocked(getStockBalances).mockResolvedValue({ balances: [], total: 0, limit: 50, offset: 0 });
});

describe("SpgSnapshotPage: ГХП без участков", () => {
  it("помечает, что у выбранной ГХП нет участков, и не пустеет данными", async () => {
    renderPage();

    // Дефолт «все ГХП»: кнопка «Все группы» активна, пока ничего не выбрано.
    const allButton = await screen.findByRole("button", { name: /Все группы/ });
    expect(allButton.className).toContain("bg-primary");

    fireEvent.click(await screen.findByRole("button", { name: /Без участков/ }));

    // Шапка явно говорит, почему под ней остатки всех групп, а не молчит.
    await waitFor(() =>
      expect(
        screen.queryByText(/нет участков — показаны остатки по всем группам/),
      ).not.toBeNull(),
    );

    // Данные не пустеют: панель остатков на месте и запрос уходит без фильтра по участкам.
    expect(screen.queryByText(/Наличие на участках/)).not.toBeNull();
    const calls = vi.mocked(getStockBalances).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1][0]?.location_ids).toBeUndefined();
  });
});
