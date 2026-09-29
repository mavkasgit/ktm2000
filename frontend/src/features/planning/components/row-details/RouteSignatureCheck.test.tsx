// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { RouteCheckResponse, RouteSignatureCheck, RouteSignatureStep } from "@/shared/api/productionPlans";
import type * as ProductionPlansApi from "@/shared/api/productionPlans";

// Мокаем API-слой: карточка обязана показывать то, что прислала проверка
// маршрута, а не то, что она додумывает сама.
vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof ProductionPlansApi>()),
  routeCheck: vi.fn(),
}));

import { routeCheck } from "@/shared/api/productionPlans";
import { RouteSignatureCheckCard } from "./RouteSignatureCheck";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const EXPECTED = "transit:RAW_STOCK::0:0:0>production:SAWING:SAW:1:1:0";
const ACTUAL = "transit:RAW_STOCK::0:0:0>production:PACKING:PACK:1:0:0";

function step(overrides: Partial<RouteSignatureStep> & { section_code: string }): RouteSignatureStep {
  return {
    stage_kind: "production",
    operation_codes: [],
    operation_names: [],
    is_significant: false,
    transforms_dimensions: false,
    is_final: false,
    ...overrides,
  };
}

const RAW_STOCK = step({
  stage_kind: "transit",
  section_code: "RAW_STOCK",
  section_name: "Склад сырья",
  operation_codes: [""],
  operation_names: ["Хранение: Склад сырья"],
});

const SAWING = step({
  section_code: "SAWING",
  section_name: "Пиление",
  operation_codes: ["SAW"],
  operation_names: ["Раскрой"],
  is_significant: true,
  transforms_dimensions: true,
});

const PACKING = step({
  section_code: "PACKING",
  section_name: "Упаковка",
  // Название операции совпадает с названием участка — так и в данных.
  operation_codes: ["PACK"],
  operation_names: ["Упаковка"],
  is_final: true,
});

const PRESSING = step({
  section_code: "PRESSING",
  section_name: "Пресс",
  operation_codes: ["PRESS_WINDOW"],
  operation_names: ["Окно"],
});

function makeSignature(overrides: Partial<RouteSignatureCheck> = {}): RouteSignatureCheck {
  return {
    verdict: "match",
    expected: EXPECTED,
    expected_steps: [RAW_STOCK, SAWING],
    actual: EXPECTED,
    actual_steps: [RAW_STOCK, SAWING],
    ...overrides,
  };
}

