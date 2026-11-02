#!/usr/bin/env node
// Реестр инструментов: чем проект проверяют, где закреплено, где исполняется (#356).
//
// Схема (tools.schema.json) исполняется через Ajv, а не предлагается «на веру»:
// запись без полей или с лишним полем красная. `pinned_in` читается из файла —
// заявить закрепление там, где его нет, нельзя. Дубликаты id/repo ловятся
// независимо от регистра.
//
// docs/toolchain.md — производная от реестра (срез D, #383). Пока документа нет,
// это «не сгенерирован», а не красное: проверка не требует того, чего ещё не существует.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const REGISTRY = "tools.json";
const SCHEMA = "tools.schema.json";
const DOC = "docs/toolchain.md";
const DOC_BLOCK = /<!-- tools:start -->([\s\S]*?)<!-- tools:end -->/;
/** Пути в реестре записываются прямыми слешами; на Windows join() даёт обратные. */
const norm = (p) => p.replaceAll("\\", "/");

const args = process.argv.slice(2);
const jsonOut = args.includes("--json");
const emitTable = args.includes("--emit-table");
for (const flag of args) {
  if (!["--json", "--emit-table"].includes(flag)) {
    console.error(`check-registry: неизвестный флаг ${flag} (есть --json, --emit-table)`);
    process.exit(2);
  }
}

const read = (rel) => readFileSync(join(ROOT, rel), "utf8");
const rootManifest = JSON.parse(read("package.json"));
const frontManifest = JSON.parse(read("frontend/package.json"));
const problems = [];
const notes = [];

const fail = (msg) => problems.push(msg);

if (!existsSync(join(ROOT, REGISTRY))) fail(`${REGISTRY} отсутствует`);
if (!existsSync(join(ROOT, SCHEMA))) fail(`${SCHEMA} отсутствует`);

let registry = null;
if (!problems.length) {
  for (const [rel, sink] of [
    [REGISTRY, "реестр"],
    [SCHEMA, "схема"],
  ]) {
    try {
      JSON.parse(read(rel));
    } catch (error) {
      fail(`${rel}: не читается как JSON (${sink}) — ${error.message}`);
    }
  }
}

if (!problems.length) {
  try {
    registry = JSON.parse(read(REGISTRY));
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    const validate = ajv.compile(JSON.parse(read(SCHEMA)));
    if (!validate(registry)) {
      for (const err of validate.errors) {
        const at = err.instancePath || "/";
        const extra = err.params?.additionalProperty ? ` (${err.params.additionalProperty})` : "";
        fail(`схема: ${at} ${err.message}${extra}`);
      }
    }
  } catch (error) {
    registry = null;
    fail(`схема не исполняется: ${error.message}`);
  }
}

if (registry) {
  const tools = registry.tools;

  // (д) дубликаты — независимо от регистра.
  for (const field of ["id", "repo"]) {
    const seen = new Map();
    for (const tool of tools) {
      const key = String(tool[field]).toLowerCase();
      const prev = seen.get(key);
      if (!prev) {
        seen.set(key, tool);
        continue;
      }
      // Один репозиторий ≠ один инструмент: vitest и @vitest/coverage-v8 живут в
      // vitest-dev/vitest, но решают разные задачи и блокируют по-разному.
      // Различаются пакетом — значит это разные артефакты, не дубль записи.
      const distinctArtifacts =
        tool.npm_package && prev.npm_package && tool.npm_package !== prev.npm_package;
      if (!(field === "repo" && distinctArtifacts)) {
        fail(`${field} «${tool[field]}» дублирует запись «${prev.id}»`);
      } else {
        notes.push(`repo ${tool[field]} общий для ${prev.id} и ${tool.id} — разные пакеты`);
      }
    }
  }

  // (б) заявленное закрепление обязано быть в файле.
  for (const tool of tools) {
    const where = tool.pinned_in;
    if (where === "absent") {
      if (tool.version !== "absent") fail(`${tool.id}: pinned_in=absent, а version «${tool.version}»`);
      continue;
    }
    if (tool.version === "absent") fail(`${tool.id}: version=absent, а pinned_in «${where}»`);
    const abs = join(ROOT, where);
    if (!existsSync(abs)) {
      fail(`${tool.id}: закреплений в ${where} нет — файла/каталога не существует`);
      continue;
    }
    let haystack;
    let single = null;
    if (statSync(abs).isDirectory()) {
      const files = readdirSync(abs)
        .filter((name) => /\.(yml|yaml)$/.test(name))
        .map((name) => readFileSync(join(abs, name), "utf8"));
      if (!files.length) {
        fail(`${tool.id}: в каталоге ${where} нет *.yml — где искать закрепление?`);
        continue;
      }
      haystack = files.join("\n");
    } else {
      const text = readFileSync(abs, "utf8");
      const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
      // Файл-пин (.nvmrc, .python-version): версия обязана совпадать целиком,
      // иначе «24» пройдёт в файле, где написано «240».
      if (lines.length === 1) single = lines[0].trim();
      else haystack = text;
    }
    if (single !== null) {
      if (single !== tool.version) {
        fail(`${tool.id}: ${where} = «${single}», в реестре заявлено «${tool.version}»`);
      }
    } else if (!haystack.includes(tool.version)) {
      fail(`${tool.id}: «${tool.version}» не найдено в ${where}`);
    }
  }

  // (г) пакет в package.json без записи в реестр ⇒ красный.
  const npmPackages = new Set(
    tools.map((t) => t.npm_package).filter((p) => typeof p === "string" && p),
  );
  const rootDeps = Object.keys(rootManifest.devDependencies || {});
  for (const dep of rootDeps) {
    if (!npmPackages.has(dep)) fail(`${dep}: есть в package.json (devDependencies), в реестре нет`);
  }
  const frontDeps = Object.keys({
    ...(frontManifest.devDependencies || {}),
    ...(frontManifest.dependencies || {}),
  });
  // Устаревшая запись: реестр ссылается на пакет, который из манифеста исчез.
  for (const tool of tools.filter((t) => t.npm_package)) {
    const declared = norm(tool.pinned_in) === "package.json" ? rootDeps : frontDeps;
    if (!declared.includes(tool.npm_package)) {
      fail(`${tool.id}: пакет ${tool.npm_package} не объявлен в ${tool.pinned_in}`);
    }
  }

  notes.push(`${tools.length} записей, блокирующих ${tools.filter((t) => t.blocking).length}`);
}

