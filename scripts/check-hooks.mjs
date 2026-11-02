#!/usr/bin/env node
// Проверка, что хуки действительно установлены (#353).
//
// `lefthook install` — действие разовое и не наследуется: новый клон, новый
// worktree или переустановка node_modules оставляют core.hooksPath прежним, а
// файлов хуков в нём уже нет. Отличить «хуки есть» от «хуки были» можно только
// по факту: какие lifecycle-хуки объявлены в lefthook.yml и есть ли под каждый
// shim в каталоге хуков.
//
// Только читает. Ничего не устанавливает: вывод — готовая команда.

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
const json = args.includes("--json");
if (args.some((a) => a !== "--json")) {
  console.error("hooks:check: аргументов нет, кроме --json");
  process.exit(2);
}

function git(...rest) {
  const r = spawnSync("git", ["-C", ROOT, ...rest], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
}

const configPath = join(ROOT, "lefthook.yml");
const declared = existsSync(configPath)
  ? Object.keys(
      (function readTopLevel(text) {
        // Без yaml-парсера: нужны только имена секций нулевого отступа.
        const out = {};
        for (const line of text.split(/\r?\n/)) {
          if (/^[a-z][a-z-]*:$/.test(line)) out[line.slice(0, -1)] = true;
        }
        return out;
      })(readFileSync(configPath, "utf8")),
    )
  : [];

const hooksDirRaw = git("rev-parse", "--git-path", "hooks") || join(".git", "hooks");
const hooksDir = resolve(ROOT, hooksDirRaw);
const present = existsSync(hooksDir) ? readdirSync(hooksDir).filter((f) => !f.endsWith(".sample")) : [];

const missing = declared.filter((h) => !present.includes(h));
const extra = present.filter((h) => !declared.includes(h));
const configMissing = declared.length === 0;

const verdict = configMissing ? "нет конфига" : missing.length ? "не установлены" : "установлены";
const ok = !configMissing && !missing.length;

const report = {
  ok,
  config: configMissing ? null : "lefthook.yml",
  core_hooks_path: git("config", "--get", "core.hooksPath") || "(не задан, используется " + hooksDirRaw + ")",
  hooks_dir: hooksDir,
  declared,
  present,
  missing,
  extra,
  verdict,
};

if (json) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(`lefthook.yml: ${report.config ?? "нет"} — объявлено хуков: ${declared.length}${configMissing ? " (конфига нет ⇒ ничего не объявлено)" : ""}`);
  console.log(`core.hooksPath: ${report.core_hooks_path}`);
  console.log(`каталог хуков: ${hooksDir}`);
  for (const h of declared) {
    console.log(`  ${present.includes(h) ? "✓" : "✗"} ${h.padEnd(20)} ${present.includes(h) ? "shim есть" : "shim отсутствует"}`);
  }
  for (const h of extra) console.log(`  · ${h.padEnd(20)} в lefthook.yml не объявлен (остаток или чужой хук) ·`);
  console.log(
    ok
      ? `итог: ${verdict} — но хук остаётся удобством: ` +
        `полный набор проверок даёт npm run gate, он работает и без хуков`
      : `итог: ${verdict} — установка: npm run hooks:install`,
  );
}

process.exitCode = ok ? 0 : 1;
