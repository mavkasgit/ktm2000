// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import type {
  ProductWipRemainder,
  ProductWipStats,
} from "@/shared/api/productionPlans";

// Мокаем API-слой: диалог обязан показывать размер каждой строки из ответа.
vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/shared/api/productionPlans")>()),
  getProductWipStats: vi.fn(),
}));

import { getProductWipStats } from "@/shared/api/productionPlans";
import { ProductWipStatsDialog } from "./ProductWipStatsDialog";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const stats: ProductWipStats = {
  sku: "TEST-SKU",
  product_name: "Тестовое изделие",
  product_id: 1,
  remainders: [
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      completed_ops: "Сверловка",
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 2000 },
      dimensions_label: "2 м",
      quantity: 10,
      max_completed_seq: 0,
      stages_with_icons: [],
    },
    {
      spg_id: 10,
      spg_code: "SPG-A",
      spg_name: "СПГ А",
      completed_ops: "Сверловка",
      spg_icon: null,
      spg_icon_color: null,
      dimensions: { length_mm: 3000 },
      dimensions_label: "3 м",
      quantity: 4,
      max_completed_seq: 0,
      stages_with_icons: [],
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
    completed_ops: "Сверловка",
    spg_icon: null,
    spg_icon_color: null,
    dimensions: null,
    max_completed_seq: 0,
    stages_with_icons: [],
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

  it("раскрывает пару: подпись «Артикулы пары», имена компонентов и оба SKU", async () => {
    vi.mocked(getProductWipStats).mockResolvedValue(pairStats());

    const { cleanup } = mountDialog("PAIR-AAA+PAIR-BBB");
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Артикулы пары");
      });
      const text = document.body.textContent ?? "";

      // Парный ответ не должен схлопываться в одиночную сводку.
      expect(text).not.toContain("Наименование изделия");
      expect(text).toContain("Профиль А + Профиль Б");
      expect(text).toContain("PAIR-AAA");
      expect(text).toContain("PAIR-BBB");
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
});
