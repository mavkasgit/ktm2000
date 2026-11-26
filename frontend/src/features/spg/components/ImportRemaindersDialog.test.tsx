// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Section } from "@/shared/api/sections";
import type { ImportOperationStep } from "@/shared/api/stock";

// Мокаем API-слой: диалог обязан брать участки и операции из справочников,
// а не из литералов в коде.
vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getRemainderImportOperations: vi.fn(),
  getRemainderSheets: vi.fn(),
  previewRemaindersExcel: vi.fn(),
  importRemaindersExcel: vi.fn(),
}));

import { fireEvent, screen, within } from "@testing-library/react";
import { listSections } from "@/shared/api/sections";
import {
  getRemainderImportOperations,
  getRemainderSheets,
  importRemaindersExcel,
  previewRemaindersExcel,
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
  type RemainderImportItem,
  type RemainderImportResponse,
  type RemainderPreviewResponse,
  type RemainderSheet,
} from "@/shared/api/stock";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { remainderPreviewColumns } from "../lib/remainderPreviewColumns";
import {
  ImportRemaindersDialog,
  getImportItemOperationsLabel,
  getImportItemOperationsServerLabel,
} from "./ImportRemaindersDialog";

// Без этого флага React 18 сыплет предупреждения «not configured to support act(...)»
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const makeSection = (overrides: Partial<Section>): Section => ({
  id: 1,
  code: "X",
  name: "X",
  description: null,
  sort_order: 0,
  is_active: true,
  type: "raw_stock",
  icon: null,
  icon_color: null,
  ...overrides,
});

const makeOperation = (overrides: Partial<ImportOperationStep>): ImportOperationStep => ({
  sequence: 0,
  section_code: "S",
  section_name: "S",
  operation_code: "OP",
  operation_name: "OP",
  is_significant: true,
  ...overrides,
});

function mountDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);

  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <ImportRemaindersDialog open onOpenChange={vi.fn()} onSaved={vi.fn()} />
      </QueryClientProvider>,
    );
  });

  return {
    cleanup: () => {
      act(() => root.unmount());
      container.remove();
      queryClient.clear();
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ImportRemaindersDialog", () => {
  it("renders target sections from the server reference, not from hardcoded literals", async () => {
    // Названия участков намеренно НЕ совпадают со старыми литералами
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "ZONE_B", name: "Зона Бета", sort_order: 20 }),
      makeSection({ id: 12, code: "ZONE_A", name: "Зона Альфа", sort_order: 10, type: "wip_stock" }),
      makeSection({ id: 13, code: "MILLING", name: "Фрезеровка", sort_order: 5, type: "production" }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([
      makeOperation({ sequence: 10, operation_code: "OP_FIRST", operation_name: "Первая операция" }),
      makeOperation({ sequence: 20, operation_code: "OP_SECOND", operation_name: "Вторая операция" }),
    ]);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Зона Альфа");
      });
      const text = document.body.textContent ?? "";

      // Участки приходят из справочника, в порядке sort_order с сервера
      expect(text).toContain("Зона Бета");
      expect(text.indexOf("Зона Альфа")).toBeLessThan(text.indexOf("Зона Бета"));
      // Производственные участки не предлагаются как целевые
      expect(text).not.toContain("Фрезеровка");

      // Старые литералы сидов удалены и не подмешиваются как fallback
      expect(text).not.toContain("Склад сырья");
      expect(text).not.toContain("Склад подготовки");
      expect(text).not.toContain("Склад полуфабриката");
      expect(text).not.toContain("Дробеструй");

      // Пример операций — из справочника, в серверном порядке
      expect(text).toContain("Первая операция, Вторая операция");
    } finally {
      cleanup();
    }
  });

  it("на шаге загрузки подсказывает про ОСВ и ручной шаблон", async () => {
    vi.mocked(listSections).mockResolvedValue([]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        const text = document.body.textContent ?? "";
        expect(text).toContain("выгрузка 1С (ОСВ)");
        expect(text).toContain("ручной шаблон");
        expect(text).toContain("тип каждого листа виден на вкладках");
      });
    } finally {
      cleanup();
    }
  });

  it("shows an explicit error when the sections reference fails to load", async () => {
    vi.mocked(listSections).mockRejectedValue(new Error("network down"));
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain(
          "Не удалось загрузить справочники участков и операций",
        );
      });
    } finally {
      cleanup();
    }
  });
});

