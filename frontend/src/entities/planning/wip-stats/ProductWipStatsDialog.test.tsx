// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import type {
  ProductWipRemainder,
  ProductWipStats,
} from "@/shared/api/productionPlans";
import type { ImportOperationStep } from "@/shared/api/stock";

// Мокаем API-слой: диалог обязан показывать размер каждой строки из ответа.
vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  getProductWipStats: vi.fn(),
}));

import { getProductWipStats } from "@/shared/api/productionPlans";
import { ProductWipStatsDialog } from "./ProductWipStatsDialog";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

/** Этап оси операций в формате справочника (`RouteStepsDisplay`). */
const makeStep = (operation_name: string, sequence = 1): ImportOperationStep => ({
  sequence,
  section_code: "PROD",
  section_name: "Участок",
  operation_code: `OP${sequence}`,
  operation_name,
  is_significant: true,
});

const stats: ProductWipStats = {
  sku: "TEST-SKU",
  product_name: "Тестовое изделие",
  product_id: 1,
  remainders: [
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      // Заполненная ось: рисуются чипы этапов.
      completed_operations: ["OP1"],
      completed_stages: [makeStep("Сверловка")],
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 2000 },
      dimensions_label: "2 м",
      quantity: 10,
      max_completed_seq: 1,
    },
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      // Ось не зафиксирована: подпись пустого состояния (прочерк), а не
      // вовсе пустая ячейка — строка остаётся строкой.
      completed_operations: null,
      completed_stages: [],
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 3000 },
      dimensions_label: "3 м",
      quantity: 4,
      max_completed_seq: 0,
    },
  ],
  in_work: [
    {
      section_id: 21,
      section_code: "PROD",
      section_name: "Участок",
      operation_name: "Сверлить",
      section_icon: null,
      section_icon_color: null,
      dimensions: { length_mm: 2000 },
      dimensions_label: "2 м",
      planned_qty: 100,
      completed_qty: 20,
      issued_qty: 100,
      active_tasks_count: 1,
    },
    {
      section_id: 21,
      section_code: "PROD",
      section_name: "Участок",
      operation_name: "Сверлить",
      section_icon: null,
      section_icon_color: null,
      dimensions: null,
      dimensions_label: "—",
      planned_qty: 50,
      completed_qty: 0,
      issued_qty: 50,
      active_tasks_count: 2,
    },
  ],
  is_pair: false,
  components: [],
  warning: null,
};

/** Остаток компонента пары: имя, подпись размера и количество уникальны для блока. */
function pairRemainder(
  overrides: Partial<ProductWipRemainder> &
    Pick<ProductWipRemainder, "spg_name" | "dimensions_label" | "quantity">,
): ProductWipRemainder {
  return {
    spg_id: 10,
    spg_code: "SPG-A",
    // Маршрут пройден, операций не было — третья ветка правила подписи.
    completed_operations: [],
    completed_stages: [],
    spg_icon: null,
    spg_icon_color: null,
    dimensions: null,
    max_completed_seq: 0,
    ...overrides,
  };
}

/** Ответ по составному артикулу «A+B»: остатки раскрыты покомпонентно. */
function pairStats(overrides: Partial<ProductWipStats> = {}): ProductWipStats {
  return {
    sku: "PAIR-AAA+PAIR-BBB",
    product_name: "Профиль А + Профиль Б",
    product_id: null,
    remainders: [],
    in_work: [],
    is_pair: true,
    components: [
      {
        sku: "PAIR-AAA",
        product_id: 11,
        product_name: "Профиль А",
        remainders: [
          pairRemainder({ spg_name: "ГХП А", dimensions_label: "2,7 м", quantity: 123 }),
        ],
      },
      {
        sku: "PAIR-BBB",
        product_id: 22,
        product_name: "Профиль Б",
        remainders: [
          pairRemainder({
            spg_id: 20,
            spg_code: "SPG-B",
            spg_name: "ГХП Б",
            dimensions_label: "3,2 м",
            quantity: 456,
          }),
        ],
      },
    ],
    warning: null,
    ...overrides,
  };
}

