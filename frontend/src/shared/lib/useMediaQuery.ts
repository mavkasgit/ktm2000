import { useEffect, useState } from "react";

/**
 * Состояние медиазапроса вместо отрисовки двух раскладок сразу.
 *
 * CSS-классы `hidden md:block` / `md:hidden` прячут неверный экран вёрсткой,
 * но обе ветки всё равно строятся: доска участка рисовала и таблицу, и
 * мобильные карточки, платя за каждую строку дважды. Хук отдаёт, какой экран
 * активен, и компонент выбирает одну ветку, сохраняя обе кодовые ветки.
 *
 * Значение читается синхронно на первом рендере (без лишнего кадра с пустым
 * экраном) и обновляется по `change` — поворот планшета не требует
 * перезагрузки. Если `matchMedia` в окружении нет, возвращается `false`:
 * компонент обязан рисовать осмысленное состояние и без хука.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => readMediaQuery(query));

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mediaQueryList = window.matchMedia(query);
    const handleChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    // Синхронизация на случай, если запрос уже изменился между рендером и
    // подпиской (быстрая смена ширины окна).
    setMatches(mediaQueryList.matches);

    if (typeof mediaQueryList.addEventListener === "function") {
      mediaQueryList.addEventListener("change", handleChange);
      return () => mediaQueryList.removeEventListener("change", handleChange);
    }
    // Safari < 14 и старые WebKit знают только устаревший API.
    const legacyList = mediaQueryList as unknown as {
      addListener: (listener: (event: MediaQueryListEvent) => void) => void;
      removeListener: (listener: (event: MediaQueryListEvent) => void) => void;
    };
    legacyList.addListener(handleChange);
    return () => legacyList.removeListener(handleChange);
  }, [query]);

  return matches;
}

function readMediaQuery(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(query).matches;
}
