import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export interface UseFullscreenElementOptions {
  /** Вошли в полный экран (в том числе повторно, после отказа). */
  onEnter?: () => void;
  /** Вышли из полного экрана — своим `exit()`, Esc или кнопкой браузера. */
  onExit?: () => void;
  /** Вход/выход не удался; промис при этом всё равно отклоняется. */
  onError?: (error: unknown) => void;
}

export interface UseFullscreenElementReturn {
  /** Целевой элемент сейчас в полноэкранном режиме. */
  value: boolean;
  enter: () => Promise<void>;
  exit: () => Promise<void>;
  toggle: () => Promise<void>;
}

/**
 * Полноэкранный режим для конкретного элемента: промисы, ошибка наружу.
 *
 * `exit()` закрывает только свой элемент: если на странице открыт чужой
 * fullscreen, хук его не трогает.
 */
// TODO: убрать после фикса useFullscreen в @siberiacancode/reactuse
// (siberiacancode/reactuse#516): пакетный хук возвращает void из enter()/exit(),
// из-за чего отказ requestFullscreen без жеста в киоске не поймать.
export function useFullscreenElement<T extends Element>(
  ref: RefObject<T | null>,
  options: UseFullscreenElementOptions = {},
): UseFullscreenElementReturn {
  const [value, setValue] = useState(false);
  // Опции обычно приходят литералом на каждый рендер; через ref `enter` и
  // `exit` не меняют идентичность из-за нового объекта колбэков.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  // Последний элемент, который мы сами открыли: нужен в cleanup, когда React
  // уже отвязал ref, а fullscreen всё ещё наш.
  const enteredRef = useRef<Element | null>(null);

  const enter = useCallback(async () => {
    const element = ref.current;
    if (!element) return;
    try {
      await requestFullscreen(element);
      enteredRef.current = element;
    } catch (error) {
      optionsRef.current.onError?.(error);
      throw error;
    }
  }, [ref]);

  const exit = useCallback(async () => {
    const target = ref.current ?? enteredRef.current;
    if (!target || fullscreenElement() !== target) return;
    try {
      await exitFullscreen();
      enteredRef.current = null;
    } catch (error) {
      optionsRef.current.onError?.(error);
      throw error;
    }
  }, [ref]);

  const toggle = useCallback(async () => {
    const target = ref.current ?? enteredRef.current;
    if (target && fullscreenElement() === target) {
      await exit();
    } else {
      await enter();
    }
  }, [enter, exit, ref]);

  useEffect(() => {
    const element = ref.current;
    let active = element !== null && fullscreenElement() === element;
    setValue(active);

    const sync = () => {
      const current = ref.current;
      if (!current) return;
      const next = fullscreenElement() === current;
      if (next === active) return;
      active = next;
      setValue(next);
      if (next) optionsRef.current.onEnter?.();
      else optionsRef.current.onExit?.();
    };

    document.addEventListener("fullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
    };
  }, [ref]);

  return { value, enter, exit, toggle };
}

function fullscreenElement(): Element | null {
  return document.fullscreenElement ?? null;
}

function requestFullscreen(element: Element): Promise<void> {
  if (typeof element.requestFullscreen !== "function") {
    throw new Error("Fullscreen API недоступен в этом браузере");
  }
  return element.requestFullscreen(); // reactuse-ok: обёртка Fullscreen API — enter() ReactUse не возвращает промис (upstream #516)
}

function exitFullscreen(): Promise<void> {
  if (typeof document.exitFullscreen !== "function") {
    throw new Error("Fullscreen API недоступен в этом браузере");
  }
  return document.exitFullscreen(); // reactuse-ok: обёртка Fullscreen API — exit() ReactUse не возвращает промис (upstream #516)
}
