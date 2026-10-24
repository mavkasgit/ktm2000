import js from "@eslint/js"
import boundaries from "eslint-plugin-boundaries"
import reactHooks from "eslint-plugin-react-hooks"
import tseslint from "typescript-eslint"

/**
 * Границы FSD (issue #333).
 *
 * Слои: app -> modules -> features -> entities -> shared.
 * Внутри слоя features и entities соседние элементы (features/a, features/b)
 * друг друга не видят: общее спускается в entities/shared.
 *
 * Правило опирается на `boundaries/dependencies` (v7): все локальные импорты
 * запрещены по умолчанию, разрешения выданы политиками ниже. Алиасы `@/` и
 * `shared/` разбирает TypeScript-resolver — без него `@/features/...`
 * выглядел бы внешним пакетом и правило молчало бы.
 */
export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "shared-ui/**",
      "**/*.d.ts",
    ],
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",

      // Гигиена существующего кода — отдельные задачи, не #333: линтер не
      // должен падать на дереве из-за них, иначе правило границ не включить.
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/no-explicit-any": "off",

      // Пустые catch — осознанный приём в коде (ошибка уже обработана выше).
      "no-empty": ["error", { allowEmptyCatch: true }],
      // shadcn-паттерн `interface Props extends React.HTMLAttributes<…> {}`.
      "@typescript-eslint/no-empty-object-type": [
        "error",
        { allowInterfaces: "with-single-extends" },
      ],
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      boundaries,
    },
    settings: {
      "boundaries/root-path": "src",
      "import/resolver": {
        typescript: {
          project: "./tsconfig.json",
        },
        node: true,
      },
      "boundaries/elements": [
        { type: "app", pattern: "app", partialMatch: false },
        {
          type: "modules",
          pattern: "modules/*",
          capture: ["module"],
          partialMatch: false,
        },
        {
          type: "features",
          pattern: "features/*",
          capture: ["feature"],
          partialMatch: false,
        },
        {
          type: "entities",
          pattern: "entities/*",
          capture: ["entity"],
          partialMatch: false,
        },
        { type: "shared", pattern: "shared", partialMatch: false },
      ],
    },
    rules: {
      "boundaries/dependencies": [
        "error",
        {
          default: "disallow",
          message:
            "Нарушены архитектурные границы FSD: слой не может импортировать соседний элемент того же слоя; общее вынеси в entities/shared.",
          policies: [
            {
              // app собирает приложение и видит все слои.
              from: { element: { type: "app" } },
              allow: {
                to: {
                  element: {
                    types: ["app", "modules", "features", "entities", "shared"],
                  },
                },
              },
            },
            {
              // modules — переносимые модули: свои файлы, entities и shared.
              from: { element: { type: "modules" } },
              allow: {
                to: { element: { types: ["modules", "entities", "shared"] } },
              },
            },
            {
              // features может брать общее снизу: modules, entities, shared.
              from: { element: { type: "features" } },
              allow: {
                to: { element: { types: ["modules", "entities", "shared"] } },
              },
            },
            {
              // Соседняя фича — запрещена, даже если общий код пока лежит в ней.
              from: { element: { type: "features" } },
              disallow: { to: { element: { type: "features" } } },
              message:
                "features не может импортировать features; общее вынеси в entities/shared.",
            },
            {
              // entities видит только shared: соседние сущности друг друга
              // не импортируют — общее правило и для features (см. docstring).
              from: { element: { type: "entities" } },
              allow: { to: { element: { types: ["shared"] } } },
            },
            {
              from: { element: { type: "shared" } },
              allow: { to: { element: { type: "shared" } } },
            },
          ],
        },
      ],
    },
  },
)
