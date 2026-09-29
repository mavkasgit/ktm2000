/**
 * Тесты логики живости PID из scripts/ensure-dev-ports.js.
 *
 * Запуск: npm run test:scripts (node --test, без внешних зависимостей).
 * Данные — строки снимка процессов в том же виде, в котором их отдаёт
 * `Get-CimInstance Win32_Process | ... | ConvertTo-Json -Compress`.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  parseProcessTable,
  orphanHeirs,
  isShellHost,
  isDockerProcess,
  expandDeadOwners,
} = require("./ensure-dev-ports-core");

/** Снимок процессов: умерший dev_server.py, переживший его uvicorn-worker, conhost. */
const SNAPSHOT_JSON = JSON.stringify([
  {
    ProcessId: 5000,
    ParentProcessId: 4,
    Name: "explorer.exe",
    CommandLine: "C:\\Windows\\explorer.exe",
  },
  {
    ProcessId: 10428,
    ParentProcessId: 5000,
    Name: "python.exe",
    CommandLine: "python   scripts/dev_server.py",
  },
  {
    ProcessId: 20000,
    ParentProcessId: 10428,
    Name: "python.exe",
    CommandLine: "python -m uvicorn app.main:app --workers 1",
  },
  {
    ProcessId: 20001,
    ParentProcessId: 20000,
    Name: "python.exe",
    CommandLine: "python -c from multiprocessing.spawn import spawn_main; spawn_main(...)",
  },
  {
    ProcessId: 20002,
    ParentProcessId: 10428,
    Name: "conhost.exe",
    CommandLine: "C:\\Windows\\System32\\conhost.exe",
  },
]);

test("parseProcessTable разбирает снимок процессов и схлопывает пробелы в cmd", () => {
  const table = parseProcessTable(SNAPSHOT_JSON);

  assert.equal(table.size, 5);
  assert.equal(table.get(10428).parent, 5000);
  assert.equal(table.get(10428).name, "python.exe");
  assert.equal(table.get(10428).cmd, "python scripts/dev_server.py");
  assert.equal(table.get(20002).name, "conhost.exe");
});

test("parseProcessTable переживает битый и одиночный вывод PowerShell", () => {
  assert.equal(parseProcessTable("").size, 0);
  assert.equal(parseProcessTable("Get-CimInstance : Access denied").size, 0);

  // Один процесс ConvertTo-Json отдаёт объектом, а не массивом.
  const single = parseProcessTable('{"ProcessId":7,"ParentProcessId":4,"Name":"cmd.exe"}');
  assert.equal(single.size, 1);
  assert.equal(single.get(7).name, "cmd.exe");
  assert.equal(single.get(7).parent, 4);
  // Отсутствующие поля не роняют разбор и не становятся NaN.
  assert.equal(single.get(7).cmd, "");
});

test("orphanHeirs находит живых потомков мёртвого PID, а не его самого", () => {
  const table = parseProcessTable(SNAPSHOT_JSON);

  const heirs = orphanHeirs(table, 10428).sort((a, b) => a - b);

  assert.deepEqual(heirs, [20000, 20001, 20002]);
  assert.ok(!heirs.includes(10428), "умерший владелец сокета не является своим же наследником");
  // Внук найден через цепочку «мёртвый -> ребёнок -> внук», а не только дети.
  assert.ok(heirs.includes(20001));
  // Поддерево собирается целиком: у 5000 (explorer) есть 10428, а у того — вся ветка.
  assert.deepEqual(orphanHeirs(table, 5000).sort((a, b) => a - b), [10428, 20000, 20001, 20002]);
  assert.deepEqual(orphanHeirs(table, 39344), [], "у vite нет потомков");
});

