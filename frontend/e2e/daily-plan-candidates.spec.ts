import type { Page } from "@playwright/test";

import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiCreateBareProduct,
  apiGetSectionByCode,
  apiGetSections,
  apiResetAll,
  apiSeedData,
  apiSimulatePlanImport,
} from "./api-helpers";
import { expect, test } from "./fixtures";
import {
  approvePositionViaUI,
  expandBoardGroupsViaUI,
  fetchBoardViaUI,
  findApprovablePositionViaUI,
  takeToWorkViaUI,
  waitForPlanningTableViaUI,
  type ApprovablePosition,
} from "./ui-helpers";

/**
 * @ui — тикет #301: задание, уже включённое в дневной план, не должно
 * показываться кандидатами при создании нового плана и не должно уходить
 * в его состав.
 *
 * Что проверяем (приёмка AC тикета):
 * 1. На доске участка с непустым планом задание этого плана **не появляется**
 *    в кандидатах — строки нет вовсе (без заменителя и пояснений).
 * 2. Оно **не считается в счётчике** «Выбрано N»: счётчик равен числу
 *    кандидатов, а не числу строк доски.
 * 3. Подтверждение плана, собранного **из показанных строк**, не даёт `409`:
 *    скрытое задание не уходит ни через клик по строке, ни через
 *    «Выделить все», ни через шапку группы.
 *
 * ## Грабли сетапа, на которые ушло время (не повторять)
 *
 * - `apiRunDemoFullRoute` **не годится**: он доводит все стадии роута до
 *   конца, доска остаётся пустой и кандидатов не существует — тест проверял
 *   бы пустоту. Рабочий путь: план из позиций → утверждение → «Взять в
 *   работу» (как в `sawing-four-lengths-cycle`), после этого доска заполнена.
 * - Вкладку «План» берём **по контейнеру вкладок**: кнопка с таким именем
 *   есть и в самой таблице (выбор колонок, `aria-haspopup`), и поиск по
 *   странице даёт `strict mode violation` на двух элементах.
 * - Группы надо раскрыть (`expandBoardGroupsViaUI`): таблица виртуализирована,
 *   и без раскрытия `data-task-id` в DOM не попадает — клик провисает до
 *   таймауста теста.
 * - Клик по строке **не даёт отбора**, если `status === "waiting_previous"`:
 *   `SectionTasksBoard` на такой строке Selection не переключает вовсе. Поэтому
 *   кандидат на «занятое» задание берём из доски явно, отбрасывая
 *   `waiting_previous`, и сразу проверяем `aria-selected` — иначе падение
 *   выглядит как «кнопка „Подтвердить“ не нажимается», а причина в другом.
 */

/** Дата плана в формате маски `Дата плана` (ДД.ММ.ГГГГ). */
const PLAN_DATE = "03.10.2026";

/** Строка задания доски. */
function rowById(page: Page, taskId: number) {
  return page.locator(`tr[data-row-kind="board-task"][data-task-id="${taskId}"]`);
}

/** Кандидаты режима создания плана — отрисованные строки доски. */
function candidateRows(page: Page) {
  return page.locator('tr[data-row-kind="board-task"][data-task-id]');
}

/** Вкладка «План» — по контейнеру вкладок, см. грабли в шапке. */
function planTab(page: Page) {
  return page
    .locator("div.inline-flex.items-center.rounded-md.border", {
      has: page.getByRole("button", { name: "План", exact: true }),
    })
    .getByRole("button", { name: "План", exact: true });
}

/** Задание доски в форме, которой пользуется этот тест. */
interface BoardTask {
  id: number;
  status?: string;
  in_daily_plan?: boolean;
}

/**
 * Задания доски в форме теста. Ответ приходит как `Record<string, unknown>`,
 * поэтому каждое поле сужается явно, а не через утверждение типа: иначе
 * опечатка в имени поля прошла бы молча.
 */
function boardTasks(raw: Array<Record<string, unknown>>): BoardTask[] {
  return raw.map((task) => ({
    id: Number(task.id),
    status: typeof task.status === "string" ? task.status : undefined,
    in_daily_plan: task.in_daily_plan === true,
  }));
}

