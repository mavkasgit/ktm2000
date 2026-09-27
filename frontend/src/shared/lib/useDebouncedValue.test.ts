/**
 * Пауза перед запросом по поиску — одна реализация на приложение (#197).
 *
 * Двенадцать копий `setTimeout(…, 300)` + `clearTimeout` в одинаковом виде
 * означали, что одна цифра в задержке меняет поведение одного экрана и
 * молча ломает остальные одиннадцать.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue, useFlushableDebouncedValue } from "./useDebouncedValue";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useDebouncedValue", () => {
  it("сразу отдаёт введённое значение — пауза не должна прятать первый ввод", () => {
    const { result } = renderHook(() => useDebouncedValue("привет", 300));
    expect(result.current).toBe("привет");
  });

  it("не отдаёт новое значение раньше паузы", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "а" },
    });
    rerender({ v: "аб" });
    expect(result.current).toBe("а");

    act(() => void vi.advanceTimersByTime(299));
    expect(result.current).toBe("а");
  });

  it("отдаёт значение после паузы", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "а" },
    });
    rerender({ v: "аб" });
    act(() => void vi.advanceTimersByTime(300));
    expect(result.current).toBe("аб");
  });

  it("при быстром наборе отдаёт только последнее значение", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "" },
    });
    for (const v of ["а", "аб", "абв", "абвг"]) rerender({ v });
    act(() => void vi.advanceTimersByTime(300));
    expect(result.current).toBe("абвг");
  });

  it("пауза каждый раз начинается заново, а не считается от первого ввода", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "" },
    });
    rerender({ v: "а" });
    act(() => void vi.advanceTimersByTime(200));
    rerender({ v: "аб" });
    act(() => void vi.advanceTimersByTime(200));
    // 400 мс от первого ввода, но 200 от последнего — значения ещё нет.
    expect(result.current).toBe("");
    act(() => void vi.advanceTimersByTime(100));
    expect(result.current).toBe("аб");
  });

  it("пустая пауза отдаёт значение сразу — для полей без задержки", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 0), {
      initialProps: { v: "а" },
    });
    rerender({ v: "аб" });
    act(() => void vi.advanceTimersByTime(0));
    expect(result.current).toBe("аб");
  });

  it("таймер снимается при размонтировании — нет обновления состояния после ухода", () => {
    const clear = vi.spyOn(globalThis, "clearTimeout");
    const { unmount } = renderHook(() => useDebouncedValue("а", 300));
    unmount();
    expect(clear).toHaveBeenCalled();
  });
});

describe("useFlushableDebouncedValue", () => {
  it("отдаёт значение с той же паузой, что и обычный хук", () => {
    const { result, rerender } = renderHook(({ v }) => useFlushableDebouncedValue(v, 300), {
      initialProps: { v: "а" },
    });
    rerender({ v: "аб" });
    expect(result.current.value).toBe("а");
    act(() => void vi.advanceTimersByTime(300));
    expect(result.current.value).toBe("аб");
  });

  it("flush применяет значение немедленно — Enter не ждёт паузы", () => {
    const { result, rerender } = renderHook(({ v }) => useFlushableDebouncedValue(v, 300), {
      initialProps: { v: "" },
    });
    rerender({ v: "юп-2083" });
    act(() => result.current.flush());
    expect(result.current.value).toBe("юп-2083");
  });

  it("flush не отменяет паузу: последующий ввод всё равно отложен", () => {
    const { result, rerender } = renderHook(({ v }) => useFlushableDebouncedValue(v, 300), {
      initialProps: { v: "" },
    });
    rerender({ v: "юп" });
    act(() => result.current.flush());
    rerender({ v: "юп-2083" });
    expect(result.current.value).toBe("юп");
    act(() => void vi.advanceTimersByTime(300));
    expect(result.current.value).toBe("юп-2083");
  });
});
