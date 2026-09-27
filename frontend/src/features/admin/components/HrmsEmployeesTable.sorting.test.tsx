/**
 * Сортировка списка сотрудников: наружу уходит строка `sort` со всеми
 * выбранными приоритетами.
 *
 * Регресс: на сервер уходил только `sortConfigs[0]`, поэтому вторая
 * колонка с бейджем приоритета «2» вообще не влияла на порядок строк —
 * оператор кликал и не видел эффекта.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  listEmployees: vi.fn(),
}));

import { listEmployees } from "../api";
import { HrmsEmployeesTable } from "./HrmsEmployeesTable";

const EMPLOYEE = {
  id: 1,
  hrms_id: 101,
  name: "Иванов Иван",
  tab_number: "0001",
  position: "Сварщик",
  department: "Сварка",
};

const renderTable = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HrmsEmployeesTable />
    </QueryClientProvider>,
  );

// У активной колонки в aria-label добавляется направление: «Сортировка по name (desc)».
const clickSort = (field: string) =>
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^Сортировка по ${field}`) }));

/** Строка `sort` последнего запроса сотрудников. */
const lastSort = () => {
  const calls = vi.mocked(listEmployees).mock.calls;
  return calls[calls.length - 1]?.[0]?.sort;
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listEmployees).mockResolvedValue({
    employees: [EMPLOYEE],
    total: 1,
    limit: 50,
    offset: 0,
    synced_at: null,
  });
});

describe("HrmsEmployeesTable: сортировка колонок", () => {
  it("до первого клика по шапке просит порядок по имени", async () => {
    renderTable();

    await waitFor(() => expect(listEmployees).toHaveBeenCalled());
    expect(vi.mocked(listEmployees).mock.calls[0][0]).toMatchObject({ sort: "name:asc" });
  });

  it("в запрос уходят оба выбранных приоритета в порядке выбора", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("department");
    await waitFor(() => expect(lastSort()).toBe("department:desc"));

    clickSort("name");
    await waitFor(() => expect(lastSort()).toBe("department:desc,name:desc"));
  });

  it("колонка HRMS ID уходит на сервер полем hrms_id, а не именем колонки", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("hrmsId");
    await waitFor(() => expect(lastSort()).toBe("hrms_id:desc"));
  });

  it("повторный клик по колонке меняет направление, а не добавляет приоритет", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("tabNumber");
    await waitFor(() => expect(lastSort()).toBe("tab_number:desc"));
    clickSort("tabNumber");
    await waitFor(() => expect(lastSort()).toBe("tab_number:asc"));
  });
});
