import type { Locator } from "@playwright/test";

import { apiEnsureCatalogProduct, apiGetSectionByCode } from "./api-helpers";
import { expect, test, type Page } from "./fixtures";
import { ARRIVAL_BUDGET_MS, gotoRoute } from "./route-arrival.mjs";

/**
 * @ui-narrow — E2E режима оптимальных ширин предпросмотра остатков (#484,
 * эпик #475; интеграция — #483, спека `docs/specs/preview-column-widths.md`).
 *
 * Что доказывается в реальном браузере:
 *
 * - **Ширины колонок не «дышат»**: до и после прокрутки виртуализированной
 *   таблицы `getBoundingClientRect` заголовков и `<col>` совпадает (допуск 1 px).
 *   Поиск, сортировка и переключение чипа ширины не меняют; прокрутка не
 *   сбрасывается (при том же числе строк).
 * - **Предсказанная высота строки = фактическая** (`|predicted − actual| ≤ 1 px`)
 *   по каждой отрисованной строке; строка-нарушитель называется в сообщении.
 * - **Полный текст**: под флагом «Наименование» и «Ошибки» переносятся, а не
 *   обрезаются, `title` сохранён.
 * - **Пилюли «Операций»**: доля строк с обрезанной пилюлей не выше лимита
 *   текущего фикса на этой ширине (`pillsTruncationLimitAtWidth`, отдаётся
 *   таблицей в `data-pills-limit-share`).
 * - **Без флага** — прежнее поведение: `truncate` наименования и текущие доли.
 *
 * Высоты (средняя строка, p95, суммарная) под обоими режимами печатаются в
 * лог и в аннотации отчёта: проходного порога у них нет, это вход для #485.
 *
 * Данные — синтетический TSV, вставляемый из буфера обмена (тот же путь, что
 * у оператора: `useImportClipboardPaste`). 320 строк проходят порог
 * виртуализации (300), поэтому прокрутка действительно меняет монтированные
 * строки. Артикулы создаются через API в `beforeEach`.
 */

const PRODUCTS: Array<{ sku: string; name: string }> = [
  { sku: "E2E-OPT-01", name: "Плинтус алюминиевый декоративный 2,7 м" },
  { sku: "E2E-OPT-02", name: "Профиль ПВХ с закрывающей планкой" },
  { sku: "E2E-OPT-03", name: "Уголок декоративный алюминиевый" },
  { sku: "E2E-OPT-04", name: "Наличник телескопический с фрезеровкой" },
  { sku: "E2E-OPT-05", name: "Соединитель профиля скрытого монтажа" },
  { sku: "E2E-OPT-06", name: "Заглушка торцевая для профиля" },
  {
    sku: "E2E-OPT-LONG",
    name: "Соединитель декоративный армированный для профиля скрытого монтажа с уплотнителем",
  },
  {
    sku: "E2E-OPT-OUTLIER",
    name:
      "Профиль алюминиевый анодированный декоративный с терморазрывом " +
      "и интегрированным уплотнителем для фасадных конструкций",
  },
];

/**
 * Наборы операций из сидов. Длинные ряды нарочно дают обрезку на узкой
 * таблице — иначе доля обрезанных пилюль была бы нулевой и ничего не
 * доказывала.
 */
const OPERATION_SETS = [
  "",
  "Сверловка",
  "Сверловка, Серебро",
  "Сверловка, Окно, Серебро",
  "",
  "Дробеструй, Окно",
  "Сверловка, Серебро",
  // Один тяжёлый ряд на восемь: пилюли действительно упираются в ширину, но
  // не диктуют её всей таблице, как было бы при каждом втором ряде.
  "Сверловка, Дробеструй, Окно, Гребенка, Серебро, Золото, Чёрный, Медь, Титан",
];

const ROW_COUNT = 320;

const SPG_HEADING = "Группы хранения и производства";
const SEARCH_PLACEHOLDER = "Код 1С, артикул или наименование…";

