#!/usr/bin/env node
// Умный pre-push гейт: по `git diff <base>...HEAD` выбирает шаги `gate` и
// запускает только их. Полный `npm run gate` — когда затронуты обе зоны,
// конфиги/скрипты или базу определить не удалось.
//
// Это и есть основной гейт KTM: GitHub Actions остаётся фоновым вторым взглядом.
// Обход (`--no-verify`, `LEFTHOOK=0`) агенту запрещён — AGENTS.md.

import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolvePlan } from "./changed-scopes.mjs";

const ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

/** Разбор stdin git pre-push: `<local ref> <sha> <remote ref> <sha>`. */
export function parsePushRefs(input) {
  return String(input)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [localRef, localSha, remoteRef, remoteSha] = line.split(/\s+/);
      return { localRef, localSha, remoteRef, remoteSha };
    });
}

export function isDeleteOrTag(ref) {
  return ref.localRef === "(delete)" || ref.remoteRef?.startsWith("refs/tags/");
}

/** Только теги/удаления — код не меняется, гейт не нужен. */
export function shouldSkipRefs(refs) {
  return refs.length > 0 && refs.every(isDeleteOrTag);
}

/** Аргументы `node scripts/gate.mjs` для плана. */
export function buildGateArgs(plan) {
  if (plan.steps === null) return ["scripts/gate.mjs", "--strict"];
  return ["scripts/gate.mjs", `--only=${plan.steps.join(",")}`, "--strict"];
}

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const filesArg = args.find((arg) => arg.startsWith("--files="));
  const baseArg = args.find((arg) => arg.startsWith("--base="));

  const refs = parsePushRefs(readFileSync(0, "utf8"));
  if (shouldSkipRefs(refs)) {
    console.log("pre-push gate: только теги/удаления — проверки не нужны");
    return;
  }

  const plan = resolvePlan({
    files: filesArg
      ? filesArg
          .slice("--files=".length)
          .split(",")
          .map((file) => file.trim())
          .filter(Boolean)
      : null,
    base: baseArg ? baseArg.slice("--base=".length) : null,
  });

  const where = plan.base
    ? `база ${plan.base}`
    : filesArg
      ? "явный список файлов"
      : "база не найдена";
  const what = plan.steps === null ? "полный npm run gate" : plan.steps.join(", ");
  console.log(`pre-push gate: ${where}; файлов ${plan.files.length}; скоуп ${plan.scope}`);
  console.log(`pre-push gate: ${what}`);

  if (plan.files.length === 0 && plan.base) {
    console.log("pre-push gate: изменений относительно базы нет — проверки не нужны");
    return;
  }

  if (dryRun) return;

  const gateArgs = buildGateArgs(plan);
  const started = Date.now();
  const result = spawnSync(process.execPath, gateArgs, { cwd: ROOT, stdio: "inherit" });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);

  if (result.error) {
    console.error(`pre-push gate: не удалось запустить gate — ${result.error.message}`);
    process.exit(1);
  }

  if (result.status !== 0) {
    console.error("");
    console.error(`pre-push gate: КРАСНЫЙ (${seconds} с) — push остановлен.`);
    console.error("Агенту обход запрещён (AGENTS.md). Аварийный выход человека:");
    console.error("  git push --no-verify");
    process.exit(result.status ?? 1);
  }

  console.log(`pre-push gate: зелёный (${seconds} с)`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
