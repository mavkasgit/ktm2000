/**
 * Лок рабочего дерева на один прогон E2E (#281).
 *
 * Зачем отдельным модулем
 * -----------------------
 * `node_modules/.e2e-run/current.lock` сериализует прогоны **внутри одного
 * worktree** (отчёт Playwright, `test-results`, кеш браузеров у дерева одни).
 * Машинный предел держит семафор (`run-slots.mjs`), но именно этот лок
 * встречает следующий прогон после падения предыдущего — и до появления модуля
 * он умел только «подождать 40 минут и снять по возрасту». Процесс, убитый
 * (`taskkill`, падение ОС, отмена задачи), держал дерево до получаса, хотя
 * проверить живость процесса — одна системная ошибка `ESRCH`.
 *
 * Правило подбора теперь симметрично семафору: держатель **мёртв** — лок
 * снимается сразу и называется, из-за чего; держатель жив — лок отдаётся
 * только по возрасту (`staleMs`), как и раньше. Разница принципиальна для
 * уборки: клон БД брошенного прогона сносится, только если мёртв его процесс
 * (`reclaimReason(...).dead`), а не потому, что прогон просто долгий.
 *
 * Payload лока: `{ tier, pid, at, runId }`. `runId` пишется с #281, чтобы
 * следующий прогон в дереве знал, чей клон БД остался от погибшего
 * предшественника, и снёс его, а не ждал `drop --stale-run-minutes` (180 мин).
 */

import fs from "node:fs";
import path from "node:path";

import { isProcessAlive } from "./run-slots.mjs";

export const DEFAULT_LOCK_TIMEOUT_MS = 30 * 60_000;
export const DEFAULT_LOCK_STALE_MS = 40 * 60_000;

/** Файл лока дерева: `node_modules/.e2e-run/current.lock` (в `.gitignore`). */
export function lockFileIn(frontendDir) {
  return path.join(frontendDir, "node_modules", ".e2e-run", "current.lock");
}

export function readLock(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** Пишет лок эксклюзивно; false — лок уже держит кто-то другой. */
export function tryAcquireLock(file, payload) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  try {
    // "wx" — атомарно: файл создаётся, только если его не было.
    fs.writeFileSync(file, JSON.stringify(payload), { flag: "wx" });
    return true;
  } catch (err) {
    if (err.code === "EEXIST") return false;
    throw err;
  }
}

export function releaseLock(file) {
  fs.rmSync(file, { force: true });
}

/**
 * Почему лок можно снять у текущего держателя.
 *
 * @returns {{dead: boolean, message: string}|null} `null` — держатель живой и
 *   лок свежий, отбирать нельзя.
 */
export function reclaimReason(
  holder,
  {
    staleMs = DEFAULT_LOCK_STALE_MS,
    now = Date.now(),
    alive = isProcessAlive,
  } = {},
) {
  if (!holder) return null;
  if (!alive(holder.pid)) {
    return {
      dead: true,
      message:
        `держатель (pid ${holder.pid ?? "?"}, ярус ${holder.tier ?? "?"}) мёртв — ` +
        "снимаю, прошлый прогон не убрал за собой",
    };
  }
  const age = now() - (holder.at ?? now());
  if (age > staleMs) {
    return {
      dead: false,
      message:
        `держатель (pid ${holder.pid}, ярус ${holder.tier ?? "?"}) держит лок ` +
        `${Math.round(age / 60_000)} мин (> ${Math.round(staleMs / 60_000)}) — снимаю`,
    };
  }
  return null;
}