const makeSheet = (overrides: Partial<RemainderSheet>): RemainderSheet => ({
  index: 0,
  name: "Лист",
  kind: "unknown",
  detected_section_id: null,
  detected_section_name: null,
  ...overrides,
});

const makePreview = (
  overrides: Partial<RemainderPreviewResponse> = {},
): RemainderPreviewResponse => ({
  sheet_name: "Лист",
  source_kind: "manual_template",
  source_token: "test-source-token",
  detected_section_id: null,
  detected_section_name: null,
  total_rows: 0,
  summary: { total: 0, valid: 0, skipped: 0, invalid: 0, quantity_total: 0 },
  section_meta: [],
  items: [],
  items_total: 0,
  limit: 50,
  offset: 0,
  ...overrides,
});

const makeImportResponse = (
  overrides: Partial<RemainderImportResponse> = {},
): RemainderImportResponse => ({
  success: true,
  imported_count: 0,
  errors: [],
  transaction_ids: [],
  ...overrides,
});

/** Выбрать файл в дропзоне — так же, как это делает оператор. */
async function selectFile(name = "остатки.xlsx") {
  // Дропзона появляется только после справочников участков и операций.
  await vi.waitFor(() => {
    expect(document.querySelector('input[type="file"]')).toBeTruthy();
  });
  const input = document.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) throw new Error("В диалоге нет поля файла");
  await act(async () => {
    fireEvent.change(input, { target: { files: [new File(["x"], name)] } });
  });
}

/**
 * Предпросмотр листа, у которого есть участок в шапке: так отвечает сервер на
 * ОСВ-лист (спека §5.2).
 */
function osvPreview(sheetIndex: number, sectionId: number, sectionName: string) {
  const detection = {
    source_kind: "1c_osv" as const,
    detected_section_id: sectionId,
    detected_section_name: sectionName,
    summary: { total: 1, valid: 1, skipped: 0, invalid: 0, quantity_total: 10 },
    section_meta: [
      { source_row_number: 2, status: "valid" as const, target_section_id: sectionId, target_section_name: sectionName },
    ],
    items: [
      makeImportItem({
        source_row_number: 2,
        source_code: `код-${sheetIndex}`,
        target_section_id: sectionId,
        target_section_name: sectionName,
      }),
    ],
    items_total: 1,
    total_rows: 1,
  };
  return makePreview(detection);
}

const makeImportItem = (overrides: Partial<RemainderImportItem>): RemainderImportItem => ({
  source_row_number: 2,
  sku: "OPS-1",
  product_id: null,
  product_name: null,
  quantity: 10,
  source_code: null,
  source_name: null,
  source_unit: null,
  source_quantity_m: null,
  comment: null,
  status: "valid",
  errors: [],
  matched_sku: null,
  warnings: [],
  raw_values: [],
  completed_operations_raw: null,
  completed_stages: [],
  target_section_name: null,
  target_section_id: null,
  quality_state_raw: null,
  quality_state: "good",
  length_raw: null,
  dimensions: null,
  dimensions_label: "—",
  ...overrides,
});

