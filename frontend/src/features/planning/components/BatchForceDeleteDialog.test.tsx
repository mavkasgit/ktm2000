import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type * as ProductionPlansApi from "@/shared/api/productionPlans";
import {
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
} from "@/shared/api/stock";

vi.mock("@/shared/api/productionPlans", async (importOriginal) => ({
  ...(await importOriginal<typeof ProductionPlansApi>()),
  getBatchForceDeletePreview: vi.fn(),
}));

import {
  getBatchForceDeletePreview,
  type BatchForceDeletePreview,
  type BatchDeleteConflict,
} from "@/shared/api/productionPlans";

import { BatchForceDeleteDialog, stockEffectRowKey } from "./BatchForceDeleteDialog";

type Effect = BatchForceDeletePreview["stock_effects"][number];

const PRESS_STAGE = {
  sequence: 1,
  section_code: "PRESS",
  section_name: "Пресс",
  operation_code: "PRESS_WINDOW",
  operation_name: "Пресс (окно)",
  is_significant: true,
};

function effect(overrides: Partial<Effect> = {}): Effect {
  return {
    product_sku: "FG-200",
    location_id: 7,
    location_code: "PRESS",
    dimensions: null,
    completed_operations: null,
    completed_stages: [],
    net_delta: "5.000",
    ledger_entries: 1,
    ...overrides,
  };
}

function makePreview(effects: Effect[]): BatchForceDeletePreview {
  return {
    batch_id: 3,
    filename: "plan.xlsx",
    production_plan_id: 1,
    positions: 1,
    section_plan_lines: 1,
    work_tasks: 1,
    transfers: 0,
    defects: 0,
    ledger_entries: effects.length,
    stock_effects: effects,
    blockers: [],
  };
}

const conflict: BatchDeleteConflict = {
  code: "batch_has_released_positions",
  blockers: [{ position_id: 2, reason: "released" }],
  safe_action: "delete_drafts_only",
  drafts: 1,
};

function renderDialog(effects: Effect[]) {
  vi.mocked(getBatchForceDeletePreview).mockResolvedValue(makePreview(effects));
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <BatchForceDeleteDialog
        open
        onOpenChange={vi.fn()}
        planId={1}
        batchId={3}
        filename="plan.xlsx"
        conflict={conflict}
        onForceDeleted={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

let consoleErrorSpy: MockInstance | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  // React пишет дубли ключей через console.error — ловим их как факт бага,
  // а не как текст предупреждения, который легко «переименовать».
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleErrorSpy?.mockRestore();
  consoleErrorSpy = null;
});

function duplicateKeyWarnings(): unknown[][] {
  if (!consoleErrorSpy) return [];
  return consoleErrorSpy.mock.calls.filter((args) =>
    args.some((arg) => typeof arg === "string" && arg.includes("same key")),
  );
}

describe("stockEffectRowKey", () => {
  it("различает два пустых состояния оси: null и []", () => {
    const notRecorded = stockEffectRowKey(effect({ completed_operations: null }));
    const withoutOps = stockEffectRowKey(effect({ completed_operations: [] }));
    expect(notRecorded).not.toBe(withoutOps);
  });

  it("различает разные наборы операций одного артикула и участка", () => {
    const press = stockEffectRowKey(
      effect({ completed_operations: ["PRESS_WINDOW"], completed_stages: [PRESS_STAGE] }),
    );
    const shot = stockEffectRowKey(effect({ completed_operations: ["SHOT"] }));
    expect(press).not.toBe(shot);
  });

  it("различает разные габариты одного артикула и участка", () => {
    const long = stockEffectRowKey(effect({ dimensions: { length_mm: 2700 } }));
    const short = stockEffectRowKey(effect({ dimensions: { length_mm: 900 } }));
    expect(long).not.toBe(short);
  });

  it("одинаковое состояние даёт одинаковый ключ независимо от порядка кодов", () => {
    const a = stockEffectRowKey(effect({ completed_operations: ["SHOT", "PRESS_WINDOW"] }));
    const b = stockEffectRowKey(effect({ completed_operations: ["PRESS_WINDOW", "SHOT"] }));
    expect(a).toBe(b);
  });
});

describe("BatchForceDeleteDialog — свод «Как изменятся остатки»", () => {
  it("две группы одного артикула и участка: разные подписи и разные ключи", async () => {
    renderDialog([
      effect({ completed_operations: null }),
      effect({ completed_operations: [] }),
    ]);

    await screen.findByText(OPERATIONS_NOT_RECORDED_LABEL);
    expect(screen.getByText(OPERATIONS_EMPTY_LABEL)).toBeTruthy();

    const rows = screen.getAllByRole("row").filter((row) => row.querySelector("td"));
    expect(rows).toHaveLength(2);
    expect(duplicateKeyWarnings()).toHaveLength(0);
  });

  it("непустой признак печатается названиями справочника, а не кодами", async () => {
    renderDialog([
      effect({
        completed_operations: ["PRESS_WINDOW"],
        completed_stages: [PRESS_STAGE],
      }),
    ]);

    await screen.findByText("Пресс (окно)");
    expect(screen.queryByText("PRESS_WINDOW")).toBeNull();
    expect(duplicateKeyWarnings()).toHaveLength(0);
  });
});
