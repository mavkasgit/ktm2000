import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_AGE_DAYS,
  checkProofCoverage,
  daysSince,
  isExpired,
  summarize,
} from "./proof-coverage-core.mjs";

const TODAY = new Date("2026-11-20T12:00:00Z");

const entry = (over = {}) => ({
  reason: "шаг меняет живую базу стенда",
  becomes_possible: "когда появится клон стенда (#379) — тогда шаг накатывает миграции на него",
  reviewed: "2026-11-20",
  expires: "2027-05-01",
  ...over,
});

test("дни считаются по календарю, а не по часам", () => {
  assert.equal(daysSince("2026-11-20", TODAY), 0);
  assert.equal(daysSince("2026-11-19", TODAY), 1);
  assert.equal(daysSince("2026-05-24", TODAY), MAX_AGE_DAYS);
  assert.equal(daysSince("не дата", TODAY), null);
});

test("срок истекает со следующего дня, а не в день expires", () => {
  assert.equal(isExpired("2026-11-20", TODAY), false, "сегодня — ещё не истёк");
  assert.equal(isExpired("2026-11-21", TODAY), false, "будущее — не истёк");
  assert.equal(isExpired("2026-11-19", TODAY), true, "вчера — истёк");
});

test("корректное исключение со сроком — зелёное", () => {
  const result = checkProofCoverage(
    { steps: { ruff: { proven_at: "2026-11-03" } }, exempt: { "alembic-drift": entry() } },
    { steps: ["ruff", "alembic-drift"], today: TODAY },
  );
  assert.deepEqual(result.problems, []);
  assert.deepEqual(result.warnings, []);
  assert.deepEqual(result.uncovered, []);
  assert.equal(result.exemptCount, 1);
  assert.match(summarize(result), /2\/2 шагов/);
});

test("истёкший expires — красное, а не «когда-нибудь»", () => {
  const result = checkProofCoverage(
    { steps: {}, exempt: { "e2e-smoke": entry({ expires: "2026-11-19" }) } },
    { steps: ["e2e-smoke"], today: TODAY },
  );
  assert.equal(result.problems.length, 1);
  assert.match(result.problems[0], /срок истёк 2026-11-19/);
});

test("битый формат даты — красное", () => {
  const result = checkProofCoverage(
    { steps: {}, exempt: { "e2e-smoke": entry({ reviewed: "20.11.2026", expires: "soon" }) } },
    { steps: ["e2e-smoke"], today: TODAY },
  );
  assert.equal(result.problems.length, 2);
  assert.match(result.problems.join("\n"), /reviewed должен быть YYYY-MM-DD/);
  assert.match(result.problems.join("\n"), /expires должен быть YYYY-MM-DD/);
});

test("обзор старше порога — warn, а не красное", () => {
  const stale = `2026-05-23`; // 181 день
  const result = checkProofCoverage(
    { steps: {}, exempt: { "test-hygiene": entry({ reviewed: stale }) } },
    { steps: ["test-hygiene"], today: TODAY },
  );
  assert.deepEqual(result.problems, []);
  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /181 дней/);
  assert.match(summarize(result), /1 просроченных обзоров/);
});

test("исключение без причины или без условия — красное", () => {
  const result = checkProofCoverage(
    { steps: {}, exempt: { "test-hygiene": entry({ reason: "  ", becomes_possible: "" }) } },
    { steps: ["test-hygiene"], today: TODAY },
  );
  assert.equal(result.problems.length, 2);
  assert.match(result.problems.join("\n"), /без reason/);
  assert.match(result.problems.join("\n"), /без becomes_possible/);
});

test("исключение строкой (старый формат) — красное: срок не проверить", () => {
  const result = checkProofCoverage(
    { steps: {}, exempt: { "e2e-smoke": "берёт слот семафора" } },
    { steps: ["e2e-smoke"], today: TODAY },
  );
  assert.equal(result.problems.length, 1);
  assert.match(result.problems[0], /должна быть объектом/);
});

test("шаг без доказательства и без исключения попадает в uncovered", () => {
  const result = checkProofCoverage(
    { steps: { ruff: {} }, exempt: {} },
    { steps: ["ruff", "pins"], today: TODAY },
  );
  assert.deepEqual(result.uncovered, ["pins"]);
  assert.deepEqual(result.problems, []);
});
