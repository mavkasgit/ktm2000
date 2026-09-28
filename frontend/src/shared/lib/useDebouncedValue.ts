import { useCallback, useEffect, useRef, useState } from "react";

/** Пауза перед запросом по поиску, принятая в приложении, мс. */
export const SEARCH_DEBOUNCE_MS = 300;

/**
 * Значение с задержкой перед тем, как попасть в запрос (#197).
 *
 * Пауза нужна, чтобы набор слова не порождал запрос на каждую букву. Само
 * значение отдаётся сразу: задерживается только запрос, а не ввод — иначе
 * поле не откликается на первое нажатие.
 *
 * Пауза начинается заново на каждое изменение, поэтому при быстром наборе
 * наружу выходит только последнее значение. Задержка `0` отдаёт значение
 * без паузы — для полей, где запрос идёт по каждому изменению.
 */
export function useDebouncedValue<T>(value: T, delayMs: number = SEARCH_DEBOUNCE_MS): T {
  return useDebounced(value, delayMs).value;
}

/**
 * То же, но с возможностью применить значение немедленно — для полей, где
 * `Enter` означает «искать сейчас», а не «дождаться паузы». Это выход из
 * одного хука, а не вторая реализация: показ «2,5 с» против «2,8 с» из-за
 * двух разных правил ожидания — ровно тот дефект, который тикет и убирает.
 */
export function useFlushableDebouncedValue<T>(
  value: T,
  delayMs: number = SEARCH_DEBOUNCE_MS,
): { value: T; flush: () => void } {
  return useDebounced(value, delayMs);
}

function useDebounced<T>(
  value: T,
  delayMs: number,
): { value: T; flush: () => void } {
  const [debounced, setDebounced] = useState(value);
  // Текущее значение нужно и таймеру, и flush, а менять state на каждый
  // ввод нельзя — иначе перерендер на символ.
  const latest = useRef(value);
  latest.current = value;

  useEffect(() => {
    if (delayMs <= 0) {
      setDebounced(value);
      return;
    }
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  const flush = useCallback(() => {
    setDebounced(latest.current);
  }, []);

  return { value: debounced, flush };
}
