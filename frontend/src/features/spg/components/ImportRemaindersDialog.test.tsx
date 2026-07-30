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
}));

import { listSections } from "@/shared/api/sections";
import { getRemainderImportOperations } from "@/shared/api/stock";
import { ImportRemaindersDialog } from "./ImportRemaindersDialog";

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
