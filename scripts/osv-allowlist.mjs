#!/usr/bin/env node
// Датированные исключения аудита зависимостей (#369).
//
// Принцип проекта: исключение из проверки — не молчаливый `|| true` и не пустой
// список, а запись с причиной и датой пересмотра. Здесь живёт единственный
// источник правды для allowlist osv-scanner: из него генерируется TOML-конфиг
// скана (`--write`), и он же проверяется на просроченные записи (`--check`).
//
// Почему JSON, а не сразу `.osv-scanner.toml`: у osv-scanner в блоке
// `[[IgnoredVulns]]` есть только `id` и `ignoreUntil` — поля «причина» нет.
// Причина в комментарии TOML не переживёт правку руками и не проверяется
// машиной, а просроченное исключение обязано краснеть.
//
// Запуск: node scripts/osv-allowlist.mjs --check
//         node scripts/osv-allowlist.mjs --write /tmp/osv.toml

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const ALLOWLIST = ".github/osv-allowlist.json";

/** iso-дата (YYYY-MM-DD) из строки; null — формат не тот. */
export function parseDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Проверка записей: у каждой — id, package, reason, review_by в будущем.
 * Просроченная запись — ошибка, а не предупреждение: «пересмотреть до» без
 * последствий не пересматривают.
 */
export function validateEntries(entries, today) {
  const errors = [];
  if (!Array.isArray(entries)) {
    return ["entries: ожидался массив записей"];
  }
  const seen = new Set();
  for (const [index, entry] of entries.entries()) {
    const at = `entries[${index}]`;
    for (const field of ["id", "package", "reason", "review_by"]) {
      if (typeof entry?.[field] !== "string" || !entry[field].trim()) {
        errors.push(`${at}: пустое поле ${field}`);
      }
    }
    const reviewBy = parseDate(entry?.review_by);
    if (entry?.review_by && !reviewBy) {
      errors.push(`${at}: review_by «${entry.review_by}» — не дата YYYY-MM-DD`);
    } else if (reviewBy && reviewBy < today) {
      errors.push(
        `${at}: исключение ${entry.id} просрочено (review_by ${entry.review_by}) — ` +
          "уязвимость либо чинится обновлением, либо срок продлевается осознанно",
      );
    }
    if (entry?.id) {
      if (seen.has(entry.id)) errors.push(`${at}: id ${entry.id} повторяется`);
      seen.add(entry.id);
    }
  }
  return errors;
}

/** TOML-конфиг osv-scanner: только `id` + `ignoreUntil` (больше полей у него нет). */
export function toOsvToml(entries) {
  const head = [
    "# Сгенерировано scripts/osv-allowlist.mjs из .github/osv-allowlist.json.",
    "# Не править руками: причина и дата пересмотра живут в JSON.",
  ];
  const blocks = entries.map(
    (entry) =>
      `[[IgnoredVulns]]\nid = "${entry.id}"\nignoreUntil = ${entry.review_by}\n`,
  );
  return `${head.join("\n")}\n\n${blocks.join("\n")}`.trimEnd() + "\n";
}

export function checkAllowlist({ path = ALLOWLIST, today = new Date() } = {}) {
  const file = join(ROOT, path);
  if (!existsSync(file)) {
    return { ok: false, errors: [`нет ${path} — allowlist аудита не заведён`] };
  }
  let data;
  try {
    data = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    return { ok: false, errors: [`${path}: не читается как JSON (${error.message})`] };
  }
  // Дата локальная: срок пересмотра — решение человека в его часовом поясе.
  const day = new Date(`${today.toLocaleDateString("sv-SE")}T00:00:00Z`);
  const errors = validateEntries(data.entries, day);
  const expiredIds = data.entries
    ?.filter((entry) => parseDate(entry.review_by) && parseDate(entry.review_by) < day)
    .map((entry) => entry.id);
  return {
    ok: errors.length === 0,
    errors,
    entries: data.entries?.length ?? 0,
    expired: expiredIds?.filter(Boolean) ?? [],
  };
}

function main() {
  const args = process.argv.slice(2);
  const writeIndex = args.indexOf("--write");
  const checkIndex = args.indexOf("--check");

  if (writeIndex !== -1) {
    const target = args[writeIndex + 1];
    if (!target) {
      console.error("osv-allowlist: --write требует путь к файлу");
      return 2;
    }
    const data = JSON.parse(readFileSync(join(ROOT, ALLOWLIST), "utf8"));
    writeFileSync(target, toOsvToml(data.entries ?? []));
    console.log(`osv-allowlist: ${target} — записей ${data.entries?.length ?? 0}`);
    return 0;
  }
  if (checkIndex === -1) {
    console.error("osv-allowlist: нужен --check или --write <путь>");
    return 2;
  }

  const result = checkAllowlist();
  console.log(
    result.ok
      ? `osv-allowlist: ${result.entries} записей, просроченных нет`
      : `osv-allowlist: ${result.errors.length} ошибок`,
  );
  for (const error of result.errors ?? []) console.error(`  ✗ ${error}`);
  return result.ok ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = main();
}