// Подпись ячейки «Операции» — общее правило (#242): прочерк обоим пустым
// состояниям. В запрос фильтра уходит серверная подпись: её собирает
// `getImportItemOperationsServerLabel`, и по ней же сервер ищет строки —
// выбор обязан находить то, что видит глаз, а пустых состояний два.
describe("подпись «Операции» в предпросмотре импорта", () => {
  it("пустая колонка подписывается прочерком", () => {
    expect(getImportItemOperationsLabel(makeImportItem({}))).toBe("—");
  });

  it("печатает имена этапов, а не сырой текст колонки", () => {
    const item = makeImportItem({
      completed_operations_raw: "СЫРОЙ ТЕКСТ ИЗ EXCEL",
      completed_stages: [
        makeOperation({ sequence: 1, operation_code: "DOS", operation_name: "Дробеструй" }),
        makeOperation({ sequence: 2, operation_code: "BLK", operation_name: "Чёрный" }),
      ],
    });
    expect(getImportItemOperationsLabel(item)).toBe("Дробеструй, Чёрный");
  });

  it("неразрешённое значение колонки — прочерк, а не его текст", () => {
    // Сцена не разрешилась в справочник → в баланс уйдёт NULL (ADR-0055 п.6),
    // поэтому и подпись пустая: сырой текст в ячейку не попадает.
    const item = makeImportItem({
      completed_operations_raw: "Что-то неизвестное",
      completed_stages: [],
    });
    expect(getImportItemOperationsLabel(item)).toBe("—");
  });

  it("список фильтра различает два пустых состояния подписями, а не прочерком", () => {
    // Перевода «—» → подпись быть не может: ячейка одна у обоих состояний,
    // а сервер (`_preview_operations_label`) различает их — значит, в список
    // фильтра идут подписи, собранные по `completed_operations_raw`.
    const column = remainderPreviewColumns.find((c) => c.id === "operations")!;
    expect(column.mapValue).toBeUndefined();

    const noColumn = makeImportItem({});
    const emptyCell = makeImportItem({
      completed_operations_raw: "  —  ",
      completed_stages: [],
    });
    expect(getImportItemOperationsServerLabel(noColumn)).toBe(
      OPERATIONS_NOT_RECORDED_LABEL,
    );
    expect(getImportItemOperationsServerLabel(emptyCell)).toBe(OPERATIONS_EMPTY_LABEL);
    expect(getImportItemOperationsServerLabel(noColumn)).not.toBe(
      getImportItemOperationsServerLabel(emptyCell),
    );

    // Обе ячейки печатают прочерк — это подпись, а не различие состояний.
    expect(getImportItemOperationsLabel(noColumn)).toBe("—");
    expect(getImportItemOperationsLabel(emptyCell)).toBe("—");

    expect(
      buildColumnApiParams(
        { operations: new Set([OPERATIONS_EMPTY_LABEL]) },
        {},
        remainderPreviewColumns,
      ),
    ).toEqual({ operations: OPERATIONS_EMPTY_LABEL });
    expect(
      buildColumnApiParams(
        { operations: new Set([OPERATIONS_NOT_RECORDED_LABEL]) },
        {},
        remainderPreviewColumns,
      ),
    ).toEqual({ operations: OPERATIONS_NOT_RECORDED_LABEL });
  });

  it("ответ без completed_stages (null) не роняет сборку фильтра", () => {
    // Предпросмотр ОСВ до правки отдавал null: диалог читал `.length` и
    // падал ошибкой границы раздела ещё до показа строк.
    const item = makeImportItem({
      completed_stages: null as unknown as ImportOperationStep[],
    });
    expect(getImportItemOperationsServerLabel(item)).toBe(
      OPERATIONS_NOT_RECORDED_LABEL,
    );
    expect(getImportItemOperationsLabel(item)).toBe("—");
  });
});

describe("вкладки листов файла остатков", () => {
  it("показывает все листы с типом и выбирает первый лист ОСВ", async () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа", sort_order: 10 }),
      makeSection({ id: 12, code: "PREP", name: "Зона Бета", sort_order: 20 }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
    vi.mocked(getRemainderSheets).mockResolvedValue([
      makeSheet({ index: 0, name: "Импорт остатков", kind: "manual_template" }),
      makeSheet({
        index: 1,
        name: "Склад сырой",
        kind: "1c_osv",
        detected_section_id: 11,
        detected_section_name: "Зона Альфа",
      }),
      makeSheet({
        index: 2,
        name: "Дробь",
        kind: "1c_osv",
        detected_section_id: 12,
        detected_section_name: "Зона Бета",
      }),
      makeSheet({ index: 3, name: "Служебный", kind: "unknown" }),
    ]);
    vi.mocked(previewRemaindersExcel).mockResolvedValue(osvPreview(1, 11, "Зона Альфа"));

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Склад сырой · ОСВ 1С");
      });
      const text = document.body.textContent ?? "";

      // Вкладки — все листы файла, подпись несёт тип листа (спека §9).
      expect(text).toContain("Импорт остатков · шаблон");
      expect(text).toContain("Дробь · ОСВ 1С");
      expect(text).toContain("Служебный · неизвестно");
      // Выбор по умолчанию — первый лист ОСВ, а не первый лист файла.
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalled();
      });
      expect(vi.mocked(previewRemaindersExcel).mock.calls.at(-1)?.[1]?.sheet_index).toBe(1);
    } finally {
      cleanup();
    }
  });

  it("предпросмотр кэшируется по листу: возврат на вкладку не повторяет запрос", async () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа" }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
    vi.mocked(getRemainderSheets).mockResolvedValue([
      makeSheet({ index: 0, name: "Импорт остатков", kind: "manual_template" }),
      makeSheet({ index: 1, name: "Склад сырой", kind: "1c_osv", detected_section_id: 11 }),
    ]);
    vi.mocked(previewRemaindersExcel).mockImplementation(async (_source, opts) =>
      opts?.sheet_index === 1 ? osvPreview(1, 11, "Зона Альфа") : makePreview({ sheet_name: "Импорт остатков" }),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      await vi.waitFor(() => {
        expect(screen.getByRole("button", { name: "Импорт остатков · шаблон" })).toBeTruthy();
      });
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalledTimes(1);
      });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Импорт остатков · шаблон" }));
      });
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalledTimes(2);
      });

      // Возврат на уже загруженный лист берёт кэш, а не новый запрос.
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Склад сырой · ОСВ 1С" }));
      });
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Склад сырой");
      });
      expect(previewRemaindersExcel).toHaveBeenCalledTimes(2);
    } finally {
      cleanup();
    }
  });

  it("новый файл начинает предпросмотр заново, а не берёт чужой кэш", async () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа" }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
    vi.mocked(getRemainderSheets).mockResolvedValue([
      makeSheet({ index: 0, name: "Склад сырой", kind: "1c_osv", detected_section_id: 11 }),
    ]);
    vi.mocked(previewRemaindersExcel).mockResolvedValue(
      osvPreview(0, 11, "Зона Альфа"),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile("первый.xlsx");
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalledTimes(1);
      });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Назад" }));
      });
      await selectFile("второй.xlsx");

      // Ключ кэша — лист и параметры, файла в нём нет: без сброса диалог
      // показал бы предпросмотр прошлого файла.
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalledTimes(2);
      });
    } finally {
      cleanup();
    }
  });
});

