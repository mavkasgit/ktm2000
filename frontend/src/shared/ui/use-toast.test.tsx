// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { dismissToast, toast, useToast, type ToastData } from "./use-toast";

// Без этого флага React 18 сыплет предупреждения «not configured to support act(...)»
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

/** Задержка удаления закрытого тоста из стора (соответствует TOAST_REMOVE_DELAY в модуле). */
const TOAST_REMOVE_DELAY = 300;

let unmountCurrent: (() => void) | null = null;

/**
 * Монтирует потребителя через публичный хук `useToast()` и отдаёт то, что он видит в сторе.
 * Действия над стором выполняются экспортируемыми `toast`/`dismissToast`, наблюдение — через хук.
 */
function mountToastConsumer() {
  const container = document.createElement("div");
  const root: Root = createRoot(container);
  const state: { current: ToastData[] | null } = { current: null };

  function Consumer() {
    const { toasts } = useToast();
    state.current = toasts;
    return null;
  }

  act(() => {
    root.render(<Consumer />);
  });

  const unmount = () => {
    act(() => {
      root.unmount();
    });
  };
  unmountCurrent = unmount;

  return {
    getToasts: () => {
      if (!state.current) throw new Error("Потребитель тостов не смонтирован");
      return state.current;
    },
    unmount,
  };
}

/** Кладёт тост и возвращает его id. */
function addToast(title: string): string {
  let id = "";
  act(() => {
    id = toast({ title, variant: "default" });
  });
  return id;
}

describe("стор тостов (use-toast)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Модульный синглтон живёт между кейсами: закрываем все тосты и даём таймерам удаления сработать.
    act(() => {
      dismissToast();
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY);
    });
  });

  afterEach(() => {
    unmountCurrent?.();
    unmountCurrent = null;
    // Гасим оставшиеся таймеры удаления, иначе их записи застрянут в модульном `toastTimeouts`
    // и следующий кейс не сможет перепланировать удаление (guard `has(toastId)`).
    act(() => {
      vi.runOnlyPendingTimers();
    });
    vi.useRealTimers();
  });

  it("закрытый тост остаётся в сторе с open: false до истечения задержки удаления", () => {
    const consumer = mountToastConsumer();
    const id = addToast("Первый");
    expect(consumer.getToasts()).toHaveLength(1);
    expect(consumer.getToasts()[0].open).toBe(true);

    act(() => {
      dismissToast(id);
    });

    // Тост обязан пережить exit-анимацию, поэтому 299 мс он ещё в сторе, но уже помечен закрытым.
    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY - 1);
    });
    expect(consumer.getToasts()).toHaveLength(1);
    expect(consumer.getToasts()[0].open).toBe(false);
  });

  it("закрытый тост удаляется из стора после задержки", () => {
    const consumer = mountToastConsumer();
    const id = addToast("Первый");

    act(() => {
      dismissToast(id);
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY);
    });

    expect(consumer.getToasts()).toHaveLength(0);
  });

  it("dismissToast() без id закрывает все тосты и убирает их из стора после задержки", () => {
    const consumer = mountToastConsumer();
    addToast("Первый");
    addToast("Второй");
    addToast("Третий");
    expect(consumer.getToasts()).toHaveLength(3);

    act(() => {
      dismissToast();
    });
    expect(consumer.getToasts().map((t) => t.open)).toEqual([false, false, false]);

    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY);
    });
    expect(consumer.getToasts()).toHaveLength(0);
  });

  it("показывает три новых тоста после закрытия двух (закрытые не занимают слоты)", () => {
    const consumer = mountToastConsumer();
    addToast("Первый");
    addToast("Второй");

    act(() => {
      dismissToast();
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY);
    });
    // Если закрытые тосты остаются в сторе, сюда попадут «призраки» и слоты лимита окажутся занятыми.
    expect(consumer.getToasts()).toHaveLength(0);

    addToast("Новый A");
    addToast("Новый B");
    addToast("Новый C");

    const toasts = consumer.getToasts();
    expect(toasts).toHaveLength(3);
    expect(toasts.map((t) => t.open)).toEqual([true, true, true]);
  });

  it("закрытый тост не вытесняет живой тост из лимита стека", () => {
    const consumer = mountToastConsumer();
    addToast("Первый");
    addToast("Второй");
    const closedId = addToast("Третий");

    act(() => {
      dismissToast(closedId);
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_REMOVE_DELAY);
    });
    expect(consumer.getToasts()).toHaveLength(2);

    addToast("Новый");

    // Все три слота должны быть заняты видимыми тостами, а не закрытым «призраком».
    const toasts = consumer.getToasts();
    expect(toasts).toHaveLength(3);
    expect(toasts.map((t) => t.open)).toEqual([true, true, true]);
  });

  it("стек ограничен тремя тостами, вытесняются самые старые", () => {
    const consumer = mountToastConsumer();
    addToast("Первый");
    addToast("Второй");
    addToast("Третий");
    addToast("Четвёртый");

    expect(consumer.getToasts().map((t) => t.title)).toEqual([
      "Четвёртый",
      "Третий",
      "Второй",
    ]);
  });
});
