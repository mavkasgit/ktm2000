/**
 * Уборка после прогона E2E: только осиротевшие браузеры и проигрыватели
 * прогона. Подключён в `playwright.config.ts` как `globalTeardown`.
 *
 * Почему стек здесь не трогаем
 * ---------------------------
 * Стеком владеет Playwright (`webServer` в `playwright.config.ts`): он сам
 * стартует backend и frontend, сам ждёт готовности и сам убивает своё дерево
 * по завершении прогона.
 *
 * Раньше владение было ненастоящим: `global-setup.ts` поднимал `npm run dev`
 * через `spawn(..., { detached: true, shell: true })` и сразу его отпускал, а
 * teardown угадывал, чей это процесс, по регуляркам в command line. С uvicorn
 * --reload угадывание промахивалось: оставался `python scripts/dev_server.py`,
 * который держал :8012 в LISTENING уже с мёртвым воркером. Следующий прогон
 * видел занятый порт и падал на «Тест-стек недоступен» — то есть уборка
 * предыдущего прогона ломала следующий.
 *
 * Порты здесь тоже не трогаем: при `PW_REUSE_STACK=1` стек поднят оператором
 * и должен пережить прогон.
 *
 * Что остаётся за teardown
 * ------------------------
 * `chrome.exe` / `headless_shell.exe` / `ffmpeg*` от прерванного прогона: их
 * Playwright за собой не убирает, они висят и едят память. Режутся только
 * процессы, чей command line указывает на каталог этого репо или на
 * `test-results`/`playwright-report`, либо Playwright-браузер с умершим
 * родителем (`--user-data-dir=.../playwright_*_profile-*`). Браузеры чужого
 * параллельного прогона и обычный Chrome пользователя не трогаются.
 *
 * Teardown никогда не бросает исключение: иначе Playwright замаскирует
 * результат прогона (падение теста) ошибкой уборки.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(E2E_DIR, "..");
const REPO_ROOT = path.resolve(E2E_DIR, "..", "..");
const REPO_ROOT_LC = REPO_ROOT.toLowerCase();

/**
 * Артефакты прогона: дефолтный `testDir`-овый `test-results` и папка html-отчёта
 * из `reporter` в `playwright.config.ts`. Пути в command line ffmpeg/chrome
 * позволяют опознать процесс именно этого прогона.
 */
const RUN_OUTPUT_DIRS_LC = [
  path.join(FRONTEND_DIR, "test-results"),
  path.join(FRONTEND_DIR, "playwright-report"),
].map((dir) => dir.toLowerCase());

const IS_WIN = process.platform === "win32";
const SELF_PID = process.pid;

function log(message: string): void {
  console.log(`[e2e:teardown] ${message}`);
}

interface ProcInfo {
  pid: number;
  ppid: number;
  name: string;
  cmd: string;
}

/* ------------------------------------------------------------------ */
/* Снимок процессов                                                   */
/* ------------------------------------------------------------------ */

function normalizeProcess(raw: unknown): ProcInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const pid = Number(r.pid ?? r.ProcessId);
  if (!Number.isFinite(pid) || pid <= 0) return null;
  return {
    pid,
    ppid: Number(r.ppid ?? r.ParentProcessId) || 0,
    name: String(r.name ?? r.Name ?? ""),
    cmd: String(r.cmd ?? r.CommandLine ?? "").replace(/\s+/g, " ").trim(),
  };
}

function toArray<T>(value: unknown): T[] {
  if (value === null || value === undefined) return [];
  return Array.isArray(value) ? (value as T[]) : [value as T];
}