test("живой наследник умершего владельца сокета — реальный держатель порта", () => {
  const table = parseProcessTable(SNAPSHOT_JSON);
  // netstat показал PID 10428 на :8012, но в списке процессов его уже нет.
  const netstatRows = [
    {
      port: 8012,
      pid: 10428,
      name: "(system)",
      cmd: "",
      isDocker: false,
      alive: false,
      heirs: [],
    },
  ];

  const rows = expandDeadOwners(netstatRows, table);

  const worker = rows.filter((row) => row.pid === 20000);
  assert.equal(worker.length, 1, "переживший uvicorn-worker добавляется ровно один раз");
  assert.equal(worker[0].port, 8012);
  assert.equal(worker[0].name, "python.exe");
  assert.equal(worker[0].alive, true, "наследник жив — его можно убить и освободить порт");
  assert.equal(worker[0].isDocker, false);
  // Внук наследника тоже унаследовал сокет.
  assert.ok(rows.some((row) => row.pid === 20001 && row.alive));

  // Мёртвый владелец остаётся мёртвым и лишь перечисляет наследников в отчёте.
  const dead = rows.find((row) => row.pid === 10428);
  assert.equal(dead.alive, false);
  assert.ok(dead.heirs.includes(20000));
});

test("хосты консолей не держат сокет и не попадают в кандидаты на kill", () => {
  assert.equal(isShellHost("conhost.exe"), true);
  assert.equal(isShellHost("OpenConsole.exe"), true);
  assert.equal(isShellHost("powershell.exe"), true);
  assert.equal(isShellHost("cmd.exe"), true);
  assert.equal(isShellHost("explorer.exe"), true);
  assert.equal(isShellHost("WindowsTerminal.exe"), true);
  assert.equal(isShellHost(""), false);
  // Реальный держатель не должен отсеиваться по подстроке.
  assert.equal(isShellHost("python.exe"), false);
  assert.equal(isShellHost("mycmd.exe"), false);
  assert.equal(isShellHost(undefined), false);

  // 20002 — conhost, ребёнок мёртвого 10428: в отчёт и в кандидаты на kill он
  // не попадает (это чужое окно терминала), а живой python-наследник попадает.
  const table = parseProcessTable(SNAPSHOT_JSON);
  const rows = expandDeadOwners(
    [
      { port: 8012, pid: 10428, name: "(system)", cmd: "", isDocker: false, alive: false, heirs: [] },
    ],
    table,
  );

  assert.ok(!rows.some((row) => row.pid === 20002), "conhost не считается держателем сокета");
  assert.ok(!rows.find((row) => row.pid === 10428).heirs.includes(20002));
  assert.ok(rows.some((row) => row.pid === 20000));
});

test("живой владелец сокета не разворачивается в потомков", () => {
  const table = parseProcessTable(SNAPSHOT_JSON);
  const rows = expandDeadOwners(
    [
      { port: 8012, pid: 20000, name: "python.exe", cmd: "uvicorn", isDocker: false, alive: true, heirs: [] },
    ],
    table,
  );

  assert.deepEqual(
    rows.map((row) => row.pid),
    [20000],
  );
  assert.deepEqual(rows[0].heirs, []);
});

test("наследник, уже занявший порт, не дублируется в отчёте", () => {
  const table = parseProcessTable(SNAPSHOT_JSON);
  const rows = expandDeadOwners(
    [
      { port: 8012, pid: 10428, name: "(system)", cmd: "", isDocker: false, alive: false, heirs: [] },
      { port: 8012, pid: 20001, name: "python.exe", cmd: "spawn_main", isDocker: false, alive: true, heirs: [] },
    ],
    table,
  );

  assert.equal(rows.filter((row) => row.pid === 20001).length, 1);
  // Владелец-внук остаётся единственным источником истины для этого порта.
  assert.ok(!rows.find((row) => row.pid === 10428).heirs.includes(20001));
});

test("Docker-процессы помечаются как защищённые от kill", () => {
  assert.equal(isDockerProcess({ name: "com.docker.backend.exe", cmd: "" }), true);
  assert.equal(isDockerProcess({ name: "python.exe", cmd: "python -m uvicorn" }), false);
});
