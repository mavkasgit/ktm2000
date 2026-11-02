/**
 * «Передачи» на телефоне — та же таблица с закреплёнными колонками (#343).
 *
 * Контракт: «Артикул» закреплён слева, «Действия» справа; количество и кнопка
 * обязаны быть видны без свайпа. Пиксели кадра 390×844 меряет e2e
 * (`e2e/mobile-transfers.spec.ts`), здесь — то, что в пикселях не проверить:
 * слово у закреплённого действия переживает сворачивание подписи.
 *
 * Ревью #341 п. 2: с подписью, написанной на кнопке, закреплённая колонка
 * вместе с текстом причины не влезает в кадр (замер: профиль 104,0px +
 * действия 284,8px против 390px — полосы прокрутки не остаётся вовсе). Доска
 * участка (#345) в том же положении свернула подпись в пиктограмму, оставив
 * слово в `aria-label`; правило перенесено сюда, и для теста оно означает
 * ровно одно: доступное имя задаётся явно, а не только написанным текстом.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/transfers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/transfers")>()),
  listReadyToTransfer: vi.fn(),
  listTransferHistory: vi.fn(),
}));

vi.mock("@/shared/api/spg", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/spg")>()),
  getSpgList: vi.fn(),
}));

import { getSpgList } from "@/shared/api/spg";
import {
  listReadyToTransfer,
  listTransferHistory,
  type ReadyToTransferTask,
  type TransferHistoryResponse,
} from "@/shared/api/transfers";
import { stubViewportWidth } from "@/shared/lib/testViewport";
import { TransfersPage } from "./TransfersPage";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: "010",
    operation_name: "Пиление",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "100",
    completed_quantity: "100",
    already_transferred_quantity: "0",
    transferable_quantity: "100",
    has_next_step: true,
    next_section_id: 9,
    next_section_code: "PACK",
    next_section_name: "Упаковка",
    next_operation_name: "Упаковка",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

/** Ответ сервера: ready-выборка без серверной сортировки. */
function mockReadyItems(items: ReadyToTransferTask[]) {
  vi.mocked(listReadyToTransfer).mockImplementation(async (params = {}) => ({
    items,
    total: items.length,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
    filters: { section_id: null, spg_id: null },
  }));
}

/** Отрисовка «как на телефоне»: порог телефона в проекте — 768px. */
function renderMobile(items: ReadyToTransferTask[]) {
  stubViewportWidth(375);
  mockReadyItems(items);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TransfersPage />
    </QueryClientProvider>,
  );
}

/** Строка таблицы по её роду: задание или шапка группы. */
function rowOfKind(container: HTMLElement, kind: "ready-task" | "ready-group") {
  return container.querySelector(`tr[data-row-kind="${kind}"]`) as HTMLElement;
}

async function waitForRows(
  container: HTMLElement,
  kind: "ready-task" | "ready-group",
  count: number,
) {
  await waitFor(() => {
    expect(
      container.querySelectorAll(`tr[data-row-kind="${kind}"]`),
      `строк «${kind}» отрисовано не ${count}`,
    ).toHaveLength(count);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpgList).mockResolvedValue([
    {
      id: 1,
      code: "GP1",
      name: "ГХП №1",
      description: null,
      sort_order: 10,
      is_active: true,
      icon: null,
      icon_color: null,
      sections: [
        {
          section_id: 1,
          section_code: "SAW",
          section_name: "Пила",
          sort_order: 10,
          type: "production",
          icon: null,
          icon_color: null,
        },
      ],
    },
  ]);
  vi.mocked(listTransferHistory).mockResolvedValue({
    section_id: null,
    spg_id: null,
    transfers: [],
    total: 0,
    limit: 50,
    offset: 0,
  } satisfies TransferHistoryResponse);
});

