"use strict";
// Запуск python-скрипта проекта интерпретатором из `backend/.venv` (T-384).
//
// Нужен там, где python зовут из npm-скрипта: подстановка в `scripts/gate.mjs`
// видит только команду шага, а `npm run gen:labels:check` запускает python уже
// внутри себя, и первым в PATH оказывается чужой интерпретатор.
//
//   node scripts/run-python.js scripts/check-test-imports.py
//   node scripts/run-python.js --cwd=backend scripts/generate_frontend_labels.py --check
//
// Код возврата — код python: обёртка не переводит отказ в «ok».

const { spawn } = require("node:child_process");
const { dirname, resolve } = require("node:path");
const { resolvePython } = require("./python-core.js");

const ROOT = dirname(__dirname);
const PYTHON = resolvePython({ root: ROOT });

const argv = process.argv.slice(2);
let cwd = ROOT;
const cwdArg = argv.find((arg) => arg.startsWith("--cwd="));
if (cwdArg) {
  cwd = resolve(ROOT, cwdArg.slice("--cwd=".length));
  argv.splice(argv.indexOf(cwdArg), 1);
}

if (!argv.length) {
  process.stderr.write("run-python: нечего запускать — передайте скрипт и его аргументы\n");
  process.exit(2);
}

const child = spawn(PYTHON.exe, argv, { cwd, stdio: "inherit", windowsHide: true });

child.on("error", (error) => {
  process.stderr.write(`run-python: не удалось запустить ${PYTHON.exe}: ${error.message}\n`);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code === null ? 1 : code);
});
