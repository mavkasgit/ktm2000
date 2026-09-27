import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router-dom"
import { router } from "./Router"
import { Toaster } from "@/shared/ui"
import { AuthProvider } from "@/features/auth/hooks/useAuth"
import { startAppVersionWatch } from "@/shared/lib/appVersionWatch"
import { applyTheme, readStoredTheme } from "@user/ui"
import "./styles.css"


applyTheme(readStoredTheme())

startAppVersionWatch()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
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

