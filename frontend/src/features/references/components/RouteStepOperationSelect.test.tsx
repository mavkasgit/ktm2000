// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { SectionWithOperations } from "@/shared/api/sections";

// Мокаем API-слой: селект обязан брать операции из справочника участков,
// а не из литералов в коде.
vi.mock("@/shared/api/sections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/sections")>()),
  listSectionsWithOperations: vi.fn(),
}));

import { listSectionsWithOperations } from "@/shared/api/sections";
import { RouteStepOperationSelect, type RouteStepOperationSelectProps } from "./RouteStepOperationSelect";

// Без этого флага React 18 сыплет предупреждения «not configured to support act(...)»
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const makeSection = (
  overrides: Partial<SectionWithOperations>,
): SectionWithOperations => ({
  id: 1,
  code: "X",
  name: "X",
  type: "production",
  icon: null,
  icon_color: null,
  operations: [],
  ...overrides,
});

type Operation = SectionWithOperations["operations"][number];

const makeOperation = (overrides: Partial<Operation>): Operation => ({
  id: 1,
  operation_code: "OP",
  operation_name: "OP",
  is_significant: true,
  group_code: null,
  group_name: null,
  ...overrides,
});

function mountSelect(props: Partial<RouteStepOperationSelectProps> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);

  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <RouteStepOperationSelect
          sectionId={42}
          operationCode={null}
          operationName=""
          onChange={vi.fn()}
          {...props}
        />
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

describe("RouteStepOperationSelect", () => {
  it("renders the operation of the node's section from the server reference, not from hardcoded literals", async () => {
    // Названия операций намеренно НЕ совпадают со старым хардкод-каталогом
    vi.mocked(listSectionsWithOperations).mockResolvedValue([
      makeSection({
        id: 42,
        code: "GALVANIC",
        name: "Гальваника",
        operations: [
          makeOperation({ id: 1, operation_code: "OP_GALV", operation_name: "Гальваническое покрытие" }),
          makeOperation({ id: 2, operation_code: "OP_POLISH", operation_name: "Полировка" }),
        ],
      }),
      makeSection({
        id: 43,
        code: "OTHER",
        name: "Другой участок",
        operations: [
          makeOperation({ id: 3, operation_code: "OP_ALIEN", operation_name: "Чужая операция" }),
        ],
      }),
    ]);

    const { cleanup } = mountSelect({ sectionId: 42, operationCode: "OP_GALV" });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Гальваническое покрытие");
      });
      const text = document.body.textContent ?? "";

      // Старые литералы удалённой константы OPERATIONS не подмешиваются
      expect(text).not.toContain("Выдача сырья");
      expect(text).not.toContain("Приемка ГП");
      expect(text).not.toContain("Передача на п/ф");
    } finally {
      cleanup();
    }
  });

  it("shows an explicit empty state when the section has no operations in the reference", async () => {
    vi.mocked(listSectionsWithOperations).mockResolvedValue([
      makeSection({ id: 42, code: "EMPTY", name: "Пустой участок", operations: [] }),
    ]);

    const { cleanup } = mountSelect({ sectionId: 42 });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain(
          "У участка нет операций в справочнике",
        );
      });
    } finally {
      cleanup();
    }
  });

  it("shows an explicit error state when the operations reference fails to load", async () => {
    vi.mocked(listSectionsWithOperations).mockRejectedValue(
      new Error("network down"),
    );

    const { cleanup } = mountSelect({ sectionId: 42 });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain(
          "Не удалось загрузить справочник операций",
        );
      });
    } finally {
      cleanup();
    }
  });

  it("keeps a stale operation code of an existing route as a visible option", async () => {
    vi.mocked(listSectionsWithOperations).mockResolvedValue([
      makeSection({
        id: 42,
        code: "GALVANIC",
        name: "Гальваника",
        operations: [
          makeOperation({ id: 1, operation_code: "OP_GALV", operation_name: "Гальваническое покрытие" }),
        ],
      }),
    ]);

    const { cleanup } = mountSelect({
      sectionId: 42,
      operationCode: "OP_REMOVED",
      operationName: "Устаревшая операция",
    });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Устаревшая операция");
      });
    } finally {
      cleanup();
    }
  });
});