// docs/toolchain.md между маркерами — генерация от реестра, не второй источник.
function renderTable() {
  const rows = [...registry.tools].sort((a, b) => a.id.localeCompare(b.id));
  const head =
    "| id | чем | закреплено где | версия | где исполняется | блокирует | последний обзор |\n| --- | --- | --- | --- | --- | --- | --- |";
  const body = rows.map(
    (t) =>
      `| \`${t.id}\` | ${t.name} (${t.repo}) | \`${t.pinned_in}\` | \`${t.version}\` | ${t.runs_at.join(", ")} | ${t.blocking ? "да" : "нет"} | ${t.last_reviewed} |`,
  );
  return [head, ...body].join("\n");
}

let docStatus = "не проверен";
if (registry && !problems.length) {
  const docPath = join(ROOT, DOC);
  if (!existsSync(docPath)) {
    docStatus = "не сгенерирован";
    notes.push(`${DOC} ещё не сгенерирован (#383) — расхождение сверять не с чем`);
  } else {
    const block = DOC_BLOCK.exec(readFileSync(docPath, "utf8"));
    if (!block) {
      docStatus = "нет маркеров";
      fail(`${DOC}: нет блока <!-- tools:start --> / <!-- tools:end -->`);
    } else {
      const inDoc = block[1].trim();
      const fresh = renderTable().trim();
      docStatus = inDoc === fresh ? "совпадает" : "расходится";
      if (inDoc !== fresh) {
        const listed = new Set([...block[1].matchAll(/\| `([a-z0-9._-]+)`/g)].map((m) => m[1]));
        const ids = new Set(registry.tools.map((t) => t.id));
        const gone = [...listed].filter((id) => !ids.has(id));
        const added = [...ids].filter((id) => !listed.has(id));
        const changed = [...listed].filter((id) => ids.has(id)).length;
        fail(
          `${DOC} отстал от ${REGISTRY}: новых ${added.length} [${added.join(", ")}], удалённых ${gone.length} [${gone.join(", ")}], сверено строк ${changed} — пересобрать документ`,
        );
      }
    }
  }
}

if (emitTable) {
  if (!registry) {
    console.error("check-registry: реестр не загружен");
    process.exit(1);
  }
  console.log(renderTable());
  process.exit(0);
}

if (jsonOut) {
  console.log(
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        registry: registry ? registry.tools.length : 0,
        doc: docStatus,
        problems,
        notes,
      },
      null,
      2,
    ),
  );
} else {
  console.log(`реестр: ${registry ? `${registry.tools.length} записей` : "не загружен"} — ${DOC} ${docStatus}`);
  for (const note of notes) console.log(`  · ${note}`);
  for (const problem of problems) console.log(`  ✗ ${problem}`);
}

process.exitCode = problems.length ? 1 : 0;