function makeResponse(route_signature: RouteSignatureCheck): RouteCheckResponse {
  return {
    expected_signature: {
      template_id: null,
      rule_profile_id: 1,
      matched_rule_ids: [],
      required_sections: [],
      excluded_sections: [],
      candidate_routes: [],
      selected_route_id: 1,
      route_match_reason: null,
    },
    active_route_snapshot: null,
    match: true,
    issues: [],
    route_signature,
  };
}

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);

  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <RouteSignatureCheckCard productionPlanId={7} positionId={42} />
      </QueryClientProvider>,
    );
  });

  return {
    text: () => document.body.textContent ?? "",
    /**
     * Текст карточки без свёрнутого блока. У collapsed-`<details>` текст
     * остаётся в DOM, поэтому «строка спрятана» проверяется структурой,
     * а не отсутствием подстроки.
     */
    routeText: () => {
      const clone = document.body.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("details").forEach((details) => details.remove());
      return clone.textContent ?? "";
    },
    /**
     * Названия участков ровно в том виде, как их напечатала лента. Считать
     * вхождения подстроки во всём тексте нельзя: у этапа «Упаковка» операция
     * называется так же, и на один участок выходит два вхождения.
     */
    stageLabels: () =>
      // Только название участка: у названия операции свой `title`, и у этапа
      // «Упаковка» оба подписаны одинаково.
      Array.from(
        document.body.querySelectorAll<HTMLElement>("ol > li > div > span[title]"),
      ).map((node) => node.getAttribute("title") ?? ""),
    details: () => document.body.querySelector("details"),
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

describe("RouteSignatureCheckCard", () => {
  it("shows the route by section and operation names, not by codes", async () => {
    vi.mocked(routeCheck).mockResolvedValue(makeResponse(makeSignature()));

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("совпадает");
      });
      const text = card.routeText();
      expect(text).toContain("Склад сырья");
      expect(text).toContain("Пиление");
      expect(text).toContain("Раскрой");
      // Коды — техника сверки, в строке маршрута их нет.
      expect(text).not.toContain("SAWING");
      expect(text).not.toContain("SAW");
    } finally {
      card.cleanup();
    }
  });

  it("prints a matching route once, not as two equal columns", async () => {
    vi.mocked(routeCheck).mockResolvedValue(makeResponse(makeSignature()));

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("совпадает");
      });
      // Лента напечатала каждый участок ровно один раз, хотя сверялись два
      // маршрута: общее не дублируется, расхождения при совпадении нет.
      expect(card.stageLabels()).toEqual(["Склад сырья", "Пиление"]);
      // При совпадении блока расхождения нет вообще.
      const text = card.routeText();
      expect(text).not.toContain("Определено");
      expect(text).not.toContain("Выбрано");
    } finally {
      card.cleanup();
    }
  });

  it("falls back to the code when the section has no name", async () => {
    const nameless = { ...SAWING, section_name: null };
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(
        makeSignature({ expected_steps: [RAW_STOCK, nameless], actual_steps: [RAW_STOCK, nameless] }),
      ),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("SAWING");
      });
      // Название участка не пришло: на его месте код, без дубля названия.
      expect(card.stageLabels()).toEqual(["Склад сырья", "SAWING"]);
      // Название операции пришло — операция подписана.
      expect(card.routeText()).toContain("Раскрой");
    } finally {
      card.cleanup();
    }
  });

  it("prints the shared route once and names both versions of the divergence", async () => {
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(
        makeSignature({
          verdict: "mismatch",
          expected: EXPECTED,
          expected_steps: [RAW_STOCK, SAWING, PACKING],
          actual: ACTUAL,
          actual_steps: [RAW_STOCK, PRESSING, PACKING],
        }),
      ),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("расходится");
      });
      // Лента — это фактический маршрут целиком. Общие «Склад сырья» и
      // «Упаковка» напечатаны по одному разу: второй маршрут целиком не
      // дублируется, различается только середина.
      expect(card.stageLabels()).toEqual(["Склад сырья", "Пресс", "Упаковка"]);
      const text = card.routeText();
      // Обе стороны расхождения сказаны словами и по делу: «Пиление» было
      // определено, «Пресс» выбран вместо него.
      const divergence = text.slice(text.indexOf("Определено"));
      expect(divergence).toContain("Пиление");
      expect(divergence).toContain("Пресс");
    } finally {
      card.cleanup();
    }
  });

  it("reports a dropped stage as missing rather than as an empty list", async () => {
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(
        makeSignature({
          verdict: "mismatch",
          expected_steps: [RAW_STOCK, SAWING, PACKING],
          actual_steps: [RAW_STOCK, PACKING],
          actual: ACTUAL,
        }),
      ),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("расходится");
      });
      // «Пиление» есть только в ожидаемом маршруте: сверху оно названо как
      // «определено», а в выбранном его нет — и сказано словами, а не пустотой.
      const routeText = card.routeText();
      const divergence = routeText.slice(routeText.indexOf("Определено"));
      expect(divergence).toContain("Пиление");
      expect(divergence).toContain("этап пропущен");
      expect(card.stageLabels()).toEqual(["Склад сырья", "Упаковка"]);
    } finally {
      card.cleanup();
    }
  });

  it("keeps the route identity out of the card", async () => {
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(makeSignature({ verdict: "mismatch", actual: ACTUAL })),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("расходится");
      });
      // Сверка по кодам — техника, а не содержание работы: ни сырой
      // сигнатуры, ни кодов участков, ни признаков этапа в карточке нет.
      expect(card.text()).not.toContain(EXPECTED);
      expect(card.text()).not.toContain(ACTUAL);
      expect(card.text()).not.toContain(":0:0:0");
      expect(card.text()).not.toContain("RAW_STOCK");
      expect(card.text()).not.toContain("значимый");
      // Спрятанного блока не осталось совсем.
      expect(card.details()).toBeNull();
    } finally {
      card.cleanup();
    }
  });

  it("stays silent when the position has no route to compare", async () => {
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(
        makeSignature({ verdict: "unknown", expected: null, actual: null, expected_steps: [] }),
      ),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(vi.mocked(routeCheck)).toHaveBeenCalled();
      });
      expect(card.text()).not.toContain("Из чего считается вердикт");
      expect(card.text()).not.toContain("сравнить нельзя");
    } finally {
      card.cleanup();
    }
  });
});
