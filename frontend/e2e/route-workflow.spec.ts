import { test, expect } from "./fixtures";
import { apiResetAll } from "./api-helpers";
import {
  ensureE2ECatalogViaUI,
  PACKAGING_PLAN_XLS_PATH,
  seedReferenceDataViaUI,
  uploadTestFileViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";
import { errorLabels } from "../src/shared/lib/generated-labels";

/**
 * @ui — канонический E2E: только UI, без прямых fetch к бизнес-API.
 * Setup: Dev Settings → импорт → planning → execution.
 */

test.describe("@ui Route workflow E2E", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // Сброс производственных таблиц перед сценарием: без него вердикт спеки
    // зависит от того, что оставили прошлые прогоны и прошлые версии сида —
    // именно так 13 позиций «конфликтовали» с маршрутами промежуточной
    // итерации, лежавшими в БД стенда (#225). Справочники после сброса сеются
    // заново, поэтому порядок обязателен: сначала reset, потом seed.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("position route info is visible in planning table after import", async ({ page }) => {
    test.slow();
    await ensureE2ECatalogViaUI(page);
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    await uploadTestFileViaUI(page, PACKAGING_PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);

    const rows = page.locator('[id^="plan-position-"]');
    // Таблица плана грузится асинхронно: `count()` сразу после goto видел 0
    // строк на ещё не отрисованной таблице — и тест уходил в `test.skip`.
    // Ждём конкретное состояние (есть строка), а не «сколько бы ни нашлось».
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });

    // Сводная таблица пагинируется (50 строк на страницу по умолчанию), а в
    // «Упаковочном плане» 55 строк: не расширив страницу, «все строки» молча
    // означали бы «50 первых», и хвост плана не проверялся бы вовсе. Сектор
    // футера рисуется только когда строк больше 50 — при меньшем плане его
    // нет, и все строки уже на странице.
    const pageSizeSelect = page.getByRole("combobox", {
      name: "Количество записей на странице",
    });
    if (await pageSizeSelect.isVisible()) {
      await pageSizeSelect.click();
      await page.getByRole("option", { name: "200", exact: true }).click();
    }

    // Счётчик позиций в шапке секции — независимый источник ожидаемого числа
    // строк: по нему ждём, пока отрисуется вся страница, а не первая строка.
    const totalLabel = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Сводная таблица позиций" }) })
      .getByText(/^\d+\s+строк$/)
      .first();
    await expect(totalLabel).toBeVisible({ timeout: 30_000 });
    const total = Number((await totalLabel.innerText()).match(/\d+/)?.[0]);
    // Смена размера страницы перезапрашивает данные: пока таблица не
    // перерисовалась, в DOM остаётся предыдущая страница из 50 строк.
    await expect
      .poll(() => rows.count(), { timeout: 30_000 })
      .toBe(total);

    // Снимок всех строк одним заходом: пока идёт поштучный обход, таблица
    // может перерисоваться (пагинация, поллинг), и строки смешаются со
    // следующей страницей. Ячейки читаются по индексу среди `children` строки:
    // вторая — «Строка», третья — «Артикул», седьмая — «Маршрут», восьмая —
    // «Ошибки» (порядок в PlanPositionRow).
    const planRows = await rows.evaluateAll((rowEls) =>
      rowEls.map((row) => {
        const cells = Array.from(row.children) as HTMLElement[];
        return {
          id: row.id,
          sourceRow: cells[1]?.textContent?.trim() ?? "",
          sku: cells[2]?.textContent?.trim() ?? "",
          route: cells[6]?.textContent?.trim() ?? "",
          errors: cells[7]?.textContent?.trim() ?? "",
        };
      }),
    );
    const describe = (row: (typeof planRows)[number]) =>
      `${row.id} (строка ${row.sourceRow}, ${row.sku}): маршрут «${row.route}», ошибки «${row.errors}»`;

    // Проверка идёт по ВСЕМ строкам импортированного плана, а не по первой:
    // присваивание маршрута обязано покрыть каждую позицию.
    expect(planRows.length, "в таблице отрисован не весь план").toBe(total);

    // Первое: у каждой строки в ячейке маршрута стоит имя, а не плейсхолдер
    // неразрешённого route («Не назначен» / «Нажмите для выбора»).
    expect(
      planRows
        .filter((row) => /Не назначен|Нажмите для выбора/i.test(row.route))
        .map(describe),
      "строки плана остались без маршрута",
    ).toEqual([]);

    // Второе: строка без маршрута в этой таблице выглядит убедительно — backend
    // отдаёт имя маршрута по пересборке из профиля (`route_matcher`), поэтому
    // ячейка «Маршрут» показывает чужое имя и плейсхолдера в ней нет. Единственный
    // след неразрешённого присваивания в UI — код `route_signature_conflict`
    // в колонке «Ошибки». Проверяем его по всем строкам: пока backend-фикс #226
    // не лёг, импорт оставляет несколько таких позиций.
    expect(
      planRows
        .filter((row) => row.errors.includes(errorLabels.route_signature_conflict))
        .map(describe),
      "импорт оставил позиции с конфликтом сигнатуры маршрута",
    ).toEqual([]);
  });

  test("import wizard opens and shows template options", async ({ page }) => {
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    const addFileBtn = page.getByRole("button", { name: /добавить файл/i });
    await expect(addFileBtn).toBeVisible({ timeout: 10_000 });
    await addFileBtn.click();

    const wizard = page.getByRole("dialog");
    await expect(wizard).toBeVisible({ timeout: 10_000 });
    await expect(wizard.getByRole("heading", { name: /импорт|загруз|import/i })).toBeVisible({
      timeout: 10_000,
    });

    // Шаблон импорта выбирается на шаге загрузки, а список приезжает отдельным
    // запросом после открытия визарда — ждём его появления, а не факта диалога.
    const templateSelect = wizard.getByRole("combobox").first();
    await expect(templateSelect).toBeVisible({ timeout: 10_000 });
    await templateSelect.click();
    await expect(page.getByRole("option", { name: /Упаковочная карта РП/i })).toBeVisible({
      timeout: 10_000,
    });

    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 10_000 });
  });
});