describe("пропущенные строки и лист целиком", () => {
  const statusPreview = () =>
    makePreview({
      sheet_name: "Склад сырой",
      source_kind: "1c_osv",
      detected_section_id: 11,
      detected_section_name: "Зона Альфа",
      total_rows: 3,
      summary: { total: 3, valid: 1, skipped: 1, invalid: 1, quantity_total: 5 },
      items_total: 3,
      offset: 0,
      items: [
        makeImportItem({ source_row_number: 2, sku: "RAW-001", quantity: 5, target_section_id: 11 }),
        makeImportItem({
          source_row_number: 3,
          sku: "",
          quantity: null,
          status: "skipped",
          skip_reason: "no_catalog",
          skip_reason_label: "есть в исключениях",
          skip_note: "Нет в каталоге, новые артикулы не заводим",
          source_name: "Уголок 50*50 (нет в каталоге)",
          target_section_id: 11,
        }),
        makeImportItem({
          source_row_number: 4,
          sku: "BAD-001",
          quantity: null,
          status: "invalid",
          errors: ["Остаток меньше одной штуки"],
          target_section_id: 11,
        }),
      ],
    });

  const mockPreviewReferences = () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа" }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
    vi.mocked(getRemainderSheets).mockResolvedValue([
      makeSheet({ index: 0, name: "Склад сырой", kind: "1c_osv", detected_section_id: 11 }),
    ]);
    vi.mocked(previewRemaindersExcel).mockResolvedValue(statusPreview());
  };

  const previewChip = (name: RegExp) =>
    screen.getByRole("button", { name });
  const bodyRowTexts = () =>
    screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.textContent ?? "");

  const mountPreview = async () => {
    const mounted = mountDialog();
    await selectFile();
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain("Всего: 3");
    });
    return mounted;
  };

  it("по умолчанию скрывает пропущенные, но показывает их счётчик", async () => {
    mockPreviewReferences();
    const { cleanup } = await mountPreview();
    try {
      // Годная и ошибочная строки видны, пропущенная — нет.
      expect(document.body.textContent).toContain("RAW-001");
      expect(document.body.textContent).toContain("BAD-001");
      expect(document.body.textContent).not.toContain("Уголок 50*50 (нет в каталоге)");
      expect(document.body.textContent).not.toContain("Пропущено: есть в исключениях");
      // Бейдж в шапке остался: счётчик пропущенных виден без раскрытия.
      expect(document.body.textContent).toContain("Пропущено: 1");
      // Статусного селекта больше нет — категория переключается чипами.
      expect(screen.queryByRole("combobox", { name: "Все строки" })).toBeNull();

      // Пагинации в модалке нет: лист запрошен целиком, футера страниц нет.
      expect(previewRemaindersExcel).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ limit: 5000, offset: 0 }),
      );
      expect(document.body.textContent).not.toContain("Страница ");
    } finally {
      cleanup();
    }
  });

  it("раскладка таблицы фиксированная: ширины не зависят от смонтированных строк", async () => {
    mockPreviewReferences();
    const { cleanup } = await mountPreview();
    try {
      const header = screen.getByRole("columnheader", { name: "Код 1С" });
      const table = header.closest("table");
      expect(table).toBeTruthy();
      // Auto-раскладка считала ширины по содержимому видимых строк: при
      // скролле виртуализатор менял строки, и колонки «перерисовывались».
      expect(table!.className).toContain("table-fixed");

      // Одна `<col>` на шеврон, все колонки спеки и колонку сброса.
      const cols = Array.from(table!.querySelectorAll("colgroup > col")) as HTMLElement[];
      expect(cols).toHaveLength(remainderPreviewColumns.length + 2);
      expect(cols.slice(1, -1).map((col) => col.style.width)).toEqual(
        remainderPreviewColumns.map((column) => column.width),
      );
    } finally {
      cleanup();
    }
  });

  it("чипы изолируют категорию, повторный клик и сброс возвращают дефолт", async () => {
    mockPreviewReferences();
    const { cleanup } = await mountPreview();
    try {
      const allRows = bodyRowTexts().length;
      const skippedChip = previewChip(/^Пропущенные \d+$/);
      const errorsChip = previewChip(/^Ошибки \d+$/);
      expect(skippedChip.getAttribute("aria-pressed")).toBe("false");
      expect(errorsChip.getAttribute("aria-pressed")).toBe("false");

      // «Пропущенные» — только skipped, чип включён.
      await act(async () => {
        fireEvent.click(skippedChip);
      });
      await vi.waitFor(() => {
        expect(bodyRowTexts()).toHaveLength(1);
      });
      expect(document.body.textContent).toContain("Пропущено: есть в исключениях");
      expect(document.body.textContent).not.toContain("RAW-001");
      expect(previewChip(/^Пропущенные \d+$/).getAttribute("aria-pressed")).toBe("true");
      expect(previewChip(/^Ошибки \d+$/).getAttribute("aria-pressed")).toBe("false");

      // Повторный клик по активному — дефолт.
      await act(async () => {
        fireEvent.click(previewChip(/^Пропущенные \d+$/));
      });
      await vi.waitFor(() => {
        expect(bodyRowTexts()).toHaveLength(allRows);
      });
      expect(previewChip(/^Пропущенные \d+$/).getAttribute("aria-pressed")).toBe("false");

      // «Ошибки» взаимоисключающий: только invalid.
      await act(async () => {
        fireEvent.click(previewChip(/^Ошибки \d+$/));
      });
      await vi.waitFor(() => {
        expect(bodyRowTexts()).toHaveLength(1);
      });
      expect(document.body.textContent).toContain("BAD-001");
      expect(document.body.textContent).not.toContain("RAW-001");
      expect(previewChip(/^Ошибки \d+$/).getAttribute("aria-pressed")).toBe("true");

      // «Сбросить» возвращает дефолт.
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
      });
      await vi.waitFor(() => {
        expect(bodyRowTexts()).toHaveLength(allRows);
      });
      expect(previewChip(/^Ошибки \d+$/).getAttribute("aria-pressed")).toBe("false");
    } finally {
      cleanup();
    }
  });

  it("подпись пропуска — одна строка, чипы не шлют сетевой запрос", async () => {
    mockPreviewReferences();
    const { cleanup } = await mountPreview();
    try {
      const initialCalls = vi.mocked(previewRemaindersExcel).mock.calls.length;

      await act(async () => {
        fireEvent.click(previewChip(/^Пропущенные \d+$/));
      });
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Пропущено: есть в исключениях");
      });
      // Переключение категории — клиентская фильтрация: лист уже на экране.
      expect(previewRemaindersExcel).toHaveBeenCalledTimes(initialCalls);

      // Базовая подпись — одна строка: перенос поднимал высоту строки таблицы
      // выше общего ритма TABLE_ROW_COMPACT (40px, ADR-0030).
      const skipCell = screen
        .getByText("Пропущено: есть в исключениях")
        .closest("td");
      expect(skipCell?.className).toContain("whitespace-nowrap");
      // Заметка реестра не дублирует подпись второй строкой.
      expect(document.body.textContent).not.toContain(
        "Нет в каталоге, новые артикулы не заводим",
      );
    } finally {
      cleanup();
    }
  });

  it("смена сортировки не отправляет файл повторно, а идёт по токену", async () => {
    mockPreviewReferences();
    const { cleanup } = await mountPreview();
    try {
      expect(previewRemaindersExcel).toHaveBeenCalledTimes(1);
      const firstSource = vi.mocked(previewRemaindersExcel).mock.calls[0][0];
      expect(firstSource).not.toBeNull();

      // Клик по шапке сортировки — новый запрос, но без файла: источник уже
      // на сервере под токеном (#472).
      const skuSort = screen.getByRole("button", { name: /^Артикул, сортировка/ });
      expect(skuSort).toBeTruthy();
      await act(async () => {
        fireEvent.click(skuSort);
      });
      await vi.waitFor(() => {
        expect(previewRemaindersExcel).toHaveBeenCalledTimes(2);
      });
      const secondCall = vi.mocked(previewRemaindersExcel).mock.calls[1];
      expect(secondCall[0]).toBeNull();
      expect(secondCall[1]?.source_token).toBe("test-source-token");
    } finally {
      cleanup();
    }
  });
});

