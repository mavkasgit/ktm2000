#!/usr/bin/env node
// Предпроверка рабочего дерева одной командой (#360).
//
// Только читает: ничего не устанавливает, не поднимает, не меняет. Задача — до
// первого действия увидеть, что дерево не то, чем кажется: чужой WIP, свежий
// worktree без трёх неотслеживаемых файлов, мёртвый Postgres, занятый порт,
// устаревший индекс разведки, незакрытые хуки.
//
// Итог — GO или NO-GO со списком нехваток. `--root=` позволяет прогнать тот же
// чек по чужому worktree, не трогая его (и это же пробник для NO-GO).

import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { createConnection } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SELF = dirname(dirname(fileURLToPath(import.meta.url)));

const args = process.argv.slice(2);
const unknown = args.filter((a) => !a.startsWith("--root=") && a !== "--json");
if (unknown.length) {
  console.error(`doctor: неизвестный аргумент ${unknown.join(" ")} (есть --root=<путь>, --json)`);
  process.exit(2);
}
const rootArg = args.find((a) => a.startsWith("--root="));
const ROOT = rootArg ? resolve(rootArg.slice("--root=".length)) : SELF;

function git(...rest) {
  const r = spawnSync("git", ["-C", ROOT, ...rest], { encoding: "utf8" });
  return { ok: r.status === 0, out: (r.stdout || "").trim(), err: (r.stderr || "").trim() };
}

function probePort(port, timeout = 1500) {
  return new Promise((res) => {
    const sock = createConnection({ host: "127.0.0.1", port, connectTimeout: timeout });
    const done = (value) => {
      sock.destroy();
      res(value);
    };
    sock.on("connect", () => done("открыт"));
    sock.on("timeout", () => done("нет ответа"));
    sock.on("error", (e) => done(e.code === "ECONNREFUSED" ? "закрыт" : `ошибка ${e.code}`));
  });
}

const checks = [];
const add = (name, state, detail) => checks.push({ name, state, detail });
const state = (ok, good, bad) => (ok ? good : bad);

// 1. Ветка и чистота дерева.
const branch = git("rev-parse", "--abbrev-ref", "HEAD");
add(
  "ветка",
  branch.ok ? "ок" : "нет",
  branch.ok ? branch.out : `git не отвечает: ${branch.err || "нет дерева"}`,
);
const dirty = git("status", "--porcelain");
const dirtyLines = dirty.ok ? dirty.out.split(/\r?\n/).filter(Boolean) : [];
add(
  "чистота дерева",
  dirty.ok ? (dirtyLines.length ? "грязно" : "ок") : "нет",
  dirty.ok
    ? `${dirtyLines.length} изменённых путей${dirtyLines.length ? `: ${dirtyLines.slice(0, 6).join(", ")}${dirtyLines.length > 6 ? " …" : ""}` : ""}`
    : "git status не выполнился",
);

// 2. node_modules / .venv и версии.
const py = process.platform === "win32" ? "Scripts/python.exe" : "bin/python";
for (const [label, path, versionCmd] of [
  ["node_modules (корень)", "node_modules", null],
  ["node_modules (frontend)", "frontend/node_modules", null],
  ["backend/.venv", `backend/.venv/${py}`, `backend/.venv/${py} -V`],
]) {
  const present = existsSync(join(ROOT, path));
  let version = "";
  if (versionCmd && present) {
    const r = spawnSync(versionCmd.split(" ")[0], versionCmd.split(" ").slice(1), {
      cwd: ROOT,
      encoding: "utf8",
    });
    version = r.status === 0 ? (r.stdout || r.stderr || "").trim() : "не читается";
  }
  add(label, state(present, "ок", "нет"), present ? version || "есть" : `${path} отсутствует`);
}

// 3. Env-файлы: в свежем worktree их нет, и падение выглядит как баг продукта.
for (const envFile of [".env.dev", ".env.test", ".env.e2e"]) {
  const present = existsSync(join(ROOT, envFile));
  add(
    `env ${envFile}`,
    state(present, "ок", "нет"),
    present ? "есть" : `${envFile} нет — в новом worktree их надо копировать из основного дерева`,
  );
}

// 4. Postgres-инстансы должны отвечать, порты приложения — быть свободны.
const ports = await Promise.all([5440, 5441, 8012, 5172].map(probePort));
const [devPg, testPg, backendPort, frontendPort] = ports;
add("Postgres dev :5440", devPg === "открыт" ? "ок" : "нет", `порт ${devPg}`);
add("Postgres test :5441", testPg === "открыт" ? "ок" : "нет", `порт ${testPg}`);
add(
  "backend :8012 свободен",
  backendPort === "закрыт" ? "ок" : "занят",
  backendPort === "закрыт" ? "никто не слушает (dev-стек не поднят)" : `dev-стек отвечает: ${backendPort}`,
);
add(
  "frontend :5172 свободен",
  frontendPort === "закрыт" ? "ок" : "занят",
  frontendPort === "закрыт" ? "никто не слушает (dev-стек не поднят)" : `dev-стек отвечает: ${frontendPort}`,
);

