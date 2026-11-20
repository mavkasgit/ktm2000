"use strict";
// Тесты умного pre-push гейта (scripts/ci/pre-push-gate.mjs).

const { test } = require("node:test");
const assert = require("node:assert/strict");

const load = () => import("./pre-push-gate.mjs");

test("parsePushRefs: читает четыре поля строки git pre-push", async () => {
  const { parsePushRefs } = await load();
  assert.deepEqual(parsePushRefs("refs/heads/feat abc refs/heads/feat def\n"), [
    {
      localRef: "refs/heads/feat",
      localSha: "abc",
      remoteRef: "refs/heads/feat",
      remoteSha: "def",
    },
  ]);
});

test("shouldSkipRefs: только теги/удаления -> skip", async () => {
  const { parsePushRefs, shouldSkipRefs } = await load();
  assert.equal(
    shouldSkipRefs(parsePushRefs("refs/tags/v1 abc refs/tags/v1 abc\n")),
    true,
  );
  assert.equal(
    shouldSkipRefs(parsePushRefs("(delete) 000 refs/heads/old abc\n")),
    true,
  );
});

test("shouldSkipRefs: ветка -> не skip", async () => {
  const { parsePushRefs, shouldSkipRefs } = await load();
  assert.equal(
    shouldSkipRefs(parsePushRefs("refs/heads/feat abc refs/heads/feat def\n")),
    false,
  );
});

test("shouldSkipRefs: пустой stdin (ручной запуск) -> не skip", async () => {
  const { shouldSkipRefs } = await load();
  assert.equal(shouldSkipRefs([]), false);
});

test("buildGateArgs: full -> полный gate со strict", async () => {
  const { buildGateArgs } = await load();
  assert.deepEqual(buildGateArgs({ scope: "full", steps: null }), [
    "scripts/gate.mjs",
    "--strict",
  ]);
});

test("buildGateArgs: скоуп -> --only со списком и strict", async () => {
  const { buildGateArgs } = await load();
  assert.deepEqual(
    buildGateArgs({ scope: "docs", steps: ["docs-links", "adr-index"] }),
    ["scripts/gate.mjs", "--only=docs-links,adr-index", "--strict"],
  );
});