/** Переход на /spg с query-флагом — через канон ожидания документа (#289). */
async function arriveAtSpgWithFlag(page: Page, optimal: boolean): Promise<void> {
  const heading = page.getByRole("heading", { name: SPG_HEADING });
  const url = optimal ? "/spg?spgColumnWidths=optimal" : "/spg";
  await gotoRoute(page, url, {
    waitForRoute: (budgetMs) =>
      expect(heading)
        .toBeVisible({ timeout: budgetMs })
        .then(
          () => true,
          () => false,
        ),
    log: (line) => console.log(line),
  });
  await expect(heading).toBeVisible({ timeout: ARRIVAL_BUDGET_MS });
}

/**
 * Синтетический лист ручного шаблона. Каждая 9-я строка — несуществующий
 * артикул: она даёт длинный текст «Ошибок» (и чип «Ошибки»), остальные —
 * валидные строки с пилюлями. Длинные наименования идут каждые 8 строк, чтобы
 * они попадали в первый экран и реально переносились.
 */
function buildPreviewTsv(sectionName: string): string {
  const header = [
    "Артикул",
    "Количество",
    "Статус качества",
    "Операции",
    "Участок",
    "Комментарий",
    "Длина",
  ];
  const rows: string[][] = [header];
  for (let index = 0; index < ROW_COUNT; index += 1) {
    const isInvalid = index % 9 === 8;
    const product = PRODUCTS[index % PRODUCTS.length];
    rows.push([
      isInvalid ? `E2E-MISSING-${index}-LONG-TAIL-НЕ-В-КАТАЛОГЕ` : product.sku,
      String(10 + (index % 90)),
      "Годный",
      OPERATION_SETS[index % OPERATION_SETS.length],
      sectionName,
      `E2E-предпросмотр-${index}`,
      "2,7",
    ]);
  }
  return rows.map((row) => row.join("\t")).join("\n");
}

/** Открыть диалог и вставить лист из буфера; вернуть таблицу предпросмотра. */
async function openPreviewFromClipboard(
  page: Page,
  tsv: string,
  expectedLayout: "optimal" | "baseline",
): Promise<{ dialog: Locator; table: Locator }> {
  await page.getByRole("button", { name: "Импорт из Excel" }).click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Импорт остатков" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  // Ввод из буфера — обработчик `paste` на document, а не поле ввода.
  await dialog.evaluate((_node, text) => {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    document.dispatchEvent(
      new ClipboardEvent("paste", { clipboardData: data, bubbles: true }),
    );
  }, tsv);

  const table = dialog.locator("table").first();
  await expect(table).toHaveAttribute("data-column-layout", expectedLayout, {
    timeout: 30_000,
  });
  await expect(dialog.locator("tbody tr[data-row-key]").first()).toBeVisible({
    timeout: 30_000,
  });
  return { dialog, table };
}

interface Widths {
  ths: number[];
  cols: number[];
}

async function measureWidths(table: Locator): Promise<Widths> {
  return table.evaluate((element) => ({
    ths: Array.from(element.querySelectorAll("thead th")).map(
      (th) => th.getBoundingClientRect().width,
    ),
    cols: Array.from(element.querySelectorAll("colgroup col")).map(
      (col) => col.getBoundingClientRect().width,
    ),
  }));
}

function expectWidthsEqual(
  before: Widths,
  after: Widths,
  label: string,
  tolerance = 1,
): void {
  expect(after.ths, `${label}: число колонок в шапке`).toHaveLength(before.ths.length);
  before.ths.forEach((width, index) => {
    expect(
      Math.abs(after.ths[index] - width),
      `${label}: ширина th[${index}] ${width.toFixed(2)} → ${after.ths[index].toFixed(2)} px`,
    ).toBeLessThanOrEqual(tolerance);
  });
  // Ширины `<col>` Chrome отдаёт только когда таблица разложена; сравниваем,
  // если браузер их вернул (нулевые значения ничего не доказывают).
  if (before.cols.some((width) => width > 0) && after.cols.some((width) => width > 0)) {
    expect(after.cols, `${label}: число колонок в colgroup`).toHaveLength(
      before.cols.length,
    );
    before.cols.forEach((width, index) => {
      expect(
        Math.abs(after.cols[index] - width),
        `${label}: ширина col[${index}] ${width.toFixed(2)} → ${after.cols[index].toFixed(2)} px`,
      ).toBeLessThanOrEqual(tolerance);
    });
  }
}

interface RowMetric {
  key: number;
  actual: number;
  predicted: number | null;
}