async function fillPlanDate(page: Page): Promise<void> {
  const dateInput = page.getByRole("textbox", { name: "Дата плана" });
  await dateInput.fill("");
  await dateInput.pressSequentially(PLAN_DATE);
}

/** Кандидаты, которые доска отдаёт и которые можно выбрать (см. грабли). */
function selectableTasks(tasks: BoardTask[]): BoardTask[] {
  return tasks.filter(
    (task) => task.status !== "waiting_previous" && task.in_daily_plan !== true,
  );
}


/**
 * Участок, на доске которого есть задания, доступные для плана.
 *
 * Угадывать участок по коду роута нельзя: у задания, ждущего предыдущую
 * стадию, `status === "waiting_previous"`, и такую строку доска не отдаёт как
 * кандидата — ни в «Выделить все», ни по клику (в `SectionTasksBoard` клик по
 * такой строке Selection не переключает). На PACKING после take-to-work оба
 * задания были именно такими, поэтому перебираем участки и берём тот, где
 * кандидаты действительно есть.
 */
async function sectionWithCandidates(
  page: Page,
  sections: { id: number }[],
): Promise<{ sectionId: number; tasks: BoardTask[] }> {
  for (const section of sections) {
    const tasks = boardTasks((await fetchBoardViaUI(page, section.id)).tasks);
    if (selectableTasks(tasks).length >= 2) return { sectionId: section.id, tasks };
  }
  throw new Error(
    "Ни на одном участке не нашлось двух доступных заданий — набор для проверки не собран",
  );
}
test.describe("@ui Дневной план: занятое задание не кандидат (#301)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("задание чужого плана скрыто из кандидатов и не уходит в новый план", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;

    // ── Сетап: живые задания доски ───────────────────────────────────────
    const sku = `E2E-PLAN-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const packing = await apiGetSectionByCode("PACKING");

    await apiAddRemainder(
      product.id,
      raw.id,
      200,
      "E2E #301: начальный остаток сырья",
      { length_mm: 2700 },
    );

    // Две позиции: одна уйдёт в первый план (станет занятой), вторая
    // останется свободным кандидатом — на ней проверяются счётчик,
    // «Выделить все» и подтверждение без 409.
    const rows = [0, 1].map((n) => ({
      sku,
      name: `Позиция дневного плана ${n}`,
      raw_stock: 200,
      color: "серебро",
      qty_per_27: 50,
      length_m: 2.7,
      packaging: `Упаковка ${n}`,
      output_length_m: 2.7,
      output_qty: 50,
      west: 50,
      east: 0,
      kind: "ГП",
    }));
    const imported = await apiSimulatePlanImport(rows);
    await apiApplyChangeSet(imported.production_plan_id, imported.change_set_id);

    await page.goto("/planning");
    await waitForPlanningTableViaUI(page);
    const approved = new Set<number>();
    for (let attempt = 0; attempt < 24 && approved.size < rows.length; attempt++) {
      const position = await findApprovablePositionViaUI(page);
      if (!position || approved.has(position.id)) {
        await page.waitForTimeout(500);
        continue;
      }
      await approvePositionViaUI(page, position);
      approved.add(position.id);
    }
    expect(approved.size, "утверждены обе позиции плана").toBe(rows.length);
    for (const positionId of approved) {
      await takeToWorkViaUI(page, { id: positionId, sku } as ApprovablePosition);
    }

    // ── Шаг 0: на доске есть selectable-кандидаты ────────────────────────
    const sections = (await apiGetSections()) as { id: number }[];
    const { sectionId, tasks: before } = await sectionWithCandidates(page, sections);
    const free = selectableTasks(before);
    expect(free.length, "на доске есть задания, доступные для плана").toBeGreaterThan(1);
    const takenId = free[0].id;
    const freeId = free[1].id;

    // ── Шаг 1: первое задание уходит в дневной план через UI ────────────
    await page.goto(`/section-tasks/${sectionId}`);
    await planTab(page).click();
    await page.getByRole("button", { name: "Создать план", exact: true }).click();
    await fillPlanDate(page);
    await expandBoardGroupsViaUI(page);

    const takenRow = rowById(page, takenId);
    await expect(takenRow, "кандидат виден до создания плана").toBeVisible();
    await takenRow.click();
    // Отбор обязан состояться: иначе «Подтвердить» навсегда останется
    // disabled и падение укажет не на ту причину.
    await expect(takenRow, "клик по строке не дал отбора").toHaveAttribute(
      "aria-selected",
      "true",
      { timeout: 5_000 },
    );
    await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
    await expect(page.getByText("План №1", { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    // Признак «занято» доска теперь отдаёт.
    const after = boardTasks((await fetchBoardViaUI(page, sectionId)).tasks);
    const takenTask = after.find((task) => task.id === takenId);
    expect(takenTask, "задание плана осталось на доске").toBeTruthy();
    expect(takenTask?.in_daily_plan, "доска пометила задание как занятое").toBe(true);

    // ── Шаг 1.5: режим просмотра — задание плана остаётся видимым ───────
    //
    // «Все задания участка» — это картина участка, а не набор кандидатов
    // (docs/daily-plans-spec.md, «Режим `План`»). Регресс: скрытие занятых
    // применялось и здесь, и половина строк участка исчезала из просмотра.
    await page.getByRole("button", { name: "Все задания участка", exact: true }).click();
    await expandBoardGroupsViaUI(page);
    await expect(
      rowById(page, takenId),
      "в режиме просмотра задание плана должно оставаться на доске",
    ).toHaveCount(1);
    await expect(rowById(page, freeId), "свободное задание тоже видно").toHaveCount(1);

    // ── Шаг 2: режим создания плана — занятое задание не кандидат ────────
    //
    // Сначала снимаем выбор плана кнопкой «Все задания участка»: после
    // создания плана приложение выбирает его, и тогда вкладка «План» показывает
    // состав ЭТОГО плана, а не кандидатов (`planBoardTasks` в
    // `SectionsTasksPage`: кандидаты — только когда ни один план не выбран).
    // Это и есть путь мастера: чтобы завести второй план, он сперва вернулся
    // к списку заданий участка.
    await page.getByRole("button", { name: "Все задания участка", exact: true }).click();
    await page.getByRole("button", { name: "Создать план", exact: true }).click();
    await fillPlanDate(page);
    await expandBoardGroupsViaUI(page);

    await expect(
      rowById(page, takenId),
      "задание из плана не должно появляться среди кандидатов",
    ).toHaveCount(0);
    // Свободное — показывается: без этого первая проверка ничего не значит.
    await expect(rowById(page, freeId)).toHaveCount(1);

    // «Выделить все» не должно подтянуть занятое задание.
    const selectAll = page.getByRole("button", { name: /^Выделить все/ });
    await expect(selectAll).toBeVisible();
    await selectAll.click();

    const candidateCount = await candidateRows(page).count();
    expect(candidateCount, "после «Выделить все» видны кандидаты").toBeGreaterThan(0);
    await expect(
      page.getByText(`Выбрано заданий: ${candidateCount}`),
      "счётчик равен числу кандидатов, а не строк доски",
    ).toBeVisible();

    // ── Шаг 3: подтверждение из показанных строк не даёт 409 ─────────────
    const conflicts: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes("/api/daily-plans") && response.status() === 409) {
        conflicts.push(409);
      }
    });
    await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
    await expect(page.getByText("План №2", { exact: false })).toBeVisible({
      timeout: 15_000,
    });
    expect(conflicts, "подтверждение из показанных строк не должно дать 409").toEqual([]);

    // Занятое задание осталось в первом плане: серверная защита на месте и
    // фронт её не обошёл.
    const finalBoard = boardTasks((await fetchBoardViaUI(page, sectionId)).tasks);
    expect(
      finalBoard.find((task) => task.id === takenId)?.in_daily_plan,
      "первый план не тронут вторым",
    ).toBe(true);
  });
});