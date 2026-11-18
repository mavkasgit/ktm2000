// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { DESKTOP_VIEWPORT_QUERY, useMediaQuery } from "./useMediaQuery";

/**
 * Управляемый `matchMedia`: ширина меняется тестом, а `change` приходит в
 * подписку так же, как от браузера. `stubViewportWidth` из
 * `shared/lib/testViewport` для этого не годится — у него `addEventListener`
 * пустой, событие разослать некому.
 */
function stubViewport(initialWidth: number) {
  let width = initialWidth;
  const listeners = new Map<string, Set<() => void>>();

  const matches = (query: string): boolean => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    return min ? width >= Number(min[1]) : max ? width <= Number(max[1]) : false;
  };

  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => {
    if (!listeners.has(query)) listeners.set(query, new Set());
    return {
      get matches() {
        return matches(query);
      },
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: (type: string, listener: () => void) => {
        if (type === "change") listeners.get(query)?.add(listener);
      },
      removeEventListener: (type: string, listener: () => void) => {
        if (type === "change") listeners.get(query)?.delete(listener);
      },
      dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList;
  });

  return {
    setWidth(next: number) {
      width = next;
      for (const queryListeners of listeners.values()) {
        for (const listener of queryListeners) listener();
      }
    },
    listenerCount(query: string) {
      return listeners.get(query)?.size ?? 0;
    },
  };
}

describe("useMediaQuery", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("отдаёт состояние запроса уже на первом рендере — без кадра с чужой раскладкой", () => {
    stubViewport(1200);
    expect(renderHook(() => useMediaQuery(DESKTOP_VIEWPORT_QUERY)).result.current).toBe(true);

    stubViewport(400);
    expect(renderHook(() => useMediaQuery(DESKTOP_VIEWPORT_QUERY)).result.current).toBe(false);
  });

  it("держит границу телефона ровно на пороге Tailwind md (768px)", () => {
    const viewport = stubViewport(768);
    const { result } = renderHook(() => useMediaQuery(DESKTOP_VIEWPORT_QUERY));
    expect(result.current).toBe(true);

    act(() => viewport.setWidth(767));
    expect(result.current).toBe(false);
  });

  it("обновляется по change — поворот планшета не требует перезагрузки", () => {
    const viewport = stubViewport(1200);
    const { result } = renderHook(() => useMediaQuery(DESKTOP_VIEWPORT_QUERY));

    act(() => viewport.setWidth(400));
    expect(result.current).toBe(false);

    act(() => viewport.setWidth(1024));
    expect(result.current).toBe(true);
  });

  it("перечитывает состояние, когда запрос сменился", () => {
    stubViewport(1200);
    const { result, rerender } = renderHook(({ query }) => useMediaQuery(query), {
      initialProps: { query: DESKTOP_VIEWPORT_QUERY },
    });
    expect(result.current).toBe(true);

    rerender({ query: "(max-width: 767px)" });
    expect(result.current).toBe(false);
  });

  it("снимает подписку на change при размонтировании", () => {
    const viewport = stubViewport(1200);
    const { unmount } = renderHook(() => useMediaQuery(DESKTOP_VIEWPORT_QUERY));
    expect(viewport.listenerCount(DESKTOP_VIEWPORT_QUERY)).toBe(1);

    unmount();
    expect(viewport.listenerCount(DESKTOP_VIEWPORT_QUERY)).toBe(0);
  });
});
