/**
 * Уборка клонов БД прогона, умершего в **чужом** worktree (#306).
 *
 * Зачем
 * -----
 * `run-tier.mjs` убирает клон своего прогона в `finally`, но процесс, убитый
 * снаружи (`taskkill`, отмена задачи, падение ОС), `finally` не выполняет.
 * Свой лок дерева это спасает: следующий прогон в том же дереве видит мёртвый
 * pid и сносит клон по `runId` из лока. **Кросс-деревянный случай не спасается
 * ничем**: лок чужой, а `drop --stale-run-minutes` (180 мин) ждёт возраста.
 *
 * После изоляции по воркерам (#289) это стало заметнее: клонов на прогон
 * столько же, сколько воркеров, и каждый — на своём Postgres с своим
 * хранилищем. До #306 брошенный прогон держал на диске N клонов и N
 * env-файлов, пока не отработал бы `--stale-run-minutes`.
 *
 * Почему это безопасно
 * --------------------
 * Уборке отдаются **только** слоты, чей держатель мёртв (`run-slots.mjs`
 * проверяет живость pid системным `process.kill(pid, 0)` и зовёт `onReclaim`
 * до удаления файла слота). Прогон, который идёт, сюда не попадает никогда:
 * его pid жив. Возраст для решения не используется **никак** — «мёртв pid»
 * это факт, а «прошло 180 минут» это догадка, которая однажды снесёт живой
 * прогон соседа.
 *
 * Свой прогон пропускается по `runId`: слот мог быть переиспользован тем же
 * id, и сносить собственные клоны до `finalize` нельзя.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/**
 * Снести клоны прогонов, чьи слоты были отобраны как мёртвые.
 *
 * @param holders записи слотов в форме `{ repo, runId, envFile, pid }`
 * @param ownRunId `runId` текущего прогона — его клоны не трогаем
 * @returns {{cleaned: string[], skipped: string[], failed: string[]}}
 */
export function cleanupAbandonedRuns(holders, { ownRunId, log = console.log, run = spawnSync } = {}) {
  const result = { cleaned: [], skipped: [], failed: [] };
  for (const holder of holders) {
    const { repo, runId, envFile } = holder ?? {};
    if (!repo || !runId) {
      result.skipped.push(`слот без repo/runId: ${JSON.stringify(holder ?? {})}`);
      continue;
    }
    if (runId === ownRunId) {
      result.skipped.push(`runId ${runId} — свой прогон, не трогаю`);
      continue;
    }
    // Скрипт и env-файл чужого прогона должны существовать: если их нет,
    // прогон не оставил клонов (или дерево уже удалили) — трогать нечего.
    const script = path.join(repo, "scripts", "e2e-db.py");
    if (!fs.existsSync(script)) {
      result.skipped.push(`runId ${runId}: нет ${script} — нечего убирать`);
      continue;
    }
    if (envFile && !fs.existsSync(envFile)) {
      result.skipped.push(`runId ${runId}: env-файл ${envFile} не найден — нечего убирать`);
      continue;
    }

    const args = [script, "drop", "--run-id", runId];
    if (envFile) args.push("--env-file", envFile);
    const dropped = run("python", args, {
      cwd: repo,
      encoding: "utf8",
      shell: false,
      maxBuffer: 8 * 1024 * 1024,
    });
    if ((dropped.status ?? 1) === 0) {
      result.cleaned.push(runId);
      log(
        `[e2e:run] прогон ${runId} из чужого дерева (pid ${holder.pid ?? "?"}) мёртв — ` +
          `клоны снесены: ${(dropped.stdout ?? "").trim().split("\n").slice(-1)[0] ?? "ок"}`,
      );
    } else {
      result.failed.push(runId);
      log(
        `[e2e:run] клоны прогона ${runId} (чужое дерево) не снесены ` +
          `(код ${dropped.status}): ${`${dropped.stdout ?? ""}${dropped.stderr ?? ""}`.slice(-400)}`,
      );
    }
  }
  return result;
}