/** PowerShell: одна выборка — таблица процессов. */
function sampleWindows(): ProcInfo[] {
  const script = [
    "$ErrorActionPreference='SilentlyContinue'",
    "$procs = Get-CimInstance Win32_Process | ForEach-Object {",
    "  [pscustomobject]@{ pid = $_.ProcessId; ppid = $_.ParentProcessId; name = $_.Name; cmd = $_.CommandLine }",
    "}",
    "@($procs) | ConvertTo-Json -Depth 3 -Compress",
  ].join("; ");

  const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
    timeout: 60_000,
  });
  if (result.status !== 0 || !result.stdout) {
    log(`⚠ не удалось снять список процессов (код ${result.status}) — уборка пропущена`);
    return [];
  }
  const jsonStart = result.stdout.indexOf("[") >= 0 ? result.stdout.indexOf("[") : result.stdout.indexOf("{");
  if (jsonStart < 0) return [];
  const parsed = JSON.parse(result.stdout.slice(jsonStart)) as unknown;
  return toArray<unknown>(parsed)
    .map(normalizeProcess)
    .filter((p): p is ProcInfo => p !== null);
}

/** POSIX-эквивалент: `ps`. */
function samplePosix(): ProcInfo[] {
  const ps = spawnSync("ps", ["-eo", "pid=,ppid=,args="], { encoding: "utf8", timeout: 30_000 });
  const processes: ProcInfo[] = [];
  for (const line of (ps.stdout ?? "").split("\n")) {
    const match = line.match(/^\s*(\d+)\s+(\d+)\s+(.*)$/);
    if (!match) continue;
    const proc = normalizeProcess({ pid: match[1], ppid: match[2], cmd: match[3] });
    if (proc) processes.push(proc);
  }
  return processes;
}

function sampleProcesses(): ProcInfo[] {
  return IS_WIN ? sampleWindows() : samplePosix();
}

/* ------------------------------------------------------------------ */
/* Дерево процессов                                                   */
/* ------------------------------------------------------------------ */

/** Живые предки `pid` (снизу вверх), до первого несуществующего звена. */
function ancestorChain(table: Map<number, ProcInfo>, pid: number): number[] {
  const chain: number[] = [];
  let current = pid;
  for (let guard = 0; guard < 64; guard += 1) {
    const parent = table.get(current)?.ppid;
    if (!parent || parent === current || chain.includes(parent)) break;
    chain.push(parent);
    current = parent;
  }
  return chain;
}

function killTree(pid: number, why: string): boolean {
  if (IS_WIN) {
    const result = spawnSync("taskkill.exe", ["/F", "/T", "/PID", String(pid)], {
      encoding: "utf8",
      windowsHide: true,
      timeout: 60_000,
    });
    const ok = result.status === 0;
    log(ok ? `  ✓ PID ${pid} — ${why}` : `  ✗ PID ${pid} — ${why} (taskkill: ${result.status})`);
    return ok;
  }
  const signals: NodeJS.Signals[] = ["SIGTERM", "SIGKILL"];
  for (const signal of signals) {
    try {
      process.kill(-pid, signal);
      log(`  ✓ PID ${pid} — ${why} (${signal})`);
      return true;
    } catch {
      try {
        process.kill(pid, signal);
        log(`  ✓ PID ${pid} — ${why} (${signal})`);
        return true;
      } catch {
        /* try the next signal */
      }
    }
  }
  log(`  ✗ PID ${pid} — ${why} (не удалось убить)`);
  return false;
}

/* ------------------------------------------------------------------ */
/* Осиротевшие браузеры/проигрыватели прогона                        */
/* ------------------------------------------------------------------ */

/** Имена процессов, которые могли остаться от прогона (в нижнем регистре). */
const RUN_PROCESS_NAMES: Record<string, true> = {
  "chrome.exe": true,
  "chrome_crashpad_handler.exe": true,
  "headless_shell.exe": true,
  "ffmpeg.exe": true,
  "ffmpeg-win64.exe": true,
  "node": true,
  "node.exe": true,
};

/** Профиль, который создаёт только Playwright (`--user-data-dir`). */
const PLAYWRIGHT_PROFILE_RE = /playwright_[a-z0-9_-]*profile/i;

/**
 * Процесс, у которого живой предок — раннер Playwright. Это чужой идущий
 * прогон (текущий завершился, и его раннер — в `protectedPids`), его браузеры
 * и проигрыватели мы не режем.
 */