describe("колонки предпросмотра ОСВ", () => {
  it("печатает код 1С, наименование и метры, а шапка совпадает с телом", async () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа" }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
    vi.mocked(getRemainderSheets).mockResolvedValue([
      makeSheet({ index: 0, name: "Склад сырой", kind: "1c_osv", detected_section_id: 11 }),
    ]);
    vi.mocked(previewRemaindersExcel).mockResolvedValue(
      makePreview({
        sheet_name: "Склад сырой",
        source_kind: "1c_osv",
        detected_section_id: 11,
        detected_section_name: "Зона Альфа",
        total_rows: 1,
        summary: { total: 1, valid: 1, skipped: 0, invalid: 0, quantity_total: 2367 },
        items_total: 1,
        items: [
          makeImportItem({
            source_row_number: 2,
            source_code: "20933",
            source_name: "Кант универсальный 26мм 2,70м (ЮП-2616) алюминий",
            source_unit: "м",
            source_quantity_m: 6391.5,
            product_name: "Кант универсальный 26мм",
            quantity: 2367,
            dimensions: { length_mm: 2700 },
            dimensions_label: "2,7 м",
            target_section_id: 11,
            target_section_name: "Зона Альфа",
          }),
        ],
      }),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      await vi.waitFor(() => {
        expect(screen.getAllByRole("columnheader").some((cell) => cell.textContent === "Код 1С")).toBe(true);
      });

      const headers = screen.getAllByRole("columnheader");
      // Порядок спеки §10.1; пустые — шеврон строки и сброс фильтров.
      const labels = headers.map((cell) => cell.textContent ?? "");
      expect(labels.slice(1, -1)).toEqual([
        "#",
        "Код 1С",
        "Артикул",
        "Наименование",
        "Кол-во, шт",
        "Метры",
        "Длина",
        "Операции",
        "Качество",
        "Участок",
        "Ошибки",
      ]);

      // Колонки источника не фильтруются и не сортируются: в шапке — подпись,
      // а не кнопка попапера или сортировки (ADR-0038 §4).
      for (const label of ["Код 1С", "Наименование", "Метры"]) {
        const header = headers.find((cell) => cell.textContent === label);
        expect(header, `шапка ${label}`).toBeTruthy();
        expect(within(header!).queryByRole("button"), `кнопка в «${label}»`).toBeNull();
      }

      const bodyRow = screen.getAllByRole("row")[1];
      const cells = within(bodyRow).getAllByRole("cell");
      const byHeader = new Map(
        labels.map((label, index) => [label, cells[index]?.textContent ?? ""]),
      );
      expect(byHeader.get("Код 1С")).toBe("20933");
      expect(byHeader.get("Артикул")).toBe("OPS-1");
      expect(byHeader.get("Наименование")).toBe("Кант универсальный 26мм");
      // Штуки — fmtQty, метры — fmtQtyPrecise (дробь живая, спека §10.1).
      expect(byHeader.get("Кол-во, шт")).toBe("2367");
      expect(byHeader.get("Метры")).toBe("6391,5");
      expect(byHeader.get("Длина")).toBe("2,7 м");

      // Наименование 1С — в подсказке ячейки: в колонку оно не влезает.
      const nameCell = cells[labels.indexOf("Наименование")];
      expect(nameCell.getAttribute("title")).toBe(
        "Кант универсальный 26мм 2,70м (ЮП-2616) алюминий",
      );

      // Строка держит один ритм TABLE_ROW_COMPACT: текстовые ячейки не
      // переносятся, полное значение — в title. Перенос остаётся «Ошибкам».
      for (const label of ["Код 1С", "Артикул", "Длина"]) {
        const cell = cells[labels.indexOf(label)];
        expect(cell.getAttribute("title"), `title в «${label}»`).toBeTruthy();
        expect(cell.className, `одна строка в «${label}»`).toContain("whitespace-nowrap");
      }
      expect(nameCell.className).toContain("truncate");
      const codeCell = cells[labels.indexOf("Код 1С")];
      expect(codeCell.getAttribute("title")).toBe("20933");
    } finally {
      cleanup();
    }
  });
});

