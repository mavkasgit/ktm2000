import { vi } from "vitest";

/**
 * Ширина окна для тестов респонсивных компонентов.
 *
 * `useMediaQuery` (и гейт доски «десктопная таблица / мобильные карточки»)
 * спрашивает `window.matchMedia`; happy-dom по умолчанию даёт десктопную
 * ширину (1024), и вторая ветка в рендере не появляется. Тест, которому нужна
 * вторая ветка, ставит свою ширину ДО `render` и снимает в `afterEach`
 * (`vi.restoreAllMocks`).
 */
export function stubViewportWidth(width: number): void {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    const matches = min ? width >= Number(min[1]) : max ? width <= Number(max[1]) : false;
    return {
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList;
  });
}
