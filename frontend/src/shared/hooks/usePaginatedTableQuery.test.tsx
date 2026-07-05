// @vitest-environment happy-dom

import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { usePaginatedTableQuery } from "./usePaginatedTableQuery";

interface HarnessResult {
  page: number;
  limit: number;
  offset: number;
  getTotalPages: (total: number) => number;
  getRangeLabel: (shown: number, total: number) => string;
  setPage: (page: number) => void;
  setLimit: (limit: 50 | 100 | 200 | 500) => void;
}

function mountHarness(resetPageDeps?: readonly unknown[]) {
  const container = document.createElement("div");
  const root: Root = createRoot(container);
  const state: { current: HarnessResult | null } = { current: null };

  function Harness() {
    const hook = usePaginatedTableQuery({ resetPageDeps });
    state.current = hook;
    return null;
  }

  act(() => {
    root.render(<Harness />);
  });

  return {
    getResult: () => {
      if (!state.current) throw new Error("Hook not mounted");
      return state.current;
    },
    unmount: () => {
      act(() => {
        root.unmount();
      });
    },
  };
}

describe("usePaginatedTableQuery", () => {
  it("computes offset from page and limit", () => {
    const harness = mountHarness();
    const hook = harness.getResult();

    expect(hook.page).toBe(1);
    expect(hook.limit).toBe(50);
    expect(hook.offset).toBe(0);

    act(() => {
      hook.setPage(3);
    });

    expect(harness.getResult().offset).toBe(100);
    harness.unmount();
  });

  it("resets page when limit changes", () => {
    const harness = mountHarness();
    const hook = harness.getResult();

    act(() => {
      hook.setPage(4);
    });
    expect(harness.getResult().page).toBe(4);

    act(() => {
      harness.getResult().setLimit(100);
    });
    expect(harness.getResult().page).toBe(1);
    expect(harness.getResult().limit).toBe(100);
    harness.unmount();
  });

  it("derives total pages and range label", () => {
    const harness = mountHarness();
    const hook = harness.getResult();

    expect(hook.getTotalPages(124)).toBe(3);
    expect(hook.getRangeLabel(50, 124)).toBe("Показано 50 из 124 записей");
    harness.unmount();
  });
});