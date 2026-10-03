/**
 * Журнал действий: строки, фильтры, пустые состояния и раскрытие.
 *
 * Файл написан до правки `AuditLogsPage.tsx` и на старой раскладке падал
 * красным — это был эталон, к которому страница пришла: плотные строки 32px с
 * тонами, статус подписью, панель-`FiltersPanel`, пустое состояние строкой
 * `colSpan` внутри `tbody`.
 *
 * Контракт, который держат тесты: `audit-row-{id}`, `audit-detail-row-{id}`,
 * тексты пустых состояний «История событий пуста.» и «Нет записей,
 * соответствующих заданным фильтрам и поисковому запросу.». Тумблеры
 * статуса находятся по подписи кнопки — у поля `FiltersPanel` нет testid.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api/auditLogs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/auditLogs")>()),
  getAuditLogs: vi.fn(),
}));

import { getAuditLogs, type AuditLogEntry, type AuditLogsResponse } from "@/shared/api/auditLogs";
import { ROW_TONE_STRIPE, ROW_TONE_WASH } from "@/shared/lib/rowTones";
import { DATA_TABLE_STYLES, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { TABLE_CORNER_RESET_TD_CLASS } from "@/shared/ui/TableCornerResetHeader";
import { AuditLogsPage } from "./AuditLogsPage";

const makeEntry = (overrides: Partial<AuditLogEntry> = {}): AuditLogEntry => ({
  id: 1,
  created_at: "2026-10-03T10:15:00",
  user_id: 7,
  user_name: "Иван Петров",
  status: "success",
  title: "Задание #42",
  message: "Операция «Сборка» завершена",
  section_id: 3,
  section_name: "Сборка",
  section_code: "SB",
  task_ids: "42",
  product_sku: "2604",
  operation_name: "Сборка",
  qty_text: "10 шт",
  comment: null,
  error_details: null,
  action: "task_complete",
  entity_type: "work_task",
  entity_id: 42,
  changes: null,
  ...overrides,
});

function makeResponse(overrides: Partial<AuditLogsResponse> = {}): AuditLogsResponse {
  return {
    items: [
      makeEntry(),
      makeEntry({ id: 2, status: "error", title: "Задание #43", message: "Партия отклонена", task_ids: "43" }),
      makeEntry({ id: 3, status: "info", title: "Задание #44", message: "Задание взято в работу", task_ids: "44" }),
    ],
    task_statuses: {},
    counts: { all: 3, success: 1, error: 1, info: 1 },
    total: 3,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuditLogsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAuditLogs).mockResolvedValue(makeResponse());
});

describe("AuditLogsPage", () => {
  it("рендерит строки журнала тонами по статусу и статусом-Badge", async () => {
    renderPage();

    const successRow = (await screen.findByTestId("audit-row-1")) as HTMLElement;
    const errorRow = screen.getByTestId("audit-row-2") as HTMLElement;
    const infoRow = screen.getByTestId("audit-row-3") as HTMLElement;

    // Тоны аудита: success → ok, error → scrap, info → обычная строка.
    expect(successRow.className).toContain(ROW_TONE_WASH.ok);
    expect(errorRow.className).toContain(ROW_TONE_WASH.scrap);
    expect(infoRow.className).not.toContain(ROW_TONE_WASH.ok);
    expect(infoRow.className).not.toContain(ROW_TONE_WASH.scrap);

    // Плотность доски: 32px на каждой строке, а не «сколько вышло».
    for (const row of [successRow, errorRow, infoRow]) {
      expect(row.style.height).toBe(`${TABLE_ROW_DENSE.rowHeightPx}px`);
    }

    // Статус — подпись бейджем: кружок-иконка без текста в 32px не читается.
    expect(within(successRow).getByText("Успешно")).toBeTruthy();
    expect(within(errorRow).getByText("Ошибка")).toBeTruthy();
    expect(within(infoRow).getByText("Информация")).toBeTruthy();
  });

  it("шапка и ячейки журнала берут размеры из общего словаря, а не свои", async () => {
    renderPage();

    const row = (await screen.findByTestId("audit-row-1")) as HTMLElement;

    // Шапка: `headerRow` + `headerCell` + плотный `headerCell`. Проверяем по
    // словарю, а не литералом класса — смена словаря не должна ронять тест,
    // а вот возврат к своим `bg-slate-100 uppercase p-3` должен.
    const header = row.closest("table")!.querySelector("thead th") as HTMLElement;
    expect(header.className).toContain(DATA_TABLE_STYLES.headerRow);
    expect(header.className).toContain(DATA_TABLE_STYLES.headerCell);
    expect(header.className).toContain(TABLE_ROW_DENSE.headerCell);

    // Ячейки тела: каждая на `TABLE_ROW_DENSE.cell`, полоса тона — на первой.
    // Именно эти две проверки роняют страницу, если `p-3` вернётся в разметку
    // или полоса тона переедет на `<tr>`, где при `border-separate` её не видно.
    // Угловая ячейка сброса — не содержимое: ширина у неё своя
    // (`TABLE_CORNER_RESET_TD_CLASS`), и в общий словарь она не входит.
    const cells = [...row.querySelectorAll("td")].filter(
      (cell) => !(cell as HTMLElement).className.includes(TABLE_CORNER_RESET_TD_CLASS),
    ) as HTMLElement[];
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.className).toContain(TABLE_ROW_DENSE.cell);
    }
    expect(cells[0]!.className).toContain(ROW_TONE_STRIPE.ok);
  });

  it("фильтр статуса уезжает в параметры запроса", async () => {
    renderPage();
    await screen.findByTestId("audit-row-1");

    // Тумблеры — кнопки панели, и находятся по подписи, а не по testid:
    // `FiltersPanel` не принимает testid у поля, и ради одного экрана
    // расширять общий контракт панели незачем.
    fireEvent.click(screen.getByRole("button", { name: /^Ошибки/ }));

    await waitFor(() => {
      expect(getAuditLogs).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
    });

    // «Все записи» снимает фильтр: без этого журнал нечем вернуть в обзор.
    fireEvent.click(screen.getByRole("button", { name: /^Все записи/ }));
    await waitFor(() => {
      expect(getAuditLogs).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: undefined }),
      );
    });
  });

  it("пустой журнал без единой записи — «История событий пуста.»", async () => {
    vi.mocked(getAuditLogs).mockResolvedValue(
      makeResponse({ items: [], total: 0, counts: { all: 0, success: 0, error: 0, info: 0 } }),
    );
    renderPage();

    const empty = await screen.findByText("История событий пуста.");
    // Пустое состояние — строка таблицы, а не поплавок над ней: колонки и их
    // шапка не должны прыгать, когда данных нет.
    expect(empty.closest("td")).toBeTruthy();
    expect(screen.queryByText(/Нет записей, соответствующих/)).toBeNull();
  });

  it("пустой результат фильтра при непустом журнале — другой текст", async () => {
    vi.mocked(getAuditLogs).mockResolvedValue(
      makeResponse({ items: [], total: 0, counts: { all: 12, success: 9, error: 2, info: 1 } }),
    );
    renderPage();

    const empty = await screen.findByText(
      "Нет записей, соответствующих заданным фильтрам и поисковому запросу.",
    );
    expect(empty.closest("td")).toBeTruthy();
    expect(screen.queryByText("История событий пуста.")).toBeNull();
  });

  it("детальная строка раскрывается и сворачивается", async () => {
    renderPage();
    const row = (await screen.findByTestId("audit-row-1")) as HTMLElement;

    expect(screen.queryByTestId("audit-detail-row-1")).toBeNull();

    fireEvent.click(row);
    const detail = await screen.findByTestId("audit-detail-row-1");
    expect(within(detail).getByText("Детали события: Задание #42")).toBeTruthy();
    // Полное сообщение видно только в раскрытой строке: в основной оно обрезано.
    expect(within(detail).getByText("Операция «Сборка» завершена")).toBeTruthy();

    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.queryByTestId("audit-detail-row-1")).toBeNull();
    });
  });
});