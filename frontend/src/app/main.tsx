import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router-dom"
import { router } from "./Router"
import { Toaster } from "@/shared/ui"
import { AuthProvider } from "@/entities/auth"
import { startAppVersionWatch } from "@/shared/lib/appVersionWatch"
import { OPERATIONAL_POLL_INTERVAL_MS } from "@/shared/api/operationalPolling"
import { applyTheme, readStoredTheme } from "@user/ui"
import "./styles.css"


applyTheme(readStoredTheme())

startAppVersionWatch()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // `staleTime` равен интервалу опроса: свежесть операционных экранов
      // держит один механизм — 12-секундный `refetchInterval`
      // (`shared/api/operationalPolling`, ADR-0041). Дублировать её здесь
      // коротким значением значит получить второй источник свежести, который
      // на возврате фокуса перечитывает списки в обход опроса. Реестр сброса
      // (`shared/api/cacheInvalidation`) остаётся единственным способом
      // принудительно обновить данные после бизнес-действия.
      staleTime: OPERATIONAL_POLL_INTERVAL_MS,
      // Возврат на вкладку перечитывает только устаревшее: запрос моложе
      // `staleTime` (12 с) фокус не трогает, поэтому всплеска на каждый
      // alt-tab нет. Для опрашиваемых экранов первичен 12-секундный
      // `refetchInterval` (ADR-0041), фокус — бесплатный вторичный триггер;
      // для неопрашиваемых (склад, справочники, журнал, план) возврат фокуса
      // остаётся единственным автоматическим способом перечитать данные.
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})

function App() {
  return (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        {/* Раздел приезжает своим чанком. Навигация идёт через
            `startTransition`, поэтому React не прячет уже показанный раздел,
            пока едет чанк: фокус не теряется, «белого экрана» нет. */}
        <RouterProvider router={router} future={{ v7_startTransition: true }} />
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  )
}

createRoot(document.getElementById("root")!).render(<App />)