describe("TransfersPage на телефоне: закреплённые колонки строки", () => {
  it("профиль закреплён слева, действия — справа", async () => {
    const { container } = renderMobile([makeTask()]);
    await waitForRows(container, "ready-task", 1);

    const row = rowOfKind(container, "ready-task");
    const profile = row.querySelector('[data-sticky="profile"]') as HTMLElement;
    const actions = row.querySelector('[data-sticky="actions"]') as HTMLElement;

    expect(profile, "закреплённый артикул строки").toBeTruthy();
    expect(actions, "закреплённые действия строки").toBeTruthy();
    expect(profile.textContent).toContain("ЮП-2083");
    // Количество с кнопкой живут в закреплённой ячейке: без свайпа.
    expect(actions.querySelector('input[type="number"]')).toBeTruthy();
  });

  /**
   * На телефоне подпись закреплённого действия свёрнута в пиктограмму, иначе
   * колонка «Действия» с текстом причины не оставляет полосы прокрутки и
   * наезжает на закреплённый артикул (#341, п. 2; кадр — в e2e). Слово обязано
   * пережить сворачивание: доступное имя задаётся `aria-label`, а не только
   * написанным на кнопке текстом.
   */
  it("закреплённое действие остаётся названным словом, когда подпись свёрнута", async () => {
    const { container } = renderMobile([makeTask()]);
    await waitForRows(container, "ready-task", 1);

    const actions = rowOfKind(container, "ready-task").querySelector(
      '[data-sticky="actions"]',
    ) as HTMLElement;
    const button = actions.querySelector("button") as HTMLButtonElement;

    expect(button, "кнопка действия в закреплённой ячейке").toBeTruthy();
    expect(button.getAttribute("aria-label"), "имя кнопки строки задаётся явно").toBe("Передать");
  });

  it("финальная строка называет «Отправить» тем же явным именем", async () => {
    const { container } = renderMobile([
      makeTask({
        is_final: true,
        has_next_step: false,
        next_section_name: null,
        next_operation_name: null,
      }),
    ]);
    await waitForRows(container, "ready-task", 1);

    const actions = rowOfKind(container, "ready-task").querySelector(
      '[data-sticky="actions"]',
    ) as HTMLElement;
    const button = actions.querySelector("button") as HTMLButtonElement;

    expect(button.getAttribute("aria-label"), "имя кнопки финального выпуска").toBe("Отправить");
  });

  it("шапка группы называет своим явным именем общую кнопку передачи", async () => {
    // Две неразличимые для передачи строки одного артикула сворачиваются в
    // группу: её шапка несёт то же закрепление и свою кнопку.
    const { container } = renderMobile([
      makeTask({ task_id: 1, plan_position_id: 1, transferable_quantity: "10" }),
      makeTask({ task_id: 2, plan_position_id: 2, transferable_quantity: "10" }),
    ]);
    await waitForRows(container, "ready-group", 1);

    const actions = rowOfKind(container, "ready-group").querySelector(
      '[data-sticky="actions"]',
    ) as HTMLElement;
    const button = actions.querySelector("button") as HTMLButtonElement;

    expect(button, "кнопка передачи группы в закреплённой ячейке").toBeTruthy();
    expect(button.getAttribute("aria-label"), "имя кнопки группы").toBe("Передать");
  });
});

/**
 * Ревью #341 п. 4. На телефоне шапка группы свёрнута в закреплённые «Артикул» и
 * «Действия»: колонка с шевроном (`blockRail`) скрыта, поэтому единственный
 * способ раскрыть группу обязан жить в закреплённом профиле — там, где он
 * виден без свайпа. Тот же порядок, что у доски участка (#345).
 */
describe("TransfersPage на телефоне: раскрытие группы", () => {
  const pair = () => [
    makeTask({ task_id: 1, plan_position_id: 1, transferable_quantity: "10" }),
    makeTask({ task_id: 2, plan_position_id: 2, transferable_quantity: "10" }),
  ];

  it("шеврон в закреплённом профиле раскрывает группу и прячет снова", async () => {
    const { container } = renderMobile(pair());
    await waitForRows(container, "ready-group", 1);

    const profile = container.querySelector(
      'tr[data-row-kind="ready-group"] [data-sticky="profile"]',
    ) as HTMLElement;
    expect(profile, "закреплённый профиль шапки группы").toBeTruthy();

    // Свёрнутая группа: строк заданий нет, видна только её шапка.
    expect(container.querySelectorAll('tr[data-row-kind="ready-task"]')).toHaveLength(0);

    const chevron = within(profile).getByRole("button", { name: "Раскрыть" });
    fireEvent.click(chevron);
    await waitFor(() =>
      expect(
        container.querySelectorAll('tr[data-row-kind="ready-task"]'),
        "после тапа по шеврону группа раскрыта",
      ).toHaveLength(2),
    );

    fireEvent.click(within(profile).getByRole("button", { name: "Скрыть" }));
    await waitFor(() =>
      expect(
        container.querySelectorAll('tr[data-row-kind="ready-task"]'),
        "после второго тапа группа снова свёрнута",
      ).toHaveLength(0),
    );
  });
});

/**
 * Ревью #341 п. 3. Колонка сброса в шапке таблицы на телефоне скрыта: она
 * оказалась бы под закреплёнными «Действиями» и не попала бы под палец. Значит
 * единственный сброс фильтров — кнопка в ряду фильтров, как на доске участка.
 * Имя точное: кнопка скрытой колонки называется «Сбросить фильтры» и прошла бы
 * тестом подстрокой там, где пальцем до неё не достать.
 */
describe("TransfersPage на телефоне: сброс фильтров в ряду фильтров", () => {
  it("поиск и «Сбросить» доступны, сброс очищает введённое", async () => {
    const { container } = renderMobile([makeTask()]);
    await waitForRows(container, "ready-task", 1);

    const search = within(container).getByPlaceholderText(/Поиск по ID/) as HTMLInputElement;
    const reset = within(container).getByRole("button", { name: "Сбросить" });

    fireEvent.change(search, { target: { value: "ЮП-2083" } });
    expect(search.value).toBe("ЮП-2083");

    fireEvent.click(reset);
    await waitFor(() => expect(search.value, "сброс очистил поиск").toBe(""));
  });
});
