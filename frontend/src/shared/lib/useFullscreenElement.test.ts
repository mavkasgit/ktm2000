// @vitest-environment happy-dom

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useFullscreenElement } from "./useFullscreenElement";

/**
 * Полноэкранный режим — локальная обёртка (siberiacancode/reactuse#516):
 * пакетный `useFullscreen` отдаёт `void` из `enter()`/`exit()`. Тесты держат
 * контракт, которого у пакета нет: промис, `onError` и «чужой fullscreen не
 * закрываем».
 */
describe("useFullscreenElement", () => {
  let target: HTMLDivElement;
  let foreign: HTMLDivElement;

  /** happy-dom не умеет Fullscreen API: состояние подменяем геттером. */
  const stubFullscreenElement = (element: Element | null) => {
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => element,
    });
  };

  beforeEach(() => {
    target = document.createElement("div");
    foreign = document.createElement("div");
    document.body.append(target, foreign);
    stubFullscreenElement(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(document, "fullscreenElement");
    Reflect.deleteProperty(document, "exitFullscreen");
    target.remove();
    foreign.remove();
  });

  it("enter() возвращает промис, зовёт onError при отказе и пробрасывает его", async () => {
    const denied = new Error("Fullscreen request denied");
    Object.defineProperty(target, "requestFullscreen", {
      configurable: true,
      value: vi.fn().mockRejectedValue(denied),
    });
    const onError = vi.fn();
    const ref = { current: target };
    const { result } = renderHook(() => useFullscreenElement(ref, { onError }));

    const promise = result.current.enter();

    expect(promise).toBeInstanceOf(Promise);
    await expect(promise).rejects.toThrow("Fullscreen request denied");
    expect(onError).toHaveBeenCalledWith(denied);
  });

  it("exit() не закрывает чужой fullscreen", async () => {
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    stubFullscreenElement(foreign);
    const ref = { current: target };
    const { result } = renderHook(() => useFullscreenElement(ref));

    await act(async () => {
      await result.current.exit();
    });

    expect(exitFullscreen).not.toHaveBeenCalled();
    expect(result.current.value).toBe(false);
  });

  it("exit() закрывает свой fullscreen и сообщает о выходе по fullscreenchange", async () => {
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    stubFullscreenElement(target);
    const onExit = vi.fn();
    const ref = { current: target };
    const { result } = renderHook(() => useFullscreenElement(ref, { onExit }));

    expect(result.current.value).toBe(true);

    await act(async () => {
      await result.current.exit();
    });
    expect(exitFullscreen).toHaveBeenCalledTimes(1);

    // Браузер присылает событие уже после смены элемента — эмулируем это.
    stubFullscreenElement(null);
    act(() => {
      document.dispatchEvent(new Event("fullscreenchange"));
    });

    expect(onExit).toHaveBeenCalledTimes(1);
    expect(result.current.value).toBe(false);
  });

  it("enter() отклоняется, если Fullscreen API недоступен", async () => {
    const onError = vi.fn();
    const ref = { current: target };
    const { result } = renderHook(() => useFullscreenElement(ref, { onError }));

    await expect(result.current.enter()).rejects.toThrow("Fullscreen API недоступен");
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
