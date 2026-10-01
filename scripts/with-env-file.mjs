#!/usr/bin/env node
/**
 * Запуск команды с переменными окружения из env-файла приложения.
 *
 * Нужен там, где команда сама читает DSN из файла, а указать ему файл
 * переменной окружением нечем: alembic и сиды берут `$ENV_FILE`
 * (`backend/app/core/env_file.py`), и без него уходят на общую dev-БД.
 * Поэтому обёртка экспортирует и `ENV_FILE`, и значения файла.
 *
 * Переменная из process.env важнее значения в файле: прогон против своего
 * стенда переопределяет пути и порты снаружи.
 *
 *   node scripts/with-env-file.mjs [--env-file <path>] [--cwd <dir>] -- <команда> [аргументы...]
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Путь к env-файлу переопределяется `E2E_ENV_FILE`: у каждого worktree клона
// своя БД стенда, иначе параллельные прогоны стирают данные друг друга.
const DEFAULT_ENV_FILE = resolve(REPO_ROOT, process.env.E2E_ENV_FILE ?? ".env.e2e");

const OPTION_KEYS = { "--env-file": "envFile", "--cwd": "cwd" };

function parseArgs(argv) {
  const options = { envFile: DEFAULT_ENV_FILE, cwd: process.cwd() };
  let index = 0;
  while (index < argv.length && argv[index] in OPTION_KEYS) {
    options[OPTION_KEYS[argv[index]]] = resolve(REPO_ROOT, argv[index + 1]);
    index += 2;
  }
  if (argv[index] !== "--") {
    throw new Error(`Ожидался разделитель "--": node with-env-file.mjs [опции] -- <команда>`);
  }
  return { options, command: argv.slice(index + 1) };
}

function readEnvFile(file) {
  const values = {};
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (match && process.env[match[1]] === undefined) {
      values[match[1]] = match[2].replace(/^["']|["']$/g, "");
    }
  }
  return values;
}

const { options, command } = parseArgs(process.argv.slice(2));
if (command.length === 0) {
  throw new Error("Не указана команда после --");
}

const child = spawn(command[0], command.slice(1), {
  cwd: options.cwd,
  stdio: "inherit",
  env: { ...process.env, ...readEnvFile(options.envFile), ENV_FILE: options.envFile },
});

child.on("error", (error) => {
  console.error(`[with-env-file] не удалось запустить ${command[0]}: ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  process.exit(signal ? 1 : (code ?? 1));
});