// 5. Возраст индекса разведки — чужой скрипт, то же состояние.
const cg = spawnSync(process.execPath, [join(SELF, "scripts/codegraph-age.mjs"), "--json"], {
  cwd: ROOT,
  encoding: "utf8",
});
let cgVerdict = "нет";
let cgDetail = "скрипт возраста не ответил";
try {
  const parsed = JSON.parse(cg.stdout);
  cgVerdict = parsed.verdict === "ok" ? "ок" : parsed.verdict === "stale" ? "старый" : "нет";
  cgDetail = parsed.detail;
} catch {
  /* остаётся «нет» с текстом выше */
}
add("codegraph-индекс", cgVerdict, cgDetail);

// 6. Хуки: гейт полон и без них (принцип «хук ≠ гейт»), но отсутствие надо видеть.
//    Значение core.hooksPath, равное стандартному .git/hooks, ничего не означает:
//    в стандартном каталоге лежат только *.sample, и до коммита не запускается ничего.
//    Проверяем не конфиг, а живые исполняемые хуки по факту.
const hooksDir = git("rev-parse", "--git-path", "hooks").out || join(ROOT, ".git", "hooks");
let liveHooks = [];
try {
  liveHooks = readdirSync(resolve(ROOT, hooksDir)).filter((f) => !f.endsWith(".sample"));
} catch {
  /* каталога нет — живых хуков тоже нет */
}
add(
  "хуки до коммита",
  liveHooks.length ? "ок" : "пусто",
  liveHooks.length
    ? `${liveHooks.join(", ")} (${hooksDir})`
    : `в ${hooksDir} только *.sample — до коммита не запускается ничего (установка: npm run hooks:install; сам по себе это не поломка, гейт полный и без хуков)`,
);

// 7. Страж чужого дерева (#354): тот же вопрос, что задаёт pre-commit-хук, но
// без коммита. Без KTM_WORKTREE страж — явный no-op, и это информационная
// строка, а не поломка: одинокий клон репозитория не обязан ничего объявлять.
const guard = spawnSync(process.execPath, [join(SELF, "scripts/guard-tree.mjs"), "--json"], {
  cwd: ROOT,
  encoding: "utf8",
});
let guardState = "неясно";
let guardDetail = "страж дерева не ответил";
try {
  const parsed = JSON.parse(guard.stdout || "{}");
  if (parsed.verdict === "GO") {
    guardState = "ок";
    guardDetail = `объявленное дерево совпадает с тем, куда смотрит git (${parsed.facts.toplevel})`;
  } else if (parsed.verdict === "NO-GO") {
    guardState = "нет";
    guardDetail = parsed.problems.join("; ");
  } else {
    guardDetail = parsed.reason || "KTM_WORKTREE не задан — сверки нет";
  }
} catch {
  if (guard.stdout) guardDetail = guard.stdout.trim().slice(0, 200);
}
add("своё дерево (KTM_WORKTREE)", guardState, guardDetail);

const blockers = checks.filter((c) => ["нет", "грязно"].includes(c.state));
// Живой dev-стек, пустой каталог хуков и страж без объявленного дерева — не
// нехватки: первое хорошо, второе лечится `npm run hooks:install` (#353), третье
// означает «проверка неприменима», а не «проверка провалена».
const info = checks.filter((c) => ["занят", "неясно", "пусто"].includes(c.state));
const warnings = checks.filter((c) => c.state === "старый");
const go = blockers.length === 0;

if (args.includes("--json")) {
  console.log(
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        root: ROOT,
        branch: branch.out,
        verdict: go ? "GO" : "NO-GO",
        checks,
        blockers: blockers.map((c) => `${c.name}: ${c.detail}`),
        info: info.map((c) => `${c.name}: ${c.detail}`),
        warnings: warnings.map((c) => `${c.name}: ${c.detail}`),
      },
      null,
      2,
    ),
  );
} else {
  const mark = { ок: "✓", нет: "✗", старый: "⚠", грязно: "⚠", занят: "·", пусто: "·" };
  console.log(`doctor — ${ROOT}`);
  for (const c of checks) {
    console.log(`  ${mark[c.state] || "·"} ${c.name.padEnd(26)} ${String(c.state).padEnd(7)} ${c.detail}`);
  }
  console.log(
    go
      ? `итог: GO — красных нет из ${checks.length}${info.length + warnings.length ? ` (${info.length + warnings.length} информационных)` : ""}`
      : `итог: NO-GO — ${blockers.length} красных: ${blockers.map((c) => c.name).join(", ")}`,
  );
}

process.exitCode = go ? 0 : 1;
