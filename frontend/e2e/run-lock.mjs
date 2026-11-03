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
 * Правило подбора: держатель **мёртв** — лок снимается сразу и называется, из-за
 * чего; держатель жив — лок не отбирается никогда, какой бы возраст ни был
 * (#375). Возраст сам по себе был ложным свидетельством: долгий прогон терял
 * дерево, в котором ещё шёл, сосед занимал его место, и два стенда делили
 * `node_modules`, кеш браузеров и `test-results` — вердикт обоих перестаёт
 * читаться. Возраст живого держателя теперь только предупреждение
 * (`stallNotice`): зависший прогон видно по нему, а снятие — решение человека.
 *
 * Уборка клона привязана к смерти: клон брошенного прогона сносится, только
 * если мёртв его процесс (`reclaimReason(...).dead`).
 *
 * Payload лока: `{ tier, pid, at, runId }`. `runId` пишется с #281, чтобы
 * следующий прогон в дереве знал, чей клон БД остался от погибшего
 * предшественника, и снёс его, а не ждал `drop --stale-run-minutes` (180 мин).
 */

import fs from "node:fs";
import path from "node:path";

import { isProcessAlive } from "../../scripts/heavy-core.mjs";

export const DEFAULT_LOCK_TIMEOUT_MS = 30 * 60_000;
/**
 * С какого возраста живого держателя начинать подозревать зависание. Это НЕ
 * порог снятия: с #375 возраст не отбирает лок ни у кого живого.
 */
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

/**
 * Снимает лок, **только если он всё ещё наш**.
 *
 * Лок может перейти другому прогону: мёртвого держателя снимают, и сосед
 * занимает тот же файл. Прежний прогон в свой `finally` (`finalize()` в
 * `run-tier.mjs`) всё равно зовёт `releaseLock` — и снёс бы лок из-под
 * работающего. Сверка по `runId` (а не по `pid`) спасает и случай «тот же pid,
 * новый прогон»: `runId` у каждого прогона свой.
 */
export function releaseLock(file, runId) {
  const holder = readLock(file);
  if (holder && runId !== undefined && holder.runId !== runId) return;
  fs.rmSync(file, { force: true });
}

/**
 * Почему лок можно снять у текущего держателя.
 *
 * Ответ один: держатель мёртв. Возраст живого держателя сюда не входит — с #375
 * он не даёт права отнимать дерево у прогона, который ещё идёт.
 *
 * @returns {{dead: true, message: string}|null} `null` — держатель живой,
 *   отбирать нельзя.
 */
export function reclaimReason(holder, { alive = isProcessAlive } = {}) {
  if (!holder) return null;
  if (!alive(holder.pid)) {
    return {
      dead: true,
      message:
        `держатель (pid ${holder.pid ?? "?"}, ярус ${holder.tier ?? "?"}) мёртв — ` +
        "снимаю, прошлый прогон не убрал за собой",
    };
  }
  return null;
}

/**
 * Подозрение на зависание: живой держатель старше порога.
 *
 * Это не разрешение снять лок, а строка в логе ожидания: «долгий прогон» и
 * «прогон висит» выглядят одинаково, пока не назван возраст, и молчать о первом
 * — значит заставлять следующего ждать вслепую. Решение (ждать дальше или
 * убивать pid) остаётся за человеком.
 *
 * @returns {{ageMs: number, message: string}|null}
 */
export function stallNotice(
  holder,
  {
    staleMs = DEFAULT_LOCK_STALE_MS,
    now = () => Date.now(),
    alive = isProcessAlive,
  } = {},
) {
  if (!holder || !alive(holder.pid)) return null;
  const age = now() - (holder.at ?? now());
  if (age <= staleMs) return null;
  return {
    ageMs: age,
    message:
      `держатель (pid ${holder.pid ?? "?"}, ярус ${holder.tier ?? "?"}) жив и держит лок ` +
      `${Math.round(age / 60_000)} мин (порог подозрения ${Math.round(staleMs / 60_000)} мин) — ` +
      "не отбираю; если прогон завис, решать надо по pid, а не возрастом",
  };
}