function belongsToLiveRun(table: Map<number, ProcInfo>, proc: ProcInfo, protectedPids: Set<number>): boolean {
  for (const pid of ancestorChain(table, proc.pid)) {
    if (protectedPids.has(pid)) return false;
    const ancestor = table.get(pid);
    if (ancestor && /node/i.test(ancestor.name) && ancestor.cmd.toLowerCase().includes("playwright")) {
      return true;
    }
  }
  return false;
}

function isRunProcess(proc: ProcInfo): boolean {
  const name = proc.name.toLowerCase();
  if (!RUN_PROCESS_NAMES[name]) return false;
  // Из node-процессов прогона интересует только сам Playwright.
  if (name === "node" || name === "node.exe") return proc.cmd.toLowerCase().includes("playwright");
  return true;
}

function belongsToRun(proc: ProcInfo): boolean {
  const cmd = proc.cmd.toLowerCase();
  if (cmd.includes(REPO_ROOT_LC)) return true;
  return RUN_OUTPUT_DIRS_LC.some((dir) => cmd.includes(dir));
}

/** Браузер Playwright, чей родитель умер, — то есть оставшийся от прогона. */
function isOrphanedPlaywrightBrowser(table: Map<number, ProcInfo>, proc: ProcInfo): boolean {
  if (!PLAYWRIGHT_PROFILE_RE.test(proc.cmd)) return false;
  const parent = table.get(proc.ppid);
  return parent === undefined;
}

function browserRoots(
  table: Map<number, ProcInfo>,
  protectedPids: Set<number>,
): Array<{ pid: number; why: string }> {
  const candidates = new Map<number, string>();
  const skipped: string[] = [];
  for (const proc of table.values()) {
    if (protectedPids.has(proc.pid) || !isRunProcess(proc)) continue;
    if (belongsToLiveRun(table, proc, protectedPids)) {
      skipped.push(`${proc.name} (PID ${proc.pid}) — идёт чужой прогон`);
      continue;
    }
    if (belongsToRun(proc)) {
      candidates.set(proc.pid, `${proc.name} прогона (путь репо/артефактов в cmdline)`);
    } else if (isOrphanedPlaywrightBrowser(table, proc)) {
      candidates.set(proc.pid, `${proc.name} Playwright с умершим родителем`);
    }
  }
  for (const note of skipped) log(`  ⏭ ${note} — не трогаем`);
  const roots: Array<{ pid: number; why: string }> = [];
  for (const [pid, why] of candidates) {
    const parentPid = table.get(pid)?.ppid;
    // Дети добиваются `/T` вместе с корнем — режем только вершины.
    if (parentPid !== undefined && candidates.has(parentPid)) continue;
    roots.push({ pid, why });
  }
  return roots;
}

/* ------------------------------------------------------------------ */
/* Запуск                                                             */
/* ------------------------------------------------------------------ */

/** Снимок процессов + защищённые PID (раннер Playwright и его родители). */
function snapshot(): { table: Map<number, ProcInfo>; protectedPids: Set<number> } {
  const table = new Map(sampleProcesses().map((proc) => [proc.pid, proc]));
  return { table, protectedPids: new Set([SELF_PID, ...ancestorChain(table, SELF_PID)]) };
}

async function runTeardown(): Promise<void> {
  const { table, protectedPids } = snapshot();

  try {
    if (table.size === 0) {
      log("⚠ список процессов недоступен — уборка браузеров пропущена");
      return;
    }
    log("Проверяю осиротевшие браузеры/проигрыватели прогона:");
    const leftovers = browserRoots(table, protectedPids);
    if (leftovers.length === 0) log("  (не найдено)");
    for (const { pid, why } of leftovers) killTree(pid, why);
  } catch (err) {
    log(`⚠ уборка браузеров не удалась: ${(err as Error).message}`);
  }

  log("Стек прогона убирает Playwright (webServer) — порты не трогаю.");
  log("Уборка завершена.");
}

export default async function globalTeardown(): Promise<void> {
  try {
    await runTeardown();
  } catch (err) {
    // Ошибка уборки не должна замаскировать результат прогона (падение теста).
    log(`⚠ уборка прервана: ${(err as Error).message}`);
  }
}
