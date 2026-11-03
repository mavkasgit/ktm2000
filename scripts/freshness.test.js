"use strict";
// Юнит-тесты разбора свежести инструментов (#368). Ядро — чистая функция:
// сети и файловой системы в ней нет, поэтому все состояния, которые CLI
// собирает по git и реестрам, проверяются здесь на literal-ах.

const test = require("node:test");
const assert = require("node:assert/strict");

const { inspectFreshness, DEFAULT_THRESHOLDS, distNameFromPin } = require("./freshness-core.js");

const NOW = "2026-11-03";

/** Запись реестра с возрастом пина в днях: считаем от NOW, даты не подправляем. */
function entry(over = {}) {
  return {
    id: "ruff",
    name: "Ruff",
    version: "0.16.9",
    pinned_in: "backend/requirements-dev.txt",
    pin_exists: true,
    pin_committed_at: "2026-10-20",
    last_reviewed: "2026-11-01",
    ...over,
  };
}

function codes(findings) {
  return findings.map((f) => f.code).sort();
}

test("свежий пин без данных об апстриме не даёт флагов", () => {
  const findings = inspectFreshness([entry()], DEFAULT_THRESHOLDS, NOW);
  assert.deepEqual(findings, []);
});

test("пин-файл не найден — флаг fail: реестр врёт о том, где живёт версия", () => {
  const findings = inspectFreshness(
    [entry({ pinned_in: "backend/requirements-нет.txt", pin_exists: false })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["pin-missing"]);
  assert.equal(findings[0].level, "fail");
  assert.match(findings[0].message, /backend\/requirements-нет\.txt/);
});

test("пин не трогали дольше порога осмотра — warn, не fail", () => {
  // 181 день от 2026-05-06 до 2026-11-03.
  const findings = inspectFreshness(
    [entry({ pin_committed_at: "2026-05-06", last_reviewed: NOW })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["pin-stale"]);
  assert.equal(findings[0].level, "warn");
  assert.match(findings[0].message, /181/);
});

test("пропущен и осмотр, и пин — флаг по худшему из двух, а не два подряд", () => {
  const findings = inspectFreshness(
    [entry({ pin_committed_at: "2025-06-01", last_reviewed: "2025-06-01" })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["pin-stale"]);
  assert.equal(findings[0].level, "fail");
});

test("апстрима в записи нет — проверки по версии нет, и это не флаг", () => {
  const findings = inspectFreshness([entry({ upstream: undefined })], DEFAULT_THRESHOLDS, NOW);
  assert.deepEqual(findings, []);
});

test("доступна более свежая версия — warn с обеими версиями в тексте", () => {
  const findings = inspectFreshness(
    [entry({ version: "0.16.9", upstream: { latest_version: "0.17.3" } })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["newer-upstream"]);
  assert.equal(findings[0].level, "warn");
  assert.match(findings[0].message, /0\.16\.9/);
  assert.match(findings[0].message, /0\.17\.3/);
});

test("диапазон в пине сравнивается по числу, а не строкой: ^5.7.2 против 5.9.2 — флаг", () => {
  const findings = inspectFreshness(
    [entry({ id: "typescript", version: "^5.7.2", upstream: { latest_version: "5.9.2" } })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["newer-upstream"]);
});

test("pin по commit-sha не сравнивается с тегом — флаг не выдумывается", () => {
  const findings = inspectFreshness(
    [
      entry({
        id: "action-checkout",
        version: "@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0",
        upstream: { latest_version: "v5.0.0" },
      }),
    ],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  // Строка с sha не сопоставима с тегом: молчание лучше выдуманного флага,
  // но состояние должно быть видно — отдельный код, уровень info.
  assert.deepEqual(codes(findings), ["uncomparable"]);
  assert.equal(findings[0].level, "info");
});

test("репозиторий в архиве — fail: обновляться инструменту некуда", () => {
  const findings = inspectFreshness(
    [entry({ upstream: { latest_version: "0.16.9", archived: true } })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["archived"]);
  assert.equal(findings[0].level, "fail");
});

test("переименование owner/repo — warn: пин по старому пути молча перестанет обновляться", () => {
  const findings = inspectFreshness(
    [entry({ upstream: { latest_version: "0.16.9", renamed_to: "astral-sh/ruff" } })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["renamed"]);
  assert.equal(findings[0].level, "warn");
  assert.match(findings[0].message, /astral-sh\/ruff/);
});

test("опрос реестра упал — warn про неизвестность, а не «всё свеже»", () => {
  const findings = inspectFreshness(
    [entry({ upstream: { error: "timeout" } })],
    DEFAULT_THRESHOLDS,
    NOW,
  );
  assert.deepEqual(codes(findings), ["upstream-unknown"]);
  assert.equal(findings[0].level, "warn");
});

const REQS = [
  "# зависимости для тестов",
  "ruff==0.16.9",
  "coverage==7.16.2",
  "pytest==9.1.1  # фикстуры и параллельность",
  "pytest-xdist>=3.8.0",
  "",
].join("\n");

test("имя дистрибутива берётся из строки пина, а не из красивого имени", () => {
  // «coverage.py» — имя в реестре, на PyPI такого нет: 404 выглядел бы как
  // «инструмент не отвечает», хотя не отвечаем мы сами.
  assert.equal(distNameFromPin(REQS, "7.16.2"), "coverage");
  assert.equal(distNameFromPin(REQS, "9.1.1"), "pytest");
  assert.equal(distNameFromPin(REQS, "3.8.0"), "pytest-xdist");
});

test("версии в пине нет — имя не выдумывается", () => {
  assert.equal(distNameFromPin(REQS, "1.2.3"), null);
  assert.equal(distNameFromPin("", "7.16.2"), null);
});

test("версия реестра с оператором диапазона (>=1.13.0) — имя находится то же", () => {
  // В реестре alembic закреплён как «>=1.13.0», в requirements.txt — строка
  // `alembic>=1.13.0`: сравнивать надо числа, а не строки с префиксами.
  assert.equal(distNameFromPin("alembic>=1.13.0\n", ">=1.13.0"), "alembic");
});
