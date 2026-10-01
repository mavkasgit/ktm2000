/**
 * Сортировка списка сотрудников: наружу уходит строка `sort` со всеми
 * выбранными приоритетами.
 *
 * Регресс: на сервер уходил только `sortConfigs[0]`, поэтому вторая
 * колонка с бейджем приоритета «2» вообще не влияла на порядок строк —
 * оператор кликал и не видел эффекта.
 *
 * Порядок по умолчанию объявлен хуку (`defaultSort`), поэтому он стоит
 * первым приоритетом, пока оператор его не снимет: раньше экран подставлял
 * `name:asc` сравнением строк и первым же кликом по любой колонке этот
 * порядок заменялся — после чего «сортировка нестандартная» и сброс
 * считались руками и расходились с остальными экранами.
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

/**
 * Кнопка сортировки колонки. Доступное имя теперь собирается из подписи
 * колонки («Отдел, сортировка по возрастанию», #204), поэтому тест адресует
 * кнопку по машинному полю в `data-sort-field`.
 */
function sortButton(field: string): HTMLElement {
  const button = document.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
  if (!button) throw new Error(`Не найдена кнопка сортировки колонки «${field}»`);
  return button;
}

const clickSort = (field: string) => fireEvent.click(sortButton(field));

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

  it("в запрос уходят все выбранные приоритета, от старшего к младшему", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("department");
    await waitFor(() => expect(lastSort()).toBe("name:asc,department:desc"));

    clickSort("position");
    await waitFor(() => expect(lastSort()).toBe("name:asc,department:desc,position:desc"));
  });

  it("колонка HRMS ID уходит на сервер полем hrms_id, а не именем колонки", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("hrmsId");
    await waitFor(() => expect(lastSort()).toBe("name:asc,hrms_id:desc"));
  });

  it("повторный клик по колонке меняет направление, а не добавляет приоритет", async () => {
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("tabNumber");
    await waitFor(() => expect(lastSort()).toBe("name:asc,tab_number:desc"));
    clickSort("tabNumber");
    await waitFor(() => expect(lastSort()).toBe("name:asc,tab_number:asc"));
  });

  it("снятие сортировки по имени не уезжает в запрос: сервер сортирует так же", async () => {
    // Цикл клика общий: нет → убыв. → возр. → снять. «ФИО» стоит в состоянии
    // сразу (порядок по умолчанию), поэтому первый клик снимает колонку, и
    // строка `sort` исчезает. Порядок строк не меняется: сервер по умолчанию
    // сортирует по имени возрастанию (`_SORT_DEFAULT`) — ровно так же, как
    // `defaultSort`. Если дефолты разойдутся, тест упадёт.
    renderTable();
    await waitFor(() => expect(lastSort()).toBe("name:asc"));

    clickSort("name");
    await waitFor(() => expect(lastSort()).toBeUndefined());

    clickSort("name");
    await waitFor(() => expect(lastSort()).toBe("name:desc"));
  });
});