async function measureRows(table: Locator): Promise<RowMetric[]> {
  return table.evaluate((element) =>
    Array.from(element.querySelectorAll("tbody tr[data-row-key]")).map((row) => {
      const tr = row as HTMLTableRowElement;
      return {
        key: Number(tr.dataset.rowKey),
        actual: tr.getBoundingClientRect().height,
        predicted: tr.dataset.predictedHeight
          ? Number(tr.dataset.predictedHeight)
          : null,
      };
    }),
  );
}

interface PillMetric {
  rowsWithPills: number;
  truncatedRows: number;
}

/** Строка считается обрезанной, если хотя бы одна подпись пилюли не влезла. */
async function measurePills(table: Locator): Promise<PillMetric> {
  return table.evaluate((element) => {
    const rows = Array.from(element.querySelectorAll("tbody tr[data-row-key]"));
    let rowsWithPills = 0;
    let truncatedRows = 0;
    for (const row of rows) {
      // Колонка «Операции» — девятая (шеврон + 11 содержательных + сброс).
      const cell = row.querySelectorAll("td")[8];
      const pillRow = cell?.querySelector("div.flex");
      if (!pillRow) continue;
      rowsWithPills += 1;
      const labels = Array.from(pillRow.querySelectorAll("span.truncate"));
      const clippedLabel = labels.some(
        (label) => label.scrollWidth > label.clientWidth + 1,
      );
      if (clippedLabel || pillRow.scrollWidth > pillRow.clientWidth + 1) {
        truncatedRows += 1;
      }
    }
    return { rowsWithPills, truncatedRows };
  });
}

function percentile(values: number[], share: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.floor(share * (sorted.length - 1)));
  return sorted[index];
}

interface HeightReport {
  avg: number;
  p95: number;
  total: number;
  predictedTotal: number | null;
  rowCount: number;
}

async function measureHeights(
  table: Locator,
  rows: RowMetric[],
): Promise<HeightReport> {
  const scroll = await table.locator("xpath=..").evaluate((element) => ({
    scrollHeight: element.scrollHeight,
  }));
  const predictedTotalAttribute = await table.getAttribute("data-predicted-total-height");
  const values = rows.map((row) => row.actual);
  const avg = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  return {
    avg,
    p95: percentile(values, 0.95),
    total: scroll.scrollHeight,
    predictedTotal:
      predictedTotalAttribute === null ? null : Number(predictedTotalAttribute),
    rowCount: rows.length,
  };
}

/**
 * Предпросмотр ходит POST'ом, а поиск/сортировка лежат в `FormData` — в URL
 * их нет. Ждём **ответ** по телу запроса: запрос без ответа ещё не значит,
 * что таблица перерисовалась, и следующая проверка читала бы прошлый лист.
 */
function waitPreviewResponse(
  page: Page,
  matches: (body: string) => boolean,
): ReturnType<Page["waitForResponse"]> {
  return page.waitForResponse((response) => {
    if (!response.url().includes("/stock/import/remainders/preview")) return false;
    return matches(response.request().postData() ?? "");
  });
}

function logMetrics(mode: string, report: Record<string, unknown>): void {
  const line = `[spg-widths] ${mode} ${JSON.stringify(report)}`;
  console.log(line);
  test.info().annotations.push({ type: `spg-widths-${mode}`, description: line });
}

