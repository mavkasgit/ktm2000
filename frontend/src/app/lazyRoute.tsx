import { Suspense, lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from "react"
import { Loader2 } from "lucide-react"

/**
 * Страница раздела приходит отдельным чанком: оператор ждёт тот раздел, в
 * который зашёл, а не все двадцать одна сразу (ADR-0039).
 *
 * Ссылку на модуль страницы роутер берёт **по файлу страницы**, а не через
 * public API фичи: один импорт барела кладёт в чанк все страницы фичи, и
 * ленивая загрузка перестаёт экономить.
 */
export function lazyPage<M extends Record<string, unknown>, K extends keyof M>(
  loader: () => Promise<M>,
  name: K,
): LazyExoticComponent<ComponentType> {
  return lazy(async () => {
    const module = await loader()
    const page = module[name]
    if (!page) {
      throw new Error(`Страница ${String(name)} не экспортирована модулем`)
    }
    return { default: page as ComponentType }
  })
}

/**
 * Пока едет чанк, на месте раздела — спиннер, а не пустое место. Граница
 * стоит вокруг содержимого маршрута, поэтому каркас (меню, профиль) на
 * переходе не исчезает.
 */
export function RoutePending() {
  return (
    <div
      role="status"
      aria-label="Загрузка раздела"
      data-testid="route-pending"
      className="flex min-h-[200px] w-full items-center justify-center p-8"
    >
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  )
}

/**
 * Граница ожидания на содержимом маршрута. Навигация идёт через
 * `startTransition` (`v7_startTransition` в `main.tsx`), поэтому фолбэк
 * приходится на первое появление раздела — прямую ссылку и перезагрузку,
 * где предыдущего экрана нет, — и не мигает на переходе.
 */
export function RouteBoundary({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RoutePending />}>{children}</Suspense>
}
