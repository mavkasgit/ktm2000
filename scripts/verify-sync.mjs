/**
 * Синк-гейт переносимых файлов между sibling-проектами HRMS/KTM.
 *
 * Сверяет файлы, помеченные в scripts/sync-manifest.json как must-match.
 * Синхронизация ручная: после правки общего файла агент переносит копию
 * в соседний проект и поднимает версию.
 *
 * Режимы сравнения (поле entry.mode):
 *   - content  — байт-эквивалент, переводы строк (CRLF/LF) игнорируются;
 *   - version  — совпадение констант *_VERSION (или поля "version" в JSON)
 *                из хостового файла директории (для файла — сам файл);
 *   - presence — файл обязан существовать в обоих проектах, содержимое
 *                может различаться (хостовые файлы модулей, напр. ui.ts).
 * Поле entry.version:true добавляет к content-сравнению сверку версии.
 *
 * Запуск (из корня репозитория):
 *   node scripts/verify-sync.mjs --other ../hrms
 *   node scripts/verify-sync.mjs --other ../hrms --baseline scripts/sync-baseline.json
 *   node scripts/verify-sync.mjs --other ../hrms --if-enabled
 *
 * Baseline (JSON `{ "entries": [{ "path": "...", "reason": "..." }] }`) —
 * список известных расхождений: они подавляются, но печатаются как `known`.
 * Всё, чего в baseline нет, — падение. `--strict` baseline игнорирует: так
 * проверяют, что долг закрыт. Отсутствующий или битый baseline — exit 2.
 * Записи baseline, которые больше не понадобились, печатаются как `stale`
 * (не падение) — чтобы долг убирали, а не копили.
 *
 * В автоматическом режиме (`--if-enabled`) проверка выполняется только при
 * KTM_SYNCGATE=1|true|yes|on. Без переменной выход успешный, с неверном
 * значением — ошибка. Ручной запуск без флага проверяет всегда.
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

export const SYNC_VERSION = "1.2.0"

const MANIFEST = "scripts/sync-manifest.json"
const HOST_NAMES = ["index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"]
const MODES = new Set(["content", "version", "presence"])
const VERSION_RE = /(?:export\s+)?const\s+([A-Z][A-Z0-9_]*_VERSION)\s*=\s*["']([^"']+)["']/g

const ENABLED_VALUES = new Set(["1", "true", "yes", "on"])

export function parseArgs(argv) {
  const args = { other: null, root: null, ifEnabled: false, baseline: null, strict: false }
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--other" && argv[i + 1]) {
      args.other = argv[i + 1]
      i++
    } else if (argv[i] === "--root" && argv[i + 1]) {
      args.root = argv[i + 1]
      i++
    } else if (argv[i] === "--baseline" && argv[i + 1]) {
      args.baseline = argv[i + 1]
      i++
    } else if (argv[i] === "--if-enabled") {
      args.ifEnabled = true
    } else if (argv[i] === "--strict") {
      args.strict = true
    }
  }
  return args
}

export function normalize(content) {
  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}

export function extractVersions(content, filePath) {
  const versions = new Map()
  if (path.extname(filePath).toLowerCase() === ".json") {
    try {
      const parsed = JSON.parse(content)
      if (typeof parsed?.version === "string") versions.set("version", parsed.version)
    } catch {
      // не JSON — версий нет
    }
    return versions
  }
  for (const match of content.matchAll(VERSION_RE)) versions.set(match[1], match[2])
  return versions
}

function hostFileFor(rel, root) {
  const abs = path.join(root, rel)
  if (!fs.existsSync(abs)) return null
  if (fs.statSync(abs).isFile()) return abs
  for (const name of HOST_NAMES) {
    const candidate = path.join(abs, name)
    if (fs.existsSync(candidate)) return candidate
  }
  return null
}

function compareVersions(fileA, fileB, rel) {
  const errors = []
  const a = normalize(fs.readFileSync(fileA, "utf8"))
  const b = normalize(fs.readFileSync(fileB, "utf8"))
  const va = extractVersions(a, fileA)
  const vb = extractVersions(b, fileB)
  const keys = new Set([...va.keys(), ...vb.keys()])
  if (keys.size === 0) {
    errors.push(`не найдены константы *_VERSION: ${rel}`)
    return errors
  }
  for (const key of keys) {
    if (va.get(key) !== vb.get(key)) {
      errors.push(
        `version mismatch: ожидалось ${va.get(key) ?? "—"}, у соседа ${vb.get(key) ?? "—"} (${rel}: ${key})`,
      )
    }
  }
  return errors
}

/**
 * Читает baseline. Возвращает либо Map path → reason, либо { error }.
 * Битый или отсутствующий файл — ошибка конфигурации (exit 2), а не расхождение.
 */
export function loadBaseline(absPath) {
  let raw
  try {
    raw = fs.readFileSync(absPath, "utf8")
  } catch (error) {
    return { error: `baseline не читается: ${absPath} (${error.message})` }
  }
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (error) {
    return { error: `baseline не JSON: ${absPath} (${error.message})` }
  }
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.entries)) {
    return { error: `baseline не содержит массив entries: ${absPath}` }
  }
  const entries = new Map()
  for (const [index, entry] of parsed.entries.entries()) {
    if (!entry || typeof entry !== "object" || typeof entry.path !== "string" || entry.path.trim() === "") {
      return { error: `baseline: запись #${index} без строкового path: ${absPath}` }
    }
    const reason = typeof entry.reason === "string" && entry.reason.trim() ? entry.reason.trim() : "без причины"
    entries.set(entry.path.trim(), reason)
  }
  return { entries }
}

