/**
 * heavy — машинный счётный семафор для тяжёлых команд.
 *
 * Контракт повторяет mokevnin/heavy (README), но реализация на Node: бинарь
 * heavy собирается только под macOS/Linux, а dev-машина проекта — Windows
 * (`mise install` падает с «No matching asset found for platform windows-x64»).
 * Поэтому «heavy» здесь — это наш скрипт с тем же поведением, доступный всем,
 * у кого есть node (он и так нужен всем задачам репозитория).
 *
 * Что взято у heavy:
 *  * N слотов на машину, общие для всех worktree и агентов: слот — файл в
 *    каталоге вне репозитория, занимается атомарно (`wx`);
 *  * ждать молча, если слот свободен, и один раз сказать, кто держит слоты,
 *    если все заняты;
 *  * `--timeout` + `--on-timeout fail|run`: занятая машина замедляет прогон,
 *    но хук не валит;
 *  * вложенность через `HEAVY_HELD`: `gate` → `test:pytest` не дедлочится;
 *  * `CI` пропускает очередь: машина CI своя;
 *  * JSON-лог каждого ожидания, чтобы подбирать число слотов по данным;
 *  * пулы: `e2e` и `default` не делят слоты.
 *
 * Что взято из нашего `run-slots.mjs` (#281, #306, #375) — там это строже, чем
 * у heavy:
 *  * слот мёртвого держателя снимается, живого — нет, каким бы старым он ни
 *    был (возраст лишь называется в логе);
 *  * `releaseSlot` сверяет pid: прежний держатель не сносит слот, который уже
 *    отдан соседу;
 *  * `onReclaim` — единственный момент, когда известно, чей прогон оставил
 *    мусор (клоны БД), поэтому уборка живёт здесь.
 *
 * Каталог слотов по умолчанию: `%LOCALAPPDATA%\ktm2000-heavy\<pool>` (Windows)
 * или `$XDG_STATE_HOME/ktm2000-heavy/<pool>` (иначе). Переопределяется
 * `HEAVY_DIR`.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const DEFAULT_POOL = "default";
export const DEFAULT_POLL_MS = 250;
/** Код выхода heavy при отказе ждать дальше (как у heavy). */
export const TIMEOUT_EXIT = 75;

/**
 * @typedef {Record<string, unknown>} SlotHolder
 * @typedef {{ index: number, file: string, pid: number }} Slot
 * @typedef {{ index: number, holder: SlotHolder, alive: boolean, ageMs: number }} HolderInfo
 */

