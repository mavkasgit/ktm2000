import { AlertTriangle, RefreshCw } from "lucide-react"
import { useRouteError } from "react-router-dom"
import { Button } from "@/shared/ui/button"

/**
 * Что именно сломалось, оператору знать не нужно — но нужно знать, что
 * делать. Падение загрузки чанка после деплоя лечится обновлением страницы,
 * а ошибка в самом разделе — нет, и советовать перезагрузку в обоих случаях
 * значит отправлять человека по кругу.
 */
const CHUNK_LOAD_ERROR_MARKERS = [
  "failed to fetch dynamically imported module",
  "error loading dynamically imported module",
  "importing a module script failed",
  "chunkloaderror",
]

/** Ошибка загрузки чанка: браузер не смог принести модуль после деплоя. */
export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const text = `${error.name} ${error.message}`.toLowerCase()
  return CHUNK_LOAD_ERROR_MARKERS.some((marker) => text.includes(marker))
}

export interface RouteErrorScreenProps {
  reason: "chunk" | "unknown"
  onReload?: () => void
}

/**
 * Экран вместо «Unexpected Application Error!» react-router: что произошло
 * и одно действие, которое это чинит.
 */
export function RouteErrorScreen({ reason, onReload = () => window.location.reload() }: RouteErrorScreenProps) {
  return (
    <div
      role="alert"
      className="flex min-h-[200px] w-full flex-col items-center justify-center gap-4 p-8 text-center"
    >
      <AlertTriangle className="h-10 w-10 text-destructive" aria-hidden="true" />
      <h1 className="text-xl font-semibold">Не удалось загрузить раздел</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        {reason === "chunk"
          ? "Приложение обновилось, а вкладка осталась со старой версией. Обновите страницу — раздел откроется заново."
          : "Страница не открылась из-за ошибки. Обновите страницу, а если ошибка останется — сообщите администратору."}
      </p>
      <Button onClick={onReload}>
        <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
        Обновить страницу
      </Button>
    </div>
  )
}

/**
 * `errorElement` маршрута. Стоит на каждом маршруте, потому что неудачная
 * загрузка чанка — это ошибка рендера, и ближайшая граница маршрута должна
 * ловить её раньше, чем это сделает стандартный экран react-router.
 */
export function RouteError() {
  return <RouteErrorScreen reason={isChunkLoadError(useRouteError()) ? "chunk" : "unknown"} />
}