export function run({ root, otherRoot, manifestPath = MANIFEST, baselinePath = null, strict = false }) {
  const manifestFile = path.join(root, manifestPath)
  let manifest
  try {
    manifest = JSON.parse(fs.readFileSync(manifestFile, "utf8"))
  } catch (error) {
    return {
      ok: false,
      errors: [`Не удалось прочитать манифест: ${manifestFile} (${error.message})`],
      known: [],
      stale: [],
      problems: [],
      checked: 0,
      exitCode: 1,
    }
  }
  const entries = manifest.files
  if (!Array.isArray(entries) || entries.length === 0) {
    return {
      ok: false,
      errors: [`манифест пуст или не содержит files: ${manifestFile}`],
      known: [],
      stale: [],
      problems: [],
      checked: 0,
      exitCode: 1,
    }
  }
  const problems = []
  let checked = 0
  const report = (message, rel) => problems.push({ path: rel, message, kind: "discrepancy" })
  const reportConfig = (message, rel) =>
    problems.push({ path: rel, message, kind: "config" })

  for (const entry of entries) {
    const rel = entry.path
    const mode = entry.mode ?? "content"
    if (!MODES.has(mode)) {
      reportConfig(`неизвестный режим сравнения: ${mode} (${rel})`, rel)
      continue
    }
    const hereAbs = path.join(root, rel)
    const thereAbs = path.join(otherRoot, rel)
    if (!fs.existsSync(hereAbs)) {
      report(`файл есть у соседа, но отсутствует здесь: ${rel}`, rel)
      continue
    }
    if (!fs.existsSync(thereAbs)) {
      report(`файл есть здесь, но отсутствует у соседа: ${rel}`, rel)
      continue
    }
    if (mode === "presence") {
      checked++
      continue
    }
    if (mode === "version") {
      const hereHost = hostFileFor(rel, root)
      const thereHost = hostFileFor(rel, otherRoot)
      if (!hereHost || !thereHost) {
        report(`не найден хостовый файл версии: ${rel}`, rel)
        continue
      }
      for (const message of compareVersions(hereHost, thereHost, rel)) report(message, rel)
      checked++
      continue
    }
    const a = normalize(fs.readFileSync(hereAbs, "utf8"))
    const b = normalize(fs.readFileSync(thereAbs, "utf8"))
    if (a !== b) {
      report(`hash mismatch: файл изменён без поднятия версии: ${rel}`, rel)
    }
    if (entry.version) {
      for (const message of compareVersions(hereAbs, thereAbs, rel)) report(message, rel)
    }
    checked++
  }

  if (strict) {
    const errors = problems.map((problem) => problem.message)
    return {
      ok: errors.length === 0,
      errors,
      known: [],
      stale: [],
      problems,
      checked,
      exitCode: errors.length === 0 ? 0 : 1,
    }
  }

  let baseline = null
  if (baselinePath) {
    const loaded = loadBaseline(baselinePath)
    if (loaded.error) {
      return {
        ok: false,
        errors: [loaded.error],
        known: [],
        stale: [],
        problems,
        checked,
        exitCode: 2,
      }
    }
    baseline = loaded.entries
  }

  const errors = []
  const known = []
  const used = new Set()
  for (const problem of problems) {
    const reason = problem.kind === "discrepancy" ? baseline?.get(problem.path) : undefined
    if (reason !== undefined) {
      known.push({ path: problem.path, message: problem.message, reason })
      used.add(problem.path)
      continue
    }
    errors.push(problem.message)
  }
  const stale = baseline ? [...baseline.keys()].filter((rel) => !used.has(rel)) : []

  return {
    ok: errors.length === 0,
    errors,
    known,
    stale,
    problems,
    checked,
    exitCode: errors.length === 0 ? 0 : 1,
  }
}

function main() {
  const { other, root: rootOverride, ifEnabled, baseline, strict } = parseArgs(process.argv.slice(2))
  if (!other) {
    console.error(
      "Использование: node scripts/verify-sync.mjs --other <путь к sibling-проекту> [--root <корень репозитория>] [--baseline <файл>] [--strict] [--if-enabled]",
    )
    process.exit(2)
  }
  if (ifEnabled) {
    const value = process.env.KTM_SYNCGATE
    if (value === undefined) {
      console.log("Синк-гейт отключён (KTM_SYNCGATE не установлен).")
      process.exit(0)
    }
    const normalized = value.trim().toLowerCase()
    if (!ENABLED_VALUES.has(normalized)) {
      console.error(
        `Недопустимое значение KTM_SYNCGATE=${JSON.stringify(value)}. Используйте одно из: 1, true, yes, on.`,
      )
      process.exit(2)
    }
  }
  const root = rootOverride
    ? path.resolve(rootOverride)
    : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
  const otherRoot = path.resolve(root, other)
  if (!fs.existsSync(otherRoot)) {
    console.error(
      `sibling-проект не найден: ${otherRoot}. Проверка идёт из корня клона, где сосед существует (локально — ../hrms, в CI — отдельный checkout).`,
    )
    process.exit(2)
  }
  const baselinePath = baseline ? path.resolve(root, baseline) : null
  const result = run({ root, otherRoot, baselinePath, strict })
  for (const item of result.known) console.log(`known: ${item.path} — ${item.reason} (${item.message})`)
  for (const rel of result.stale) console.log(`stale: ${rel} — запись baseline больше не нужна`)
  for (const error of result.errors) console.error(error)
  if (result.ok) {
    const knownNote = result.known.length ? `, ${result.known.length} известных по baseline` : ""
    console.log(
      `Синк-гейт пройден: ${result.checked} файлов совпадают (${path.basename(otherRoot)})${knownNote}.`,
    )
    process.exit(0)
  }
  console.error("Синк-гейт НЕ пройден.")
  process.exit(result.exitCode ?? 1)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main()
}
