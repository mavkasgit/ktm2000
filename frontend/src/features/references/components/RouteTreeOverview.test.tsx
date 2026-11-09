import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/routes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/routes")>()),
  listRoutes: vi.fn(),
  reorderRoutes: vi.fn(),
}));

vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/ui/use-toast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/ui/use-toast")>()),
  toast: vi.fn(),
}));

import { listRoutes, reorderRoutes, type RouteDetail } from "@/shared/api/routes";
import { listSections } from "@/shared/api/sections";
import { RouteTreeOverview } from "./RouteTreeOverview";

function route(id: number, name: string): RouteDetail {
  return {
    id,
    name,
    description: "",
    is_active: true,
    steps: [],
  } as unknown as RouteDetail;
}

function renderOverview() {
  return render(
    <RouteTreeOverview onEditRoute={vi.fn()} />,
  );
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest("[draggable]");
  if (!row) throw new Error(`row for ${name} not found`);
  return row as HTMLElement;
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSections).mockResolvedValue([]);
  vi.mocked(listRoutes).mockResolvedValue([
    route(1, "Alpha"),
    route(2, "Bravo"),
    route(3, "Charlie"),
  ]);
});

describe("RouteTreeOverview — перестановка маршрутов", () => {
  it("без фильтра отправляет полный список в новом порядке", async () => {
    const view = renderOverview();

    const down = await screen.findByText("Alpha");
    expect(down).toBeTruthy();
    fireEvent.click(within(rowOf("Alpha")).getByTitle("Переместить вниз"));

    await waitFor(() => expect(reorderRoutes).toHaveBeenCalledWith([2, 1, 3]));
    view.unmount();
  });

  it("при активном фильтре сосед — следующая ВИДИМАЯ строка, а скрытая остаётся на месте", async () => {
    renderOverview();
    await screen.findByText("Alpha");

    fireEvent.change(screen.getByPlaceholderText("Поиск по названию..."), {
      target: { value: "l" },
    });

    await waitFor(() => expect(screen.queryByText("Bravo")).toBeNull());
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Charlie")).toBeTruthy();

    fireEvent.click(within(rowOf("Alpha")).getByTitle("Переместить вниз"));

    // На сервер уходит полный список: Alpha встаёт после Charlie, Bravo
    // не теряется и остаётся перед Charlie (движение, а не обмен).
    await waitFor(() => expect(reorderRoutes).toHaveBeenCalledWith([2, 3, 1]));
  });
});