/** Целое ≥ 1 из строки/числа — общая проверка флагов и переменных окружения. */
export function resolvePositiveInt(raw, label) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${label}=${raw} — нужно целое ≥ 1`);
  }
  return value;
}

/**
 * Сколько слотов по умолчанию: четверть ядер, минимум один.
 * `HEAVY_SLOTS` переопределяет, но не отменяет проверку «целое ≥ 1».
 */
export function resolveSlotCount({ slots, env = process.env, cpus = os.cpus } = {}) {
  const raw = slots ?? env.HEAVY_SLOTS ?? Math.max(1, Math.floor(cpus().length / 4));
  return resolvePositiveInt(raw, "HEAVY_SLOTS");
}

/** База состояния машинных семафоров: вне репозитория, поэтому видна всем worktree. */
export function defaultStateBase(env = process.env, platform = process.platform) {
  return platform === "win32"
    ? env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local")
    : env.XDG_STATE_HOME ?? path.join(os.homedir(), ".local", "state");
}

/** Каталог слотов пула: вне репозитория, поэтому виден всем worktree. */
export function defaultPoolDir(pool = DEFAULT_POOL, env = process.env, platform = process.platform) {
  return path.join(defaultStateBase(env, platform), "ktm2000-heavy", pool);
}

export function slotFile(dir, index) {
  return path.join(dir, `slot-${index}.json`);
}

/** Чем называть держателя в строке ожидания и в `--status`. */
export function holderLabel(holder) {
  return holder?.repo ?? holder?.command ?? "?";
}

/** Живой ли процесс. Неизвестная ошибка → «жив»: слот не отнимаем. */
export function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code !== "ESRCH";
  }
}

export function readHolder(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** Длительность для сообщений: секунды до минуты, дальше — минуты. */
export function formatDuration(ms) {
  return ms < 60_000 ? `${Math.round(ms / 1000)} с` : `${Math.round(ms / 60_000)} мин`;
}

/**
 * Занять свободный слот или вернуть null, если все заняты.
 *
 * `onReclaim(holder, info)` зовётся для каждого слота, чей держатель **мёртв**,
 * непосредственно перед удалением файла слота: это единственный момент, когда
 * известно, чей прогон оставил мусор (#306).
 *
 * @param {string} dir
 * @param {number} max
 * @param {SlotHolder} [payload]
 * @param {{alive?: (pid: number) => boolean, onReclaim?: (holder: SlotHolder, info: {index: number, reason: string}) => void}} [options]
 * @returns {Slot | null}
 */
export function tryAcquireSlot(dir, max, payload, { alive = isProcessAlive, onReclaim } = {}) {
  fs.mkdirSync(dir, { recursive: true });
  for (let index = 0; index < max; index += 1) {
    const file = slotFile(dir, index);
    const holder = readHolder(file);
    if (holder && !alive(holder.pid)) {
      onReclaim?.(holder, { index, reason: "держатель мёртв" });
      fs.rmSync(file, { force: true });
    }
    try {
      // `pid` обязателен в файле слота: без него сосед считает держателя
      // мёртвым и отбирает слот у живого процесса. Если вызывающий не передал
      // свой pid — пишем pid этого процесса.
      const owner = payload?.pid ?? process.pid;
      fs.writeFileSync(file, JSON.stringify({ at: Date.now(), ...payload, pid: owner }), { flag: "wx" });
      return { index, file, pid: owner };
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
    }
  }
  return null;
}

/**
 * Отпускает слот **только если он всё ещё наш**: файл слота бывает чужим к
 * моменту `finally` (мёртвого держателя сняли, сосед занял тот же индекс), и
 * снос такого файла перестал бы считать семафор (#306, R-04).
 */
export function releaseSlot(slot) {
  if (!slot?.file) return;
  const holder = readHolder(slot.file);
  if (holder && holder.pid !== slot.pid) return;
  fs.rmSync(slot.file, { force: true });
}

/**
 * Кто держит слоты — для строки ожидания. `ageMs` — сколько висит этот слот.
 *
 * @param {string} dir
 * @param {number} max
 * @param {{alive?: (pid: number) => boolean, now?: () => number}} [options]
 * @returns {HolderInfo[]}
 */
export function describeHolders(dir, max, { alive = isProcessAlive, now = Date.now } = {}) {
  const holders = [];
  for (let index = 0; index < max; index += 1) {
    const holder = readHolder(slotFile(dir, index));
    if (holder) {
      holders.push({
        index,
        holder,
        alive: alive(holder.pid),
        ageMs: now() - (holder.at ?? now()),
      });
    }
  }
  return holders;
}

export class SlotTimeoutError extends Error {
  constructor(message, { waitedMs, holders } = {}) {
    super(message);
    this.name = "SlotTimeoutError";
    this.waitedMs = waitedMs;
    this.holders = holders;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Ждать свободный слот, показывая, что занято.
 *
 * @param {object} [options]
 * @param {string} options.dir каталог слотов пула
 * @param {number} options.max число слотов
 * @param {SlotHolder} [options.payload] что записать в файл слота
 * @param {number} [options.waitTimeoutMs] сколько ждать (`Infinity` — сколько нужно)
 * @param {number} [options.staleMs] возраст, с которого живой держатель
 *   называется в логе как подозреваемый; слот по нему НЕ освобождается (#375)
 * @param {number} [options.pollMs] шаг опроса
 * @param {(line: string) => void} [options.log]
 * @param {(holder: SlotHolder, info: {index: number, reason: string}) => void} [options.onReclaim]
 * @param {(pid: number) => boolean} [options.alive]
 * @param {() => number} [options.now]
 * @param {(holder: SlotHolder) => string} [options.label] чем называть держателя
 */
export async function acquireSlot({
  dir,
  max,
  payload = {},
  waitTimeoutMs = Infinity,
  staleMs = Infinity,
  pollMs = DEFAULT_POLL_MS,
  log = () => {},
  onReclaim,
  alive = isProcessAlive,
  now = Date.now,
  label = holderLabel,
} = {}) {
  if (!Number.isInteger(max) || max < 1) {
    throw new Error(`max=${max} — нужно целое ≥ 1 (число слотов пула)`);
  }
  const started = now();
  let announced = false;
  let warned = false;
  for (;;) {
    // Мёртвого держателя снимает и `onReclaim` зовёт только `tryAcquireSlot`:
    // второй такой цикл здесь разошёлся бы с ним в том, когда слот считается
    // свободным.
    const slot = tryAcquireSlot(dir, max, payload, {
      alive,
      onReclaim: (holder, info) => {
        log(`слот ${info.index}: держатель (pid ${holder.pid ?? "?"}) мёртв — снимаю`);
        onReclaim?.(holder, info);
      },
    });
    if (slot) {
      if (announced) log(`получил слот ${slot.index} через ${formatDuration(now() - started)}`);
      return slot;
    }

    const waited = now() - started;
    const needHolders = !announced || staleMs !== Infinity || waited > waitTimeoutMs;
    const holders = needHolders ? describeHolders(dir, max, { alive, now }) : [];
    const stale = holders.find((info) => info.alive && info.ageMs > staleMs);
    if (stale && !warned) {
      // Держатель жив: слот НЕ отнимаем. Возраст — не право отбора, а вопрос
      // человеку: долгий прогон и зависший выглядят одинаково (#375).
      warned = true;
      log(
        `слот ${stale.index}: держатель жив (pid ${stale.holder.pid ?? "?"}, ` +
          `${formatDuration(stale.ageMs)}, ${label(stale.holder)}) — слот не отнимаю; ` +
          `порог подозрения ${formatDuration(staleMs)}`,
      );
    }
    if (!announced) {
      const busy = holders
        .map(
          ({ index, holder, ageMs }) =>
            `слот ${index}: ${label(holder)} (pid ${holder.pid ?? "?"}, ${formatDuration(ageMs)})`,
        )
        .join(", ");
      log(`жду слот: занято ${max}/${max} — ${busy}`);
      announced = true;
    }
    if (waited > waitTimeoutMs) {
      const held = holders
        .map(
          ({ index, holder, ageMs, alive: isAlive }) =>
            `слот ${index}: ${label(holder)} (pid ${holder.pid ?? "?"}, ` +
            `${isAlive ? "жив" : "мёртв"}, ${formatDuration(ageMs)})`,
        )
        .join("; ");
      throw new SlotTimeoutError(
        `не дождался слота семафора за ${formatDuration(waited)} (слотов ${max}); держат: ${held || "—"}. ` +
          "Живой держатель слота не уступает по возрасту — если прогон завис, решать надо по pid",
        { waitedMs: waited, holders },
      );
    }
    // Джиттер: одновременные претенденты не бьются в один и тот же момент.
    await sleep(pollMs * (0.75 + Math.random() * 0.5));
  }
}

/** `CI` пустым значением — это «локальная машина», а не CI (`CI=''`). */
export function isCi(env = process.env) {
  const value = env.CI;
  return value !== undefined && value !== "" && value !== "0" && value !== "false";
}

const HEAVY_FLAGS_WITH_VALUE = new Set(["--slots", "--dir", "--pool", "--timeout", "--on-timeout", "--log"]);

/** Разбор аргументов CLI. Команда идёт после `--` и не разбирается. */
export function parseHeavyArgs(argv) {
  const opts = {
    slots: null,
    dir: null,
    pool: null,
    timeoutSeconds: null,
    onTimeout: null,
    logFile: null,
    skipCi: true,
    status: false,
    help: false,
    command: [],
  };
  let index = 0;
  for (; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--") {
      index += 1;
      break;
    }
    if (arg === "--status") opts.status = true;
    else if (arg === "--help" || arg === "-h") opts.help = true;
    else if (arg === "--no-skip-ci") opts.skipCi = false;
    else if (HEAVY_FLAGS_WITH_VALUE.has(arg)) {
      const value = argv[index + 1];
      if (value === undefined) throw new Error(`${arg}: нужно значение`);
      index += 1;
      assignOption(opts, arg, value);
    } else if (arg.startsWith("--") && arg.includes("=")) {
      const eq = arg.indexOf("=");
      assignOption(opts, arg.slice(0, eq), arg.slice(eq + 1));
    } else if (arg.startsWith("-")) {
      throw new Error(`неизвестный флаг: ${arg}`);
    } else {
      break;
    }
  }
  opts.command = argv.slice(index);
  return opts;
}

function assignOption(opts, flag, value) {
  switch (flag) {
    case "--slots":
      opts.slots = value;
      break;
    case "--dir":
      opts.dir = value;
      break;
    case "--pool":
      opts.pool = value;
      break;
    case "--timeout":
      opts.timeoutSeconds = value;
      break;
    case "--on-timeout":
      opts.onTimeout = value;
      break;
    case "--log":
      opts.logFile = value;
      break;
    default:
      throw new Error(`неизвестный флаг: ${flag}`);
  }
}

/** Свести аргументы и окружение в один конфиг с проверкой значений. */
export function resolveHeavyConfig(opts, env = process.env) {
  const pool = opts.pool ?? env.HEAVY_POOL ?? DEFAULT_POOL;
  if (!/^[a-z0-9][a-z0-9_-]*$/i.test(pool)) {
    throw new Error(`пул «${pool}»: буквы, цифры, «-» и «_»`);
  }
  const slots = resolveSlotCount({ slots: opts.slots, env });
  const dir = opts.dir ?? env.HEAVY_DIR ?? defaultPoolDir(pool, env);
  const onTimeout = opts.onTimeout ?? env.HEAVY_ON_TIMEOUT ?? "fail";
  if (onTimeout !== "fail" && onTimeout !== "run") {
    throw new Error(`--on-timeout=${onTimeout}: допустимо fail или run`);
  }
  const timeoutRaw = opts.timeoutSeconds ?? env.HEAVY_TIMEOUT ?? null;
  let timeoutSeconds = null;
  if (timeoutRaw !== null && timeoutRaw !== "") {
    timeoutSeconds = Number(timeoutRaw);
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 0) {
      throw new Error(`--timeout=${timeoutRaw}: нужно целое число секунд ≥ 0`);
    }
  }
  return {
    pool,
    slots,
    dir,
    onTimeout,
    timeoutSeconds,
    logFile: opts.logFile ?? env.HEAVY_LOG ?? null,
    skipCi: opts.skipCi,
  };
}

/** Собрать строку команды: на Windows нужен shell, а аргументы — в кавычках. */
export function buildCommand(argv, platform = process.platform) {
  return argv.map((arg) => quoteArg(arg, platform)).join(" ");
}

function quoteArg(arg, platform) {
  if (arg === "") return '""';
  if (platform === "win32") {
    // Глобы тоже в кавычках: `cmd` их не раскрывает, а `node --test` ждёт
    // шаблон строкой. Иначе один аргумент понят по-разному на двух платформах.
    return /[\s"&|<>^*?[\]]/.test(arg) ? `"${arg.replace(/"/g, '\\"')}"` : arg;
  }
  return /[^\w@%+=:,./-]/.test(arg) ? `'${arg.replace(/'/g, `'\\''`)}'` : arg;
}

function signalExitCode(signal) {
  const number = os.constants.signals[signal];
  return typeof number === "number" ? 128 + number : 1;
}

function runChild(command, { cwd, env, spawnFn }) {
  return new Promise((resolve, reject) => {
    const child = spawnFn(command, { cwd, env, stdio: "inherit", shell: true });
    const forwarded = [];
    for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
      const handler = () => child.kill(signal);
      try {
        process.on(signal, handler);
        forwarded.push([signal, handler]);
      } catch {
        // Платформа без сигнала (Windows: SIGHUP нет) — просто не пересылаем.
      }
    }
    const cleanup = () => {
      for (const [signal, handler] of forwarded) process.off(signal, handler);
    };
    child.on("error", (error) => {
      cleanup();
      reject(error);
    });
    child.on("exit", (code, signal) => {
      cleanup();
      resolve({ exit: code ?? (signal ? signalExitCode(signal) : 1) });
    });
  });
}

function appendRunLog(logFile, record) {
  if (!logFile) return;
  try {
    fs.mkdirSync(path.dirname(logFile), { recursive: true });
    fs.appendFileSync(logFile, `${JSON.stringify(record)}\n`);
  } catch {
    // Лог — для настройки числа слотов, а не условие прогона: не пишется — молчим.
  }
}

export const HEAVY_HELP = [
  "heavy — машинный счётный семафор для тяжёлых команд",
  "",
  "  node scripts/heavy.mjs [флаги] -- <команда…>",
  "  node scripts/heavy.mjs --status",
  "",
  "Флаги (и переменные окружения):",
  "  --slots N            число слотов (HEAVY_SLOTS), по умолчанию четверть ядер",
  "  --dir PATH           каталог слотов (HEAVY_DIR)",
  "  --pool NAME          пул (HEAVY_POOL), по умолчанию default",
  "  --timeout SECONDS    сколько ждать слот (HEAVY_TIMEOUT); без флага — сколько нужно",
  "  --on-timeout fail|run  не дождались: код 75 или запустить без слота (HEAVY_ON_TIMEOUT)",
  "  --log FILE           JSON-строка на каждое ожидание (HEAVY_LOG)",
  "  --no-skip-ci         не пропускать очередь в CI",
  "  --status             кто держит слоты пула",
  "",
  "Вложенный вызов того же пула (HEAVY_HELD) и CI (непустой, кроме 0/false) выполняются сразу.",
].join("\n");

/**
 * Выполнить команду под слотом. Возвращает код выхода, ничего не завершает —
 * так это можно проверить тестом.
 *
 * @param {string[]} argv
 * @param {object} [options]
 * @param {Record<string, string | undefined>} [options.env]
 * @param {string} [options.cwd]
 * @param {Function} [options.spawnFn]
 * @param {() => number} [options.now]
 * @param {(line: string) => void} [options.log]
 * @param {(line: string) => void} [options.error]
 * @param {number} [options.pollMs]
 */
export async function runHeavy(argv, {
  env = process.env,
  cwd = process.cwd(),
  spawnFn = spawn,
  now = Date.now,
  log = console.log,
  error = console.error,
  pollMs = DEFAULT_POLL_MS,
} = {}) {
  let opts;
  let config;
  try {
    opts = parseHeavyArgs(argv);
    if (opts.help) {
      log(HEAVY_HELP);
      return 0;
    }
    if (!opts.status && opts.command.length === 0) {
      error("heavy: нет команды — нужен `-- <команда…>`");
      return 2;
    }
    config = resolveHeavyConfig(opts, env);
  } catch (err) {
    error(`heavy: ${err.message}`);
    return 2;
  }

  if (opts.status) {
    log(`heavy: пул «${config.pool}», слотов ${config.slots} (${config.dir})`);
    const holders = describeHolders(config.dir, config.slots, { now });
    for (const { index, holder, alive, ageMs } of holders) {
      log(
        `heavy:   слот ${index}: ${
          alive
            ? `держит pid ${holder.pid ?? "?"} ${formatDuration(ageMs)}: ${holder.command ?? holder.repo ?? "?"}`
            : `держатель pid ${holder.pid ?? "?"} мёртв — слот свободен`
        }`,
      );
    }
    const busy = holders.filter((h) => h.alive).length;
    log(`heavy: свободно ${config.slots - busy}/${config.slots}`);
    return 0;
  }

  const command = buildCommand(opts.command);
  const record = {
    start: Math.floor(now() / 1000),
    pool: config.pool,
    command: opts.command.join(" "),
    cwd,
    slot: null,
    waited_ms: 0,
    ran_ms: null,
    timed_out: false,
    exit: null,
  };

  // CI и вложенный вызов того же пула очередь не берут — и не логируются.
  if ((config.skipCi && isCi(env)) || env.HEAVY_HELD === config.pool) {
    const { exit } = await runChild(command, { cwd, env, spawnFn });
    return exit;
  }

  const started = now();
  let slot = null;
  try {
    slot = await acquireSlot({
      dir: config.dir,
      max: config.slots,
      payload: { pid: process.pid, command: record.command, cwd },
      waitTimeoutMs:
        config.timeoutSeconds === null ? Infinity : config.timeoutSeconds * 1000,
      pollMs,
      log: (line) => log(`heavy: ${line}`),
    });
    record.waited_ms = now() - started;
  } catch (err) {
    if (!(err instanceof SlotTimeoutError)) throw err;
    record.waited_ms = now() - started;
    record.timed_out = true;
    if (config.onTimeout === "run") {
      error(
        `heavy: не дождался слота за ${formatDuration(record.waited_ms)}; ` +
          "запускаю без слота (--on-timeout run)",
      );
    } else {
      error(
        `heavy: gave up waiting for a slot after ${formatDuration(record.waited_ms)} ` +
          `(--timeout ${config.timeoutSeconds}); команда не запущена`,
      );
      appendRunLog(config.logFile, record);
      return TIMEOUT_EXIT;
    }
  }

  record.slot = slot?.index ?? null;
  const ranStarted = now();
  const childEnv = {
    ...env,
    HEAVY_HELD: config.pool,
    ...(slot ? { HEAVY_SLOT: String(slot.index) } : {}),
  };
  try {
    const { exit } = await runChild(command, { cwd, env: childEnv, spawnFn });
    record.ran_ms = now() - ranStarted;
    record.exit = exit;
    appendRunLog(config.logFile, record);
    return exit;
  } finally {
    if (slot) releaseSlot(slot);
  }
}
