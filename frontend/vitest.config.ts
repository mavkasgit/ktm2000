import { defineConfig } from "vitest/config"
import { fileURLToPath, URL } from "node:url"

export default defineConfig({
  resolve: {
    alias: {
      shared: fileURLToPath(new URL("./src/shared", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    fs: {
      // Сквозная проверка иконок читает backend-сиды (../../backend/...) — разрешаем.
      allow: [fileURLToPath(new URL("..", import.meta.url))],
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    // Матчеры @testing-library/jest-dom (toBeInTheDocument и др.) — пакет в
    // devDependencies с самого начала, подключён решением #245 (Q12).
    setupFiles: ["@testing-library/jest-dom/vitest"],
    // `e2e/` целиком исключать нельзя: там живёт логика прогона (`pass-cache`),
    // которую нужно тестировать vitest'ом. Исключаем сами спеки Playwright —
    // их имена кончаются на `.spec.ts` и vitest'у они не его.
    exclude: ["**/node_modules/**", "**/e2e/**/*.spec.ts", "**/dist/**"],
    // Гейт покрытия: решения грилла #245 (Q13, Q5=1). Первый замер 2026-10-01 —
    // statements/lines 43.99%, branches 72.66%, functions 44.97% (1093 passed).
    // Порог — округление вниз: ловит падение покрытия, но не краснеет от мелкой
    // правки. Гейт блокирующий: падение порога валит `vitest run` (и CI-джоб).
    coverage: {
      thresholds: { statements: 43, lines: 43, branches: 72 },
    },
  },
})
