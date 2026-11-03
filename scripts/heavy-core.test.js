"use strict";
// Тесты машинного семафора (scripts/heavy-core.mjs). Запускаются шагом
// `npm run test:scripts` — то есть в быстром ярусе гейта.
//
// Ядро — ESM (его импортирует и frontend/e2e/run-slots.mjs), поэтому здесь
// динамический import: корневой package.json не объявляет "type": "module".

const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const dirs = [];
const load = () => import("./heavy-core.mjs");

function tempDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ktm2000-heavy-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  while (dirs.length > 0) {
    fs.rmSync(dirs.pop(), { recursive: true, force: true });
  }
});

/** Поддельный spawn: команда не запускается, выход задаёт тест. */
function fakeSpawn({ exit = 0 } = {}) {
  const calls = [];
  const fn = (command, options) => {
    calls.push({ command, options });
    const child = new EventEmitter();
    child.kill = () => {};
    setImmediate(() => child.emit("exit", exit, null));
    return child;
  };
  fn.calls = calls;
  return fn;
}

function occupy(dir, index, holder) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `slot-${index}.json`), JSON.stringify(holder));
}

test("resolveSlotCount: четверть ядер, но не меньше одного", async () => {
  const { resolveSlotCount } = await load();
  assert.equal(resolveSlotCount({ env: {}, cpus: () => new Array(8).fill({}) }), 2);
  assert.equal(resolveSlotCount({ env: {}, cpus: () => new Array(2).fill({}) }), 1);
  assert.equal(resolveSlotCount({ env: { HEAVY_SLOTS: "3" }, cpus: () => [] }), 3);
  assert.throws(() => resolveSlotCount({ slots: "0" }), /целое ≥ 1/);
  assert.throws(() => resolveSlotCount({ env: { HEAVY_SLOTS: "два" } }), /целое ≥ 1/);
});

test("isCi: только заданное значение, отличное от 0/false", async () => {
  const { isCi } = await load();
  assert.equal(isCi({}), false);
  assert.equal(isCi({ CI: "" }), false);
  assert.equal(isCi({ CI: "0" }), false);
  assert.equal(isCi({ CI: "false" }), false);
  assert.equal(isCi({ CI: "true" }), true);
  assert.equal(isCi({ CI: "1" }), true);
});

test("parseHeavyArgs: флаги, «=» и команда после --", async () => {
  const { parseHeavyArgs } = await load();
  const parsed = parseHeavyArgs([
    "--slots", "2", "--pool", "e2e", "--timeout=300", "--on-timeout", "run",
    "--log", "waits.jsonl", "--no-skip-ci", "--", "npm", "run", "--silent", "gate",
  ]);
  assert.equal(parsed.slots, "2");
  assert.equal(parsed.pool, "e2e");
  assert.equal(parsed.timeoutSeconds, "300");
  assert.equal(parsed.onTimeout, "run");
  assert.equal(parsed.logFile, "waits.jsonl");
  assert.equal(parsed.skipCi, false);
  assert.deepEqual(parsed.command, ["npm", "run", "--silent", "gate"]);

  assert.throws(() => parseHeavyArgs(["--bogus", "x"]), /неизвестный флаг/);
  assert.throws(() => parseHeavyArgs(["--slots"]), /нужно значение/);
});

test("resolveHeavyConfig: пул, каталог и проверка значений", async () => {
  const { resolveHeavyConfig, defaultPoolDir } = await load();
  const config = resolveHeavyConfig({}, { HEAVY_POOL: "e2e", HEAVY_SLOTS: "3" });
  assert.equal(config.pool, "e2e");
  assert.equal(config.slots, 3);
  assert.equal(config.dir, defaultPoolDir("e2e", { HEAVY_POOL: "e2e", HEAVY_SLOTS: "3" }));
  assert.equal(config.onTimeout, "fail");
  assert.equal(config.timeoutSeconds, null);

  assert.throws(() => resolveHeavyConfig({ onTimeout: "жди" }, {}), /fail или run/);
  assert.throws(() => resolveHeavyConfig({ timeoutSeconds: "1.5" }, {}), /целое число секунд/);
  assert.throws(() => resolveHeavyConfig({ pool: "плохой пул" }, {}), /буквы, цифры/);
});

test("слоты: занимаются по одному, мёртвый держатель снимается", async () => {
  const { tryAcquireSlot, releaseSlot, describeHolders } = await load();
  const dir = tempDir();
  const first = tryAcquireSlot(dir, 2, { pid: process.pid, repo: "a" });
  const second = tryAcquireSlot(dir, 2, { pid: process.pid, repo: "b" });
  assert.equal(first.index, 0);
  assert.equal(second.index, 1);
  assert.equal(tryAcquireSlot(dir, 2, { pid: process.pid, repo: "c" }), null);
  assert.equal(describeHolders(dir, 2, { alive: () => true }).length, 2);

  releaseSlot(first);
  assert.equal(tryAcquireSlot(dir, 2, { pid: process.pid })?.index, 0);

  // Мёртвый держатель: слот отдаётся, onReclaim называет его (по нему убирают мусор).
  const dir2 = tempDir();
  occupy(dir2, 0, { pid: 424242, at: Date.now(), repo: "брошенный" });
  const reclaimed = [];
  const slot = tryAcquireSlot(dir2, 1, { pid: process.pid }, {
    alive: () => false,
    onReclaim: (holder) => reclaimed.push(holder),
  });
  assert.equal(slot?.index, 0);
  assert.equal(reclaimed[0].repo, "брошенный");
});

test("tryAcquireSlot: без pid пишет свой pid — иначе живой слот сочли бы мёртвым", async () => {
  const { tryAcquireSlot, slotFile } = await load();
  const dir = tempDir();
  const slot = tryAcquireSlot(dir, 1, { repo: "без pid" });
  assert.equal(slot.pid, process.pid);
  assert.equal(JSON.parse(fs.readFileSync(slotFile(dir, 0), "utf8")).pid, process.pid);
});

test("acquireSlot: число слотов проверяется — иначе ожидание станет бесконечным", async () => {
  const { acquireSlot } = await load();
  await assert.rejects(acquireSlot({ dir: tempDir(), max: 0 }), /целое ≥ 1/);
  await assert.rejects(acquireSlot({ dir: tempDir(), max: undefined }), /целое ≥ 1/);
});

test("releaseSlot не сносит слот, уже занятый соседом", async () => {
  const { tryAcquireSlot, releaseSlot, slotFile } = await load();
  const dir = tempDir();
  const mine = tryAcquireSlot(dir, 1, { pid: 111, repo: "a" }, { alive: () => true });
  fs.writeFileSync(slotFile(dir, 0), JSON.stringify({ pid: 222, repo: "b", at: Date.now() }));
  releaseSlot(mine);
  assert.equal(JSON.parse(fs.readFileSync(slotFile(dir, 0), "utf8")).pid, 222);
});

test("acquireSlot: свободный слот молчит, занятый — называет держателя", async () => {
  const { acquireSlot, releaseSlot } = await load();
  const dir = tempDir();
  const log = [];
  const slot = await acquireSlot({
    dir, max: 1, payload: { pid: process.pid }, log: (line) => log.push(line),
  });
  assert.equal(slot.index, 0);
  assert.deepEqual(log, []);
  releaseSlot(slot);

  occupy(dir, 0, { pid: process.pid, at: Date.now(), repo: "чужой" });
  await assert.rejects(
    acquireSlot({
      dir, max: 1, payload: { pid: process.pid },
      waitTimeoutMs: 25, pollMs: 5, log: (line) => log.push(line),
    }),
    /не дождался слота/,
  );
  assert.match(log.join("\n"), /чужой/);
});

test("acquireSlot: живой держатель старше порога не отбирается, предупреждение одно (#375)", async () => {
  const { acquireSlot } = await load();
  const dir = tempDir();
  occupy(dir, 0, { pid: process.pid, at: Date.now() - 10 * 60_000, repo: "долгий" });
  const lines = [];
  await assert.rejects(
    acquireSlot({
      dir, max: 1, payload: { pid: 424242, repo: "ждущий" },
      staleMs: 5 * 60_000, waitTimeoutMs: 25, pollMs: 5,
      log: (line) => lines.push(line),
    }),
    /не дождался слота/,
  );
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, "slot-0.json"), "utf8")).repo, "долгий");
  assert.equal(lines.filter((line) => line.includes("держатель жив")).length, 1);
});

test("runHeavy: в CI и при вложенном вызове очередь не берётся и не логируется", async () => {
  const { runHeavy } = await load();
  const dir = tempDir();
  const logFile = path.join(dir, "waits.jsonl");

  const ciSpawn = fakeSpawn({ exit: 0 });
  const ciExit = await runHeavy(["--dir", dir, "--log", logFile, "--", "npm", "run", "gate"], {
    env: { CI: "true" }, spawnFn: ciSpawn, log: () => {}, error: () => {},
  });
  assert.equal(ciExit, 0);
  assert.equal(ciSpawn.calls.length, 1);
  assert.equal(fs.existsSync(logFile), false);

  const nestedSpawn = fakeSpawn({ exit: 0 });
  const nestedExit = await runHeavy(["--dir", dir, "--", "npm", "run", "gate"], {
    env: { HEAVY_HELD: "default" }, spawnFn: nestedSpawn, log: () => {}, error: () => {},
  });
  assert.equal(nestedExit, 0);
  assert.equal(nestedSpawn.calls.length, 1);
});

