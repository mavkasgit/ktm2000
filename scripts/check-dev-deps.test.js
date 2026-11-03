/**
 * Тесты логики `scripts/check-dev-deps-core.js` — проверка мёртвых
 * dev-зависимостей фронтенда (#374).
 *
 * Запуск: `npm run test:scripts` (`node --test`, без внешних зависимостей).
 *
 * Класс ошибок, против которого написана проверка: в devDependencies лежит
 * пакет, который никто не зовёт, и «мёртвость» утверждается на глаз по grep'у.
 * Утверждение оказалось неверным: `@testing-library/jest-dom` помечали мёртвым,
 * хотя `vitest.config.ts` подключает его через `setupFiles` под именем с
 * подпутём. Отсюда два требования к коду: использование ищется и по имени
 * пакета, и по его бинарникам (`tsc` для `typescript`), а любое «не вижу» —
 * это находка с именем, а не тихое удаление.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  inspectDevDependencies,
  isCodeFile,
  withoutComments,
  withoutDependencyDeclarations,
} = require("./check-dev-deps-core");

const NO_EXEMPT = { adopted: "2026-11-03", exempt: {} };

/** Пакет с указанными бинарниками (их читает CLI из node_modules). */
function pkg(name, bins = []) {
  return { name, bins };
}

test("пакет, не названный ни в одном файле, — находка", () => {
  const findings = inspectDevDependencies({
    packages: [pkg("мёртвый-пакет")],
    files: [{ path: "src/app/main.ts", text: 'import { x } from "./x";' }],
    allowlist: NO_EXEMPT,
  });
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "unused");
  assert.equal(findings[0].name, "мёртвый-пакет");
  // Сообщение обязано назвать, где именно искали, иначе «не нашёл» неотличимо
  // от «не смотрел».
  assert.match(findings[0].message, /1 файл/);
});

test("зовут по бинарнику — пакет жив", () => {
  // `typescript` никто не импортирует и не называет: его зовут как `tsc`
  // (`npm run typecheck` → `tsc -b`). Проверка по одному имени пакета дала бы
  // ложный «мёртвый», то есть ровно тот дефект, из-за которого тикет #374
  // и появился с неверной посылкой.
  const findings = inspectDevDependencies({
    packages: [pkg("typescript", ["tsc", "tsserver"])],
    files: [{ path: "package.json", text: '{"scripts": {"typecheck": "tsc -b"}}' }],
    allowlist: NO_EXEMPT,
  });
  assert.deepEqual(findings, []);
});

test("исключение с причиной гасит находку", () => {
  // Класс ложных срабатываний: провайдер покрытия или постпроцессор зовётся не
  // по имени пакета, а по короткому имени внутри чужого конфига
  // (`coverage.provider: "v8"`, `plugins: [tailwindcss]`). Такие пакеты живут в
  // исключениях списком с причиной — а не отключением проверки целиком (критерий
  // (в) тикета #374).
  const findings = inspectDevDependencies({
    packages: [pkg("@vitest/coverage-v8")],
    files: [{ path: "vitest.config.ts", text: "coverage: { provider: 'v8' }" }],
    allowlist: {
      adopted: "2026-11-03",
      exempt: { "@vitest/coverage-v8": { reason: "зовётся как provider: 'v8'", reviewBy: "2027-04-01" } },
    },
  });
  assert.deepEqual(findings, []);
});

test("исключение с истёкшим сроком пересмотра — находка", () => {
  // Датированные исключения (#386): право не видеть пакет у исключения есть
  // только до даты пересмотра. После неё находка обязана вернуться, иначе
  // список превращается в молчание вместо проверки.
  const findings = inspectDevDependencies({
    packages: [pkg("мёртвый-пакет")],
    files: [{ path: "src/app/main.ts", text: "export const x = 1;" }],
    allowlist: {
      adopted: "2026-05-01",
      exempt: {
        "мёртвый-пакет": { reason: "переживём до миграции на vite 7", reviewBy: "2026-10-01" },
      },
    },
    now: "2026-11-03",
  });
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "expired");
  assert.equal(findings[0].name, "мёртвый-пакет");
  assert.match(findings[0].message, /2026-10-01/);
  assert.match(findings[0].message, /переживём до миграции/);
});

