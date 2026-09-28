// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { RouteCheckResponse, RouteSignatureCheck } from "@/shared/api/productionPlans";
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
const ACTUAL = "production:SAWING:SAW:1:1:0>transit:RAW_STOCK::0:0:1";

function makeSignature(overrides: Partial<RouteSignatureCheck> = {}): RouteSignatureCheck {
  return {
    verdict: "match",
    expected: EXPECTED,
    expected_steps: [
      {
        stage_kind: "transit",
        section_code: "RAW_STOCK",
        operation_codes: [""],
        is_significant: false,
        transforms_dimensions: false,
        is_final: false,
      },
      {
        stage_kind: "production",
        section_code: "SAWING",
        operation_codes: ["SAW"],
        is_significant: true,
        transforms_dimensions: true,
        is_final: false,
      },
    ],
    actual: EXPECTED,
    actual_steps: [],
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
  it("shows both signatures and the verdict when the route signature matches", async () => {
    vi.mocked(routeCheck).mockResolvedValue(makeResponse(makeSignature()));

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("Сигнатуры совпадают");
      });
      expect(card.text()).toContain(EXPECTED);
    } finally {
      card.cleanup();
    }
  });

  it("shows the divergence when the route signature differs from the build input", async () => {
    vi.mocked(routeCheck).mockResolvedValue(
      makeResponse(makeSignature({ verdict: "mismatch", actual: ACTUAL })),
    );

    const card = mountCard();
    try {
      await vi.waitFor(() => {
        expect(card.text()).toContain("Сигнатуры расходятся");
      });
      const text = card.text();
      expect(text).toContain(EXPECTED);
      expect(text).toContain(ACTUAL);
    } finally {
      card.cleanup();
    }
  });

  it("stays silent when the position has no signature to compare", async () => {
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
      expect(card.text()).not.toContain("Сигнатура маршрута");
    } finally {
      card.cleanup();
    }
  });
});