test.describe("@ui @ui-narrow Ширины колонок предпросмотра остатков (#484)", () => {
  test.beforeEach(async ({ loginAsAdmin }) => {
    await loginAsAdmin();
    await Promise.all(
      PRODUCTS.map((product) =>
        apiEnsureCatalogProduct({
          sku: product.sku,
          name: product.name,
          lengthsMm: [2700],
        }),
      ),
    );
  });

  test("под флагом: ширины не дышат, высота предсказана, текст виден", async ({
    page,
  }) => {
    test.slow();
    const rawSection = await apiGetSectionByCode("RAW_STOCK");
    const tsv = buildPreviewTsv(rawSection.name);

    await arriveAtSpgWithFlag(page, true);
    const { dialog, table } = await openPreviewFromClipboard(page, tsv, "optimal");

    // ── 1. Ширины до и после прокрутки ────────────────────────────────
    const widthsTop = await measureWidths(table);
    const firstKeyBefore = await dialog
      .locator("tbody tr[data-row-key]")
      .first()
      .getAttribute("data-row-key");
    const container = table.locator("xpath=..");
    await container.evaluate((element) => {
      element.scrollTop = Math.max(0, element.scrollHeight * 0.45);
    });
    // Скролл действительно сменил смонтированные строки — иначе сравнение
    // ширин ничего не доказывает.
    await expect
      .poll(
        () =>
          dialog
            .locator("tbody tr[data-row-key]")
            .first()
            .getAttribute("data-row-key"),
        { message: "прокрутка не сменила виртуализированные строки" },
      )
      .not.toBe(firstKeyBefore);
    const widthsAfterScroll = await measureWidths(table);
    expectWidthsEqual(widthsTop, widthsAfterScroll, "после прокрутки");

    // ── 2. Предсказанная высота = фактическая ─────────────────────────
    const rowsAfterScroll = await measureRows(table);
    expect(rowsAfterScroll.length).toBeGreaterThan(5);
    const heightDiffs: number[] = [];
    for (const row of rowsAfterScroll) {
      expect(row.predicted, `строка ${row.key}: нет data-predicted-height`).not.toBeNull();
      const diff = Math.abs((row.predicted as number) - row.actual);
      heightDiffs.push(diff);
      expect(
        diff,
        `строка ${row.key}: предсказано ${row.predicted} px, фактически ${row.actual.toFixed(2)} px`,
      ).toBeLessThanOrEqual(1);
    }
    // Строки разной высоты: иначе проверка выше прошла бы на одинаковых 29 px.
    const heights = new Set(rowsAfterScroll.map((row) => Math.round(row.actual)));
    expect(
      heights.size,
      `видимые строки одной высоты (${[...heights].join(", ")}) — переносы не задействованы`,
    ).toBeGreaterThan(1);
    expect(
      rowsAfterScroll.some((row) => row.actual > 33),
      "нет видимой строки выше 33 px — длинные наименования не переносятся",
    ).toBeTruthy();

    // ── 3. Пилюли: доля обрезанных не выше лимита текущего фикса ───────
    const pills = await measurePills(table);
    const pillsLimitAttribute = await table.getAttribute("data-pills-limit-share");
    expect(pillsLimitAttribute, "таблица не отдала лимит обрезки пилюль").not.toBeNull();
    const pillsLimit = Number(pillsLimitAttribute);
    const pillsShare = pills.rowsWithPills === 0 ? 0 : pills.truncatedRows / pills.rowsWithPills;
    expect(pills.rowsWithPills, "на видимых строках нет пилюль «Операций»").toBeGreaterThan(0);
    expect(pillsShare, "доля обрезанных пилюль выше лимита текущего фикса").toBeLessThanOrEqual(
      pillsLimit,
    );

    const heightReport = await measureHeights(table, rowsAfterScroll);
    logMetrics("optimal", {
      tableWidth: (await table.evaluate((element) => element.getBoundingClientRect().width)),
      widthsTop: widthsTop.ths.map((width) => Number(width.toFixed(2))),
      widthsAfterScroll: widthsAfterScroll.ths.map((width) => Number(width.toFixed(2))),
      avgRowPx: Number(heightReport.avg.toFixed(2)),
      p95RowPx: Number(heightReport.p95.toFixed(2)),
      maxHeightDiffPx: Number(Math.max(...heightDiffs).toFixed(2)),
      totalTableScrollPx: heightReport.total,
      predictedTotalPx: heightReport.predictedTotal,
      visibleRows: heightReport.rowCount,
      pillsTruncatedRows: pills.truncatedRows,
      pillsRows: pills.rowsWithPills,
      pillsShare: Number(pillsShare.toFixed(4)),
      pillsLimit: Number(pillsLimit.toFixed(4)),
    });

    // ── 4. Поиск, сортировка, чип: ширины те же, скролл не сброшен ─────
    await container.evaluate((element) => {
      element.scrollTop = 1200;
    });
    const scrollBeforeFilters = await container.evaluate((element) => element.scrollTop);
    expect(scrollBeforeFilters, "прокрутка не встала на 1200 px").toBeGreaterThan(1000);

    const search = dialog.getByPlaceholder(SEARCH_PLACEHOLDER);
    const searchResponse = waitPreviewResponse(
      page,
      (body) => body.includes('name="search"') && body.includes("E2E"),
    );
    await search.fill("E2E");
    await searchResponse;
    expectWidthsEqual(widthsTop, await measureWidths(table), "после поиска");
    await expect
      .poll(() => container.evaluate((element) => element.scrollTop), {
        message: "поиск по совпадающему запросу сбросил прокрутку",
      })
      .toBeGreaterThan(1000);

    // Поиск не сбрасываем: «E2E» совпадает со всеми строками листа, поэтому
    // сортировка ниже идёт на том же наборе — так проверяется именно то, что
    // смена порядка не трогает ширины и прокрутку. Пустой запрос вернулся бы
    // из кэша предпросмотра и нового сетевого запроса не дал бы.

    // Шапка таблицы уезжает вместе с содержимым: сортировку жмём программно,
    // иначе пришлось бы самим вернуть прокрутку вверх и доказывать не то.
    const sortResponse = waitPreviewResponse(page, (body) => body.includes("sku:"));
    await dialog
      .getByRole("button", { name: /^Артикул, сортировка/ })
      .evaluate((element) => (element as HTMLElement).click());
    await sortResponse;
    expectWidthsEqual(widthsTop, await measureWidths(table), "после сортировки");
    await expect
      .poll(() => container.evaluate((element) => element.scrollTop), {
        message: "сортировка сбросила прокрутку",
      })
      .toBeGreaterThan(1000);

    // Чип «Ошибки» меняет число строк; прокрутка на 150 px остаётся валидной
    // (ошибочных строк в листе достаточно) и не должна обнуляться приложением.
    await container.evaluate((element) => {
      element.scrollTop = 150;
    });
    const errorsChip = dialog.getByRole("button", { name: /^Ошибки \d+$/ });
    await errorsChip.click();
    await expect(errorsChip).toHaveAttribute("aria-pressed", "true");
    expectWidthsEqual(widthsTop, await measureWidths(table), "после чипа «Ошибки»");
    await expect
      .poll(() => container.evaluate((element) => element.scrollTop), {
        message: "чип «Ошибки» сбросил прокрутку",
      })
      .toBeGreaterThan(100);
    await errorsChip.click();
    await expect(errorsChip).toHaveAttribute("aria-pressed", "false");

    // Пагинации нет по дизайну: лист показывается целиком.
    await expect(dialog.getByText(/Страница \d+ из \d+/)).toHaveCount(0);

    // ── 5. Полный текст под флагом, title сохранён ────────────────────
    const longSearchResponse = waitPreviewResponse(
      page,
      (body) => body.includes('name="search"') && body.includes("E2E-OPT-LONG"),
    );
    await search.fill("E2E-OPT-LONG");
    await longSearchResponse;
    await expect(dialog.locator("tbody tr[data-row-key]").first()).toBeVisible();

    const nameCell = dialog.locator("tbody tr[data-row-key]").first().locator("td").nth(4);
    await expect(nameCell).toHaveClass(/whitespace-pre-line/);
    await expect(nameCell).not.toHaveClass(/truncate/);
    // Ждём именно длинную строку: предыдущий лист тоже переносит текст, и
    // проверка классов сама по себе прошла бы на старых данных.
    await expect(nameCell).toHaveAttribute("title", PRODUCTS[6].name, {
      timeout: 15_000,
    });
    const nameState = await nameCell.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        text: element.textContent ?? "",
        title: element.getAttribute("title") ?? "",
        whiteSpace: style.whiteSpace,
        overflowX: element.scrollWidth - element.clientWidth,
      };
    });
    expect(nameState.whiteSpace).toBe("pre-line");
    expect(nameState.title, "title наименования потерян").toBe(PRODUCTS[6].name);
    expect(nameState.text.trim()).toBe(PRODUCTS[6].name);
    expect(nameState.overflowX, "наименование вылезло за ячейку").toBeLessThanOrEqual(1);

    // «Ошибки»: ищем лист с несуществующими артикулами — текст переносится и
    // не обрезается.
    const invalidSearchResponse = waitPreviewResponse(
      page,
      (body) => body.includes('name="search"') && body.includes("E2E-MISSING"),
    );
    await search.fill("E2E-MISSING");
    await invalidSearchResponse;
    const invalidRow = dialog.locator("tbody tr[data-row-key]").first();
    const errorsCell = invalidRow.locator("td").nth(11);
    await expect(errorsCell).toContainText("не найден", { timeout: 15_000 });
    const errorsState = await errorsCell.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        text: element.textContent ?? "",
        whiteSpace: style.whiteSpace,
        overflowX: element.scrollWidth - element.clientWidth,
      };
    });
    expect(errorsState.whiteSpace).toBe("pre-line");
    expect(errorsState.text).toContain("не найден");
    expect(errorsState.text.length).toBeGreaterThan(30);
    expect(errorsState.overflowX, "ошибки вылезли за ячейку").toBeLessThanOrEqual(1);

    // title операции (пилюли) сохранён. У «E2E-OPT-02» все строки с пилюлями
    // (наборы операций чередуются так, что пустой не попадает); иначе первая
    // строка могла бы оказаться без этапов.
    const pillsSearchResponse = waitPreviewResponse(
      page,
      (body) => body.includes('name="search"') && body.includes("E2E-OPT-02"),
    );
    await search.fill("E2E-OPT-02");
    await pillsSearchResponse;
    const pillTitle = dialog
      .locator("tbody tr[data-row-key]")
      .first()
      .locator("td")
      .nth(8)
      .locator("span[title]")
      .first();
    await expect(pillTitle).toHaveAttribute("title", /: /);
  });

  test("без флага: прежний truncate и текущие доли", async ({ page }) => {
    test.slow();
    const rawSection = await apiGetSectionByCode("RAW_STOCK");
    const tsv = buildPreviewTsv(rawSection.name);

    await arriveAtSpgWithFlag(page, false);
    const { dialog, table } = await openPreviewFromClipboard(page, tsv, "baseline");

    // Прежнее поведение: наименование обрезано одной строкой, title на месте.
    const nameCell = dialog.locator("tbody tr[data-row-key]").first().locator("td").nth(4);
    await expect(nameCell).toHaveClass(/truncate/);
    const baselineName = await nameCell.evaluate((element) => ({
      textOverflow: getComputedStyle(element).textOverflow,
      whiteSpace: getComputedStyle(element).whiteSpace,
      title: element.getAttribute("title") ?? "",
    }));
    expect(baselineName.textOverflow).toBe("ellipsis");
    expect(baselineName.whiteSpace).toBe("nowrap");
    expect(baselineName.title.length).toBeGreaterThan(0);

    // Текущие доли из `remainderPreviewColumns` — не посчитанный режим.
    await expect(table).not.toHaveAttribute("data-predicted-total-height", /.+/);
    const rows = await measureRows(table);
    expect(rows.every((row) => row.predicted === null)).toBeTruthy();

    // Ширины фиксированы и на текущих долях — прокрутка их не меняет.
    const widthsTop = await measureWidths(table);
    const container = table.locator("xpath=..");
    const firstKeyBefore = await dialog
      .locator("tbody tr[data-row-key]")
      .first()
      .getAttribute("data-row-key");
    await container.evaluate((element) => {
      element.scrollTop = Math.max(0, element.scrollHeight * 0.45);
    });
    await expect
      .poll(() =>
        dialog
          .locator("tbody tr[data-row-key]")
          .first()
          .getAttribute("data-row-key"),
      )
      .not.toBe(firstKeyBefore);
    expectWidthsEqual(widthsTop, await measureWidths(table), "baseline после прокрутки");

    const pills = await measurePills(table);
    const heightReport = await measureHeights(table, await measureRows(table));
    logMetrics("baseline", {
      tableWidth: await table.evaluate((element) => element.getBoundingClientRect().width),
      widths: widthsTop.ths.map((width) => Number(width.toFixed(2))),
      avgRowPx: Number(heightReport.avg.toFixed(2)),
      p95RowPx: Number(heightReport.p95.toFixed(2)),
      totalTableScrollPx: heightReport.total,
      visibleRows: heightReport.rowCount,
      pillsTruncatedRows: pills.truncatedRows,
      pillsRows: pills.rowsWithPills,
      pillsShare:
        pills.rowsWithPills === 0
          ? 0
          : Number((pills.truncatedRows / pills.rowsWithPills).toFixed(4)),
    });
  });
});