test("runHeavy: берёт слот, отдаёт HEAVY_HELD/HEAVY_SLOT и пишет JSON-лог", async () => {
  const { runHeavy } = await load();
  const dir = tempDir();
  const logFile = path.join(dir, "waits.jsonl");
  const spawnFn = fakeSpawn({ exit: 0 });

  const exit = await runHeavy(
    ["--dir", dir, "--slots", "1", "--log", logFile, "--", "npm", "run", "test:pytest"],
    { env: {}, spawnFn, log: () => {}, error: () => {} },
  );
  assert.equal(exit, 0);
  const [call] = spawnFn.calls;
  assert.equal(call.command, "npm run test:pytest");
  assert.equal(call.options.env.HEAVY_HELD, "default");
  assert.equal(call.options.env.HEAVY_SLOT, "0");
  assert.equal(call.options.shell, true);

  const record = JSON.parse(fs.readFileSync(logFile, "utf8").trim());
  assert.equal(record.pool, "default");
  assert.equal(record.slot, 0);
  assert.equal(record.exit, 0);
  assert.equal(record.timed_out, false);
  assert.equal(typeof record.waited_ms, "number");
  assert.equal(typeof record.ran_ms, "number");
});

test("runHeavy: --on-timeout fail отдаёт 75 и команду не запускает", async () => {
  const { runHeavy } = await load();
  const dir = tempDir();
  occupy(dir, 0, { pid: process.pid, at: Date.now(), command: "npm run gate" });
  const logFile = path.join(dir, "waits.jsonl");
  const spawnFn = fakeSpawn({ exit: 0 });
  const errors = [];

  const exit = await runHeavy(
    ["--dir", dir, "--slots", "1", "--timeout", "1", "--log", logFile, "--", "npm", "run", "gate"],
    { env: {}, spawnFn, log: () => {}, error: (line) => errors.push(line), pollMs: 10 },
  );
  assert.equal(exit, 75);
  assert.equal(spawnFn.calls.length, 0);
  assert.match(errors.join("\n"), /gave up waiting/);
  const record = JSON.parse(fs.readFileSync(logFile, "utf8").trim());
  assert.equal(record.timed_out, true);
  assert.equal(record.slot, null);
  assert.equal(record.ran_ms, null);
});

test("runHeavy: --on-timeout run запускает без слота", async () => {
  const { runHeavy } = await load();
  const dir = tempDir();
  occupy(dir, 0, { pid: process.pid, at: Date.now(), command: "npm run gate" });
  const logFile = path.join(dir, "waits.jsonl");
  const spawnFn = fakeSpawn({ exit: 3 });

  const exit = await runHeavy(
    [
      "--dir", dir, "--slots", "1", "--timeout", "1", "--on-timeout", "run",
      "--log", logFile, "--", "npm", "run", "gate:fast",
    ],
    { env: {}, spawnFn, log: () => {}, error: () => {}, pollMs: 10 },
  );
  assert.equal(exit, 3);
  assert.equal(spawnFn.calls.length, 1);
  assert.equal(spawnFn.calls[0].options.env.HEAVY_SLOT, undefined);
  const record = JSON.parse(fs.readFileSync(logFile, "utf8").trim());
  assert.equal(record.timed_out, true);
  assert.equal(record.slot, null);
  assert.equal(record.exit, 3);
});

test("runHeavy: --status называет держателей и свободные слоты", async () => {
  const { runHeavy } = await load();
  const dir = tempDir();
  occupy(dir, 0, { pid: process.pid, at: Date.now(), command: "npm run test:pytest" });
  const lines = [];
  const exit = await runHeavy(["--dir", dir, "--slots", "2", "--status"], {
    env: {}, log: (line) => lines.push(line), error: () => {},
  });
  assert.equal(exit, 0);
  assert.match(lines.join("\n"), /test:pytest/);
  assert.match(lines.join("\n"), /свободно 1\/2/);
});

test("runHeavy: без команды — код 2, с --help — справка", async () => {
  const { runHeavy } = await load();
  const errors = [];
  assert.equal(await runHeavy([], { env: {}, error: (line) => errors.push(line) }), 2);
  assert.match(errors.join("\n"), /нет команды/);
  const lines = [];
  assert.equal(await runHeavy(["--help"], { env: {}, log: (line) => lines.push(line) }), 0);
  assert.match(lines.join("\n"), /--on-timeout/);
});

test("buildCommand: кавычки по платформе", async () => {
  const { buildCommand } = await load();
  assert.equal(buildCommand(["npm", "run", "gate"], "linux"), "npm run gate");
  assert.equal(buildCommand(["node", "a b.js"], "linux"), "node 'a b.js'");
  assert.equal(buildCommand(["node", "a b.js"], "win32"), 'node "a b.js"');
  // Глоб — один аргумент на обеих платформах: иначе POSIX-шелл раскрыл бы
  // его сам, а Windows передал бы шаблон как есть.
  assert.equal(
    buildCommand(["node", "--test", "scripts/**/*.test.js"], "linux"),
    "node --test 'scripts/**/*.test.js'",
  );
  assert.equal(
    buildCommand(["node", "--test", "scripts/**/*.test.js"], "win32"),
    'node --test "scripts/**/*.test.js"',
  );
});