function mountDialog(sku = "TEST-SKU") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);

  act(() => {
    root.render(
      <ProductWipStatsDialog sku={sku} open onOpenChange={vi.fn()} />,
    );
  });

  return {
    cleanup: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** Блок компонента пары: сводка пары рендерит по секции на каждый артикул. */
function componentSection(sku: string): HTMLElement | null {
  return (
    Array.from(document.querySelectorAll("section")).find(
      (section) =>
        section.textContent?.includes("Остатки на складах подготовки") === true &&
        section.textContent.includes(sku),
    ) ?? null
  );
}

/** Названия ГХП в порядке отрисовки внутри блока компонента. */
function componentSpgNames(sku: string): (string | null)[] {
  const section = componentSection(sku);
  if (!section) return [];
  return Array.from(section.querySelectorAll("tbody tr")).map(
    (row) => row.querySelector("td .font-medium")?.textContent ?? null,
  );
}

/** Кнопка сортировки колонки внутри блока компонента. */
function componentSortButton(sku: string, field: string): HTMLButtonElement | null {
  const section = componentSection(sku);
  if (!section) return null;
  return section.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
}

/** Блок «В реальной работе»: операторские строки с их шапкой. */
function inWorkSection(): HTMLElement | null {
  return (
    Array.from(document.querySelectorAll("section")).find(
      (section) =>
        section.textContent?.includes("В реальной работе") === true,
    ) ?? null
  );
}

/** Операции строк блока «в работе» в порядке отрисовки. */
function inWorkOperations(): (string | null)[] {
  const section = inWorkSection();
  if (!section) return [];
  return Array.from(section.querySelectorAll("tbody tr")).map(
    (row) => row.querySelector("td .font-medium")?.textContent ?? null,
  );
}

/** Кнопка сортировки колонки блока «в работе». */
function inWorkSortButton(field: string): HTMLButtonElement | null {
  const section = inWorkSection();
  if (!section) return null;
  return section.querySelector<HTMLButtonElement>(`button[data-sort-field="${field}"]`);
}

/** Кнопка-подпись колонки «Операция (участок)» — триггер попапера фильтра. */
function inWorkFilterTrigger(): HTMLButtonElement | null {
  const section = inWorkSection();
  if (!section) return null;
  return (
    Array.from(section.querySelectorAll<HTMLButtonElement>("thead button")).find(
      (button) => button.textContent?.includes("Операция") === true,
    ) ?? null
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("ProductWipStatsDialog", () => {
  it("shows the size of each remainder and in-work task row", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(stats);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Тестовое изделие");
      });
      const text = document.body.textContent ?? "";

      // Остатки: каждая строка несёт свою подпись размера.
      expect(text).toContain("2 м");
      expect(text).toContain("3 м");
      expect(text).toContain("10");
      expect(text).toContain("4");

      // Задачи в работе: размеры из ответа, включая безразмерную строку.
      expect(text).toContain("Сверлить");
      expect(text).toContain("—");
    } finally {
      cleanup();
    }
  });

  it("печатает ось по общему правилу: заполненная — чипы, пустая — прочерк (#242)", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(stats);

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Тестовое изделие");
      });
      const text = document.body.textContent ?? "";

      // Заполненная ось — чипы этапов из ответа, а не серверная строка подписи.
      expect(text).toContain("Сверловка");
      // Пустое состояние (`null`) — прочерк, а не «не зафиксировано».
      const nullAxisRow = Array.from(document.querySelectorAll("tr")).find((row) =>
        row.textContent?.includes("3 м"),
      );
      expect(nullAxisRow?.textContent).toContain("—");
      expect(text).not.toContain("не зафиксировано");
      expect(text).not.toContain("без операций");
    } finally {
      cleanup();
    }
  });

  it("остаток с пустым списком операций подписан прочерком", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(pairStats());

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(componentSection("PAIR-AAA")).not.toBeNull();
      });

      const a = componentSection("PAIR-AAA");
      // Подпись оси и размер («2,7 м») — вся правда о строке: прочерк здесь
      // может быть только у операций, и это `[]`, а не `null`.
      expect(a?.textContent).toContain("—");
      expect(a?.textContent).not.toContain("без операций");
      expect(a?.textContent).not.toContain("не зафиксировано");
    } finally {
      cleanup();
    }
  });

  it("shows an explicit error when the stats fail to load", async () => {
    vi.mocked(getProductWipStats).mockRejectedValue(new Error("network down"));

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("network down");
      });
    } finally {
      cleanup();
    }
  });

  it("раскрывает пару: имена компонентов в шапке и оба SKU в своих блоках", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(pairStats());

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Профиль А + Профиль Б");
      });
      const text = document.body.textContent ?? "";

      // Название пары стоит в шапке рядом с составным артикулом, а
      // раскрытие — по компонентам в своих блоках.
      expect(text).toContain("PAIR-AAA");
      expect(text).toContain("PAIR-BBB");
      expect(componentSection("PAIR-AAA")?.textContent).toContain("ГХП А");
    } finally {
      cleanup();
    }
  });

  it("держит остатки каждого компонента пары в его собственном блоке", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(pairStats());

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(componentSection("PAIR-AAA")).not.toBeNull();
      });

      const a = componentSection("PAIR-AAA");
      const b = componentSection("PAIR-BBB");
      expect(b, "блок компонента PAIR-BBB не отрисован").not.toBeNull();

      // Каждый блок несёт складские остатки своего артикула…
      expect(a?.textContent).toContain("ГХП А");
      expect(a?.textContent).toContain("2,7 м");
      expect(a?.textContent).toContain("123");
      expect(b?.textContent).toContain("ГХП Б");
      expect(b?.textContent).toContain("3,2 м");
      expect(b?.textContent).toContain("456");

      // …и не подмешивает остатки соседа в общий блок.
      expect(a?.textContent).not.toContain("3,2 м");
      expect(a?.textContent).not.toContain("456");
      expect(b?.textContent).not.toContain("2,7 м");
      expect(b?.textContent).not.toContain("123");
    } finally {
      cleanup();
    }
  });

  it("предупреждает об отсутствии пары в справочнике, не теряя компоненты", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(
      pairStats({ warning: "product_pair_not_found" }),
    );

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain(
          "Пара таких профилей не создана в справочнике сырья",
        );
      });
      const text = document.body.textContent ?? "";

      // Деградация — предупреждение, а не замена сводки: компоненты раскрыты по SKU.
      expect(text).toContain("PAIR-AAA");
      expect(text).toContain("PAIR-BBB");
    } finally {
      cleanup();
    }
  });

  it("помечает компонент, которого нет в справочнике, вместо пустой таблицы", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(
      pairStats({
        components: [
          {
            sku: "PAIR-AAA",
            product_id: 11,
            product_name: "Профиль А",
            remainders: [
              pairRemainder({ spg_name: "ГХП А", dimensions_label: "2,7 м", quantity: 123 }),
            ],
          },
          { sku: "PAIR-CCC", product_id: null, product_name: "Профиль В", remainders: [] },
        ],
      }),
    );

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-CCC");
    try {
      await vi.waitFor(() => {
        expect(componentSection("PAIR-CCC")).not.toBeNull();
      });

      const missing = componentSection("PAIR-CCC");
      expect(missing?.textContent).toContain("Артикул PAIR-CCC не найден в справочнике.");
      // Ветки «нет артикула в справочнике» и «нет остатков» — разные сообщения.
      expect(missing?.textContent).not.toContain("Нет активных остатков");

      // Соседний компонент продолжает показывать свою таблицу остатков.
      expect(componentSection("PAIR-AAA")?.textContent).toContain("ГХП А");
    } finally {
      cleanup();
    }
  });

  it("блок «в работе» сортируется по колонке, а не остаётся плоским списком", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue({
      ...stats,
      in_work: [
        { ...stats.in_work[0], operation_name: "Шлифовка", dimensions: null, dimensions_label: "—", planned_qty: 5 },
        { ...stats.in_work[0], operation_name: "Анодирование", dimensions: null, dimensions_label: "—", planned_qty: 50 },
      ],
    });

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(inWorkSortButton("plan")).not.toBeNull();
      });

      // Порядок до клика — как отдал сервер (порядок этапов маршрута).
      expect(inWorkOperations()).toEqual(["Шлифовка", "Анодирование"]);

      act(() => {
        inWorkSortButton("plan")?.click();
      });
      // Первый клик — по убыванию: 50 раньше 5.
      expect(inWorkOperations()).toEqual(["Анодирование", "Шлифовка"]);

      act(() => {
        inWorkSortButton("plan")?.click();
      });
      expect(inWorkOperations()).toEqual(["Шлифовка", "Анодирование"]);
    } finally {
      cleanup();
    }
  });

  it("выбор в колонке «Операция» сужает блок «в работе»", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue({
      ...stats,
      in_work: [
        { ...stats.in_work[0], operation_name: "Шлифовка", dimensions: null, dimensions_label: "—" },
        { ...stats.in_work[0], operation_name: "Анодирование", dimensions: null, dimensions_label: "—" },
      ],
    });

    const { cleanup } = mountDialog();
    try {
      await vi.waitFor(() => {
        expect(inWorkSection()).not.toBeNull();
      });
      expect(inWorkOperations()).toEqual(["Шлифовка", "Анодирование"]);

      // Попапер открывает кнопка-подпись колонки, а не кнопка сортировки.
      act(() => {
        inWorkFilterTrigger()?.click();
      });
      // Попапер рендерится в портале, поэтому значения ищем в документе.
      const valueButton = Array.from(
        document.querySelectorAll<HTMLButtonElement>("button[aria-pressed]"),
      ).find((button) => button.textContent?.trim() === "Анодирование");
      expect(valueButton, "в поповере нет значения «Анодирование»").toBeDefined();

      act(() => {
        valueButton?.click();
      });
      expect(inWorkOperations()).toEqual(["Анодирование"]);
    } finally {
      cleanup();
    }
  });

  it("таблица остатков компонента пары сортируется сама, без общего фильтра диалога", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(
      pairStats({
        components: [
          {
            sku: "PAIR-AAA",
            product_id: 11,
            product_name: "Профиль А",
            remainders: [
              pairRemainder({ spg_name: "ГХП А1", dimensions_label: "2,7 м", quantity: 5 }),
              pairRemainder({ spg_name: "ГХП А2", dimensions_label: "3,2 м", quantity: 50 }),
            ],
          },
          {
            sku: "PAIR-BBB",
            product_id: 22,
            product_name: "Профиль Б",
            remainders: [pairRemainder({ spg_name: "ГХП Б", dimensions_label: "4 м", quantity: 7 })],
          },
        ],
      }),
    );

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(componentSortButton("PAIR-AAA", "qty")).not.toBeNull();
      });

      // Порядок по умолчанию — по убыванию остатка: 50 раньше 5.
      expect(componentSpgNames("PAIR-AAA")).toEqual(["ГХП А2", "ГХП А1"]);
      expect(componentSpgNames("PAIR-BBB")).toEqual(["ГХП Б"]);

      // Сортировка у каждой таблицы своя: щелчки по «ГХП» в блоке PAIR-AAA
      // не переставляют строки соседнего блока PAIR-BBB. Общее состояние в
      // диалоге сужало бы все компоненты пары одним фильтром.
      for (let click = 0; click < 4; click += 1) {
        act(() => {
          componentSortButton("PAIR-AAA", "name")?.click();
        });
      }
      expect(componentSpgNames("PAIR-BBB")).toEqual(["ГХП Б"]);
    } finally {
      cleanup();
    }
  });
});
