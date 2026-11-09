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
    setupFiles: ["@testing-library/jest-dom/vitest", "./vitest.setup.ts"],
    // `e2e/` целиком исключать нельзя: там живёт логика прогона (`pass-cache`),
    // которую нужно тестировать vitest'ом. Исключаем сами спеки Playwright —
    // их имена кончаются на `.spec.ts` и vitest'у они не его.
    exclude: ["**/node_modules/**", "**/e2e/**/*.spec.ts", "**/dist/**"],
    // Гейт покрытия: решения грилла #245 (Q13, Q5=1). Первый замер 2026-10-01 —
    // statements/lines 43.99%, branches 72.66%, functions 44.97% (1093 passed).
    // Порог — округление вниз: ловит падение покрытия, но не краснеет от мелкой
    // правки. Гейт блокирующий: падение порога валит `vitest run` (и CI-джоб).
    //
    // Замер 2026-11-03 (#373), `npx vitest run --coverage`, 1537 passed / 1
    // skipped: statements 56.53%, lines 56.53%, branches 75.36%, functions
    // 49.72%. Способность падать показана пробником: порог statements 60 (>
    // фактических 56.53%) дал `ERROR: Coverage for statements (56.53%) does not
    // meet global threshold (60%)` и код выхода 1 при зелёных тестах; после
    // возврата — код 0. Пороги ниже НЕ «подогнаны» под новую цифру: они
    // остаются на уровне первого замера, чтобы красить именно регресс, а рост
    // порога — отдельное решение. Надпись шага CI раньше противоречила
    // («report-only, no threshold yet») — в #373 исправлена на фактические пороги.
    coverage: {
      // `functions` добавлен в #373: порог был единственный, кто отсутствовал
      // (замер 49.72% — то есть цифра давно есть, а гейта не было).
      thresholds: { statements: 43, lines: 43, branches: 72, functions: 49 },
    },
  },
})
