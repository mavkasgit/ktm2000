import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/api/sections")>()),
  fetchAllSections: vi.fn(),
  reorderSections: vi.fn(),
  getSectionOperationGroups: vi.fn().mockResolvedValue([]),
}));

vi.mock("shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

vi.mock("@/entities/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/auth")>()),
  usePermission: () => ({ canEditReferences: true }),
}));

vi.mock("shared/ui/use-toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/ui/use-toast")>()),
  toast: vi.fn(),
}));

import { fetchAllSections, reorderSections, type Section } from "shared/api/sections";
import { getSpgList } from "shared/api/spg";
import { SectionsPage } from "./SectionsPage";

const SPG = {
  id: 1,
  code: "SPG",
  name: "ГХП",
  description: null,
  sort_order: 0,
  is_active: true,
  icon: null,
  icon_color: null,
  sections: [],
};

function section(id: number, name: string): Section {
  return {
    id,
    code: name.toUpperCase(),
    name,
    type: "production",
    sort_order: id,
    spg_links: [{ id: SPG.id, code: SPG.code, name: SPG.name }],
    operations_count: 0,
  } as Section;
}

const ALL = [section(1, "Alpha"), section(2, "Bravo"), section(3, "Charlie")];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SectionsPage />
    </QueryClientProvider>,
  );
}

function downButton(name: string): HTMLElement {
  const row = screen.getByText(name).closest("tr");
  if (!row) throw new Error(`row for ${name} not found`);
  return within(row as HTMLElement).getByTitle("Переместить вниз");
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([SPG]);
  vi.mocked(fetchAllSections).mockImplementation(async (params = {}) => {
    const query = (params.search ?? "").trim().toLowerCase();
    return query
      ? ALL.filter((item) => `${item.name} ${item.code}`.toLowerCase().includes(query))
      : ALL;
  });
});

describe("SectionsPage — перестановка участков", () => {
  it("без фильтра отправляет полный порядок", async () => {
    const view = renderPage();
    await screen.findByText("Alpha");

    fireEvent.click(downButton("Alpha"));

    await waitFor(() => expect(reorderSections).toHaveBeenCalledWith([2, 1, 3]));
    view.unmount();
  });

  it("при фильтре отправляет полный справочник, скрытая строка остаётся на месте", async () => {
    renderPage();
    await screen.findByText("Alpha");

    fireEvent.change(
      screen.getByPlaceholderText("Поиск по коду, названию, описанию, ГХП"),
      { target: { value: "l" } },
    );

    await waitFor(() =>
      expect(fetchAllSections).toHaveBeenCalledWith(
        expect.objectContaining({ search: "l" }),
      ),
    );
    await waitFor(() => expect(screen.queryByText("Bravo")).toBeNull());
    // Дождаться конца перезапроса, а не кликать по старым/пустым данным.
    await screen.findByText("Alpha");
    await screen.findByText("Charlie");

    fireEvent.click(downButton("Alpha"));

    // Alpha и Charlie меняются местами в полном списке; скрытый Bravo
    // остаётся на индексе 1 — фильтр не переставляет справочник.
    await waitFor(() => expect(reorderSections).toHaveBeenCalledWith([3, 2, 1]));
    expect(fetchAllSections).toHaveBeenCalledWith({ sort: "sort_order:asc" });
  });
});
