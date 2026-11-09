import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/api/sections")>()),
  fetchAllSections: vi.fn(),
  reorderSections: vi.fn(),
  getSectionOperationGroups: vi.fn(),
}));

vi.mock("shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

// Роли viewer/transporter: `POLICIES.editReferences` ложно, раздел только для
// чтения. Страница обязана скрыть действия, а не показать их и получить 403.
vi.mock("@/entities/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/auth")>()),
  usePermission: () => ({ canEditReferences: false }),
}));

vi.mock("shared/ui/use-toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("shared/ui/use-toast")>()),
  toast: vi.fn(),
}));

import {
  fetchAllSections,
  getSectionOperationGroups,
} from "shared/api/sections";
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

const SECTION = {
  id: 1,
  code: "PACKING",
  name: "Упаковка",
  description: null,
  type: "production" as const,
  sort_order: 1,
  is_active: true,
  icon: null,
  icon_color: null,
  spg_links: [{ id: SPG.id, code: SPG.code, name: SPG.name }],
  operations_count: 1,
};

const OPERATION_GROUP = {
  group_code: "PACK",
  group_name: "Упаковка",
  sort_order: 0,
  operations: [
    {
      id: 10,
      operation_code: "PACK_01",
      operation_name: "Завернуть",
      is_significant: true,
      icon: null,
      icon_color: null,
      group_code: "PACK",
      group_name: "Упаковка",
      sort_order: 0,
      resolver_type: null,
    },
  ],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SectionsPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([SPG]);
  vi.mocked(fetchAllSections).mockResolvedValue([SECTION]);
  vi.mocked(getSectionOperationGroups).mockResolvedValue([OPERATION_GROUP]);
});

describe("SectionsPage — роль только для чтения", () => {
  it("не показывает кнопки добавления, правки, удаления и перестановки", async () => {
    renderPage();
    await screen.findByText("Упаковка");

    // Раздел целиком: ни создания участка/ГХП, ни перестановки строк.
    expect(screen.queryByRole("button", { name: "Добавить участок" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить ГХП" })).toBeNull();
    expect(screen.queryByTitle("Переместить вверх")).toBeNull();
    expect(screen.queryByTitle("Переместить вниз")).toBeNull();

    // Раскрываем операции участка: создания и правки групп/операций нет.
    const row = screen.getByText("Упаковка").closest("tr");
    if (!row) throw new Error("строка участка не найдена");
    fireEvent.click(within(row as HTMLElement).getByTitle("Показать операции"));

    expect(await screen.findByText("PACK_01")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Добавить группу" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить операцию" })).toBeNull();
    expect(screen.queryByTitle("Редактировать группу")).toBeNull();
    expect(screen.queryByTitle("Удалить группу")).toBeNull();
    expect(screen.queryByTitle("Удалить")).toBeNull();

    const checkbox = screen.getByRole("checkbox");
    expect((checkbox as HTMLInputElement).disabled).toBe(true);
  });
});