/** Таблица результата как список строк по именам колонок. */
function tableRowsByHeader(): Map<string, string>[] {
  const rows = screen.getAllByRole("row");
  const header = within(rows[0])
    .getAllByRole("columnheader")
    .map((cell) => cell.textContent ?? "");
  return rows.slice(1).map(
    (row) =>
      new Map(
        header.map((name, index) => [
          name,
          within(row).getAllByRole("cell")[index]?.textContent ?? "",
        ]),
      ),
  );
}

describe("импорт всех листов ОСВ", () => {
  const osvSheets = () => [
    makeSheet({ index: 0, name: "Импорт остатков", kind: "manual_template" }),
    makeSheet({
      index: 1,
      name: "Склад сырой",
      kind: "1c_osv",
      detected_section_id: 11,
      detected_section_name: "Зона Альфа",
    }),
    makeSheet({
      index: 2,
      name: "Дробь",
      kind: "1c_osv",
      detected_section_id: 12,
      detected_section_name: "Зона Бета",
    }),
  ];

  const mockReferences = () => {
    vi.mocked(listSections).mockResolvedValue([
      makeSection({ id: 11, code: "RAW", name: "Зона Альфа", sort_order: 10 }),
      makeSection({ id: 12, code: "PREP", name: "Зона Бета", sort_order: 20 }),
    ]);
    vi.mocked(getRemainderImportOperations).mockResolvedValue([]);
  };

  it("применяет листы последовательно и показывает сводку по листам", async () => {
    mockReferences();
    vi.mocked(getRemainderSheets).mockResolvedValue(osvSheets());
    vi.mocked(previewRemaindersExcel).mockImplementation(async (_source, opts) =>
      opts?.sheet_index === 2
        ? makePreview({
            sheet_name: "Дробь",
            source_kind: "1c_osv",
            detected_section_id: 12,
            detected_section_name: "Зона Бета",
            summary: { total: 4, valid: 3, skipped: 0, invalid: 1, quantity_total: 3 },
          })
        : makePreview({
            sheet_name: "Склад сырой",
            source_kind: "1c_osv",
            detected_section_id: 11,
            detected_section_name: "Зона Альфа",
            summary: { total: 6, valid: 5, skipped: 0, invalid: 1, quantity_total: 5 },
          }),
    );
    vi.mocked(importRemaindersExcel).mockImplementation(async (_locationId, _source, opts) =>
      opts?.sheet_index === 1
        ? makeImportResponse({ imported_count: 5 })
        : makeImportResponse({
            imported_count: 3,
            errors: ["Строка 4: остаток меньше одной штуки"],
          }),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      const button = await screen.findByRole("button", {
        name: "Импортировать все листы ОСВ (2)",
      });
      await act(async () => {
        fireEvent.click(button);
      });
      await vi.waitFor(() => {
        expect(screen.getAllByRole("columnheader").some((c) => c.textContent === "Импортировано")).toBe(true);
      });

      expect(importRemaindersExcel).toHaveBeenCalledTimes(2);
      const calls = vi.mocked(importRemaindersExcel).mock.calls;
      // Каждый лист — свой запрос: участок листа, его `sheet_index` и никогда
      // не `clear_existing` (спека §9).
      expect(calls[0][0]).toBe(11);
      expect(calls[0][2]?.sheet_index).toBe(1);
      expect(calls[1][0]).toBe(12);
      expect(calls[1][2]?.sheet_index).toBe(2);
      for (const call of calls) expect(call[2]?.clear_existing).not.toBe(true);
      const order = vi.mocked(importRemaindersExcel).mock.invocationCallOrder;
      expect(order[0]).toBeLessThan(order[1]);

      const [first, second] = tableRowsByHeader();
      expect(first.get("Лист")).toBe("Склад сырой");
      expect(first.get("Участок")).toContain("Зона Альфа");
      expect(first.get("Импортировано")).toBe("5");
      expect(first.get("Пропущено")).toBe("1");
      expect(second.get("Лист")).toBe("Дробь");
      expect(second.get("Участок")).toContain("Зона Бета");
      expect(second.get("Импортировано")).toBe("3");
      expect(second.get("Ошибки")).toContain("остаток меньше одной штуки");
    } finally {
      cleanup();
    }
  });

  it("останавливается на ошибочном листе и показывает уже применённые", async () => {
    mockReferences();
    vi.mocked(getRemainderSheets).mockResolvedValue([
      ...osvSheets(),
      makeSheet({
        index: 3,
        name: "Готовая продукция",
        kind: "1c_osv",
        detected_section_id: 13,
        detected_section_name: "Зона Гамма",
      }),
    ]);
    vi.mocked(previewRemaindersExcel).mockImplementation(async (_source, opts) =>
      makePreview({
        sheet_name: "Лист",
        source_kind: "1c_osv",
        detected_section_id: 11,
        summary: { total: 4, valid: 4, skipped: 0, invalid: 0, quantity_total: 4 },
      }),
    );
    vi.mocked(importRemaindersExcel).mockImplementation(async (_locationId, _source, opts) => {
      if (opts?.sheet_index === 2) throw new Error("Сервер недоступен");
      return makeImportResponse({ imported_count: 4 });
    });

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      const button = await screen.findByRole("button", {
        name: "Импортировать все листы ОСВ (3)",
      });
      await act(async () => {
        fireEvent.click(button);
      });
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Сервер недоступен");
      });

      // Третий лист не тронут: импорт остановился на ошибке второго.
      expect(importRemaindersExcel).toHaveBeenCalledTimes(2);
      const rows = tableRowsByHeader();
      expect(rows).toHaveLength(2);
      expect(rows[0].get("Лист")).toBe("Склад сырой");
      expect(rows[0].get("Импортировано")).toBe("4");
      expect(rows[1].get("Лист")).toBe("Дробь");
      expect(rows[1].get("Импортировано")).toBe("0");
      expect(rows[1].get("Ошибки")).toContain("Сервер недоступен");
      expect(document.body.textContent).not.toContain("Готовая продукция");
    } finally {
      cleanup();
    }
  });

  it("на ручном листе нет «все листы», а очистка разрешена", async () => {
    mockReferences();
    vi.mocked(getRemainderSheets).mockResolvedValue(osvSheets());
    vi.mocked(previewRemaindersExcel).mockImplementation(async (_source, opts) =>
      opts?.sheet_index === 0
        ? makePreview({ sheet_name: "Импорт остатков" })
        : makePreview({ source_kind: "1c_osv", detected_section_id: 11 }),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      // По умолчанию выбран первый ОСВ-лист — действие доступно.
      await screen.findByRole("button", { name: "Импортировать все листы ОСВ (2)" });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Импорт остатков · шаблон" }));
      });

      // На ручном листе действие «все листы» не показывается: оно про ОСВ.
      await vi.waitFor(() => {
        expect(
          screen.queryByRole("button", { name: /Импортировать все листы ОСВ/ }),
        ).toBeNull();
      });
      // Очистка одного листа не мультилист: на ручном листе она разрешена.
      const checkbox = await screen.findByRole("checkbox", {
        name: /Очистить перед импортом/,
      });
      expect((checkbox as HTMLInputElement).disabled).toBe(false);
    } finally {
      cleanup();
    }
  });

  it("гасит clear_existing с видимым объяснением в мультилисте", async () => {
    mockReferences();
    vi.mocked(getRemainderSheets).mockResolvedValue(osvSheets());
    vi.mocked(previewRemaindersExcel).mockResolvedValue(
      makePreview({ source_kind: "1c_osv", detected_section_id: 11 }),
    );

    const { cleanup } = mountDialog();
    try {
      await selectFile();
      const checkbox = await screen.findByRole("checkbox", {
        name: /Очистить перед импортом/,
      });
      expect((checkbox as HTMLInputElement).disabled).toBe(true);
      expect(document.body.textContent).toContain(
        "Очистка перед импортом недоступна в мультилисте",
      );
    } finally {
      cleanup();
    }
  });
});
