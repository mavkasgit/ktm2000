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
    // `e2e/` целиком исключать нельзя: там живёт логика прогона (`pass-cache`),
    // которую нужно тестировать vitest'ом. Исключаем сами спеки Playwright —
    // их имена кончаются на `.spec.ts` и vitest'у они не его.
    exclude: ["**/node_modules/**", "**/e2e/**/*.spec.ts", "**/dist/**"],
  },
})