test("исключение на пакет, который снова называют, — находка", () => {
  const findings = inspectDevDependencies({
    packages: [pkg("happy-dom")],
    files: [{ path: "vitest.config.ts", text: 'environment: "happy-dom"' }],
    allowlist: {
      adopted: "2026-11-03",
      exempt: { "happy-dom": { reason: "используется в двух тестах", reviewBy: "2027-04-01" } },
    },
    now: "2026-11-03",
  });
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "unnecessary");
  assert.match(findings[0].message, /удалите/);
});

test("исключение без даты пересмотра — находка", () => {
  // Правило датированных исключений (#386): без даты «временно» неотличимо от
  // «навсегда», и список перестаёт обсуждаться. Проверка требует и причину, и
  // срок, иначе сама становится тем молчанием, против которого её писали.
  const findings = inspectDevDependencies({
    packages: [pkg("happy-dom")],
    files: [{ path: "src/main.ts", text: "export const x = 1;" }],
    allowlist: {
      adopted: "2026-11-03",
      exempt: { "happy-dom": { reason: "кажется полезным" } },
    },
    now: "2026-11-03",
  });
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "undated");
  assert.match(findings[0].message, /reviewBy/);
});

test("исключение на пакет, которого нет в devDependencies, — находка", () => {
  const findings = inspectDevDependencies({
    packages: [pkg("vite", ["vite"])],
    files: [{ path: "vite.config.ts", text: "import { defineConfig } from 'vite';" }],
    allowlist: {
      adopted: "2026-11-03",
      exempt: { "уже-удалён": { reason: "пакет убрали из дерева", reviewBy: "2027-04-01" } },
    },
    now: "2026-11-03",
  });
  assert.equal(findings.length, 1);
  assert.equal(findings[0].code, "unknown");
  assert.equal(findings[0].name, "уже-удалён");
});

test("объявление пакета в devDependencies — не использование", () => {
  // Ловушка, в которую проверка обязана было попасть: каждое имя пакета стоит
  // в его же объявлении (`frontend/package.json`), поэтому наивный поиск по
  // тексту дерева даёт «все 21 пакет названы» при полностью мёртвом наборе.
  // Это тавтология, а не проверка: ожидаемое значение пересчитывается тем же
  // способом, что и проверяется.
  const manifest = JSON.stringify(
    {
      scripts: { typecheck: "tsc -b" },
      dependencies: { react: "18.3.0" },
      devDependencies: { "@vitest/coverage-v8": "1.6.0", typescript: "5.5.4" },
    },
    null,
    2,
  );

  const projected = withoutDependencyDeclarations(manifest);
  assert.ok(!projected.includes("@vitest/coverage-v8"), "объявление не должно искаться");
  assert.ok(!projected.includes("18.3.0"), "версии зависимостей — тоже объявления");
  // Скрипты остаются: `tsc -b` — это и есть доказательство, что пакет используют.
  assert.match(projected, /tsc -b/);
});

test("не-манифест и битый JSON проходят без изменений", () => {
  assert.equal(withoutDependencyDeclarations('import "x";'), 'import "x";');
  const broken = '{"scripts": {"a": "b"},';
  assert.equal(withoutDependencyDeclarations(broken), broken);
});

test("комментарий в корневом скрипте — не использование", () => {
  // Иначе проверка читает свои же объяснения и чужие магические строки как
  // вызовы. Комментарии вырезаются только для root-скана (см. CLI).
  assert.equal(
    withoutComments("// @vitest/coverage-v8\nconst x = 1;", "a.js"),
    "\nconst x = 1;",
  );
  assert.match(withoutComments("const u = 'https://x';", "a.js"), /https:\/\/x/);
});

test("Markdown не считается использованием пакета", () => {
  // Имя пакета в README/AGENTS — проза: иначе проверка оставляла бы мёртвый
  // пакет живым ровно потому, что о нём кто-то написал.
  assert.equal(isCodeFile("frontend/AGENTS.md"), false);
  assert.equal(isCodeFile("docs/quality/gates.md"), false);
  assert.equal(isCodeFile("README.md"), false);
  // Код и конфиги — считаются, включая extensionless Dockerfile.
  assert.equal(isCodeFile("frontend/vitest.config.ts"), true);
  assert.equal(isCodeFile("package.json"), true);
  assert.equal(isCodeFile("mise.toml"), true);
  assert.equal(isCodeFile("Dockerfile"), true);
});
