// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Section } from "@/shared/api/sections";
import type { ImportOperationStep, RemainderImportItem } from "@/shared/api/stock";

// Мокаем API-слой: диалог обязан брать участки и операции из справочников,
// а не из литералов в коде.
vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSections: vi.fn(),
}));

vi.mock("@/shared/api/stock", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/stock")>()),
  getRemainderImportOperations: vi.fn(),
}));

import { listSections } from "@/shared/api/sections";
import {
  getRemainderImportOperations,
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
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

const makeImportItem = (overrides: Partial<RemainderImportItem>): RemainderImportItem => ({
  source_row_number: 2,
  sku: "OPS-1",
  product_id: null,
  product_name: null,
  quantity: 10,
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
});
