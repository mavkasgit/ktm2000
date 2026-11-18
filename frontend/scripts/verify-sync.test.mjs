import { afterEach, describe, expect, it } from "vitest"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import {
  NO_LOCAL_HASH,
  SYNC_VERSION,
  extractVersions,
  hashContent,
  normalize,
  parseArgs,
  run,
} from "../../scripts/verify-sync.mjs"

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const SCRIPT = path.join(REPO_ROOT, "scripts/verify-sync.mjs")

function envWithoutSyncgate() {
  const env = { ...process.env }
  delete env.KTM_SYNCGATE
  return env
}

const tempDirs = []

function makeTree(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "verify-sync-"))
  tempDirs.push(dir)
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel)
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, content)
  }
  return dir
}

afterEach(() => {
  while (tempDirs.length) fs.rmSync(tempDirs.pop(), { recursive: true, force: true })
})

const HOST = `export const DEMO_VERSION = "1.2.3"\n`
const SELF = `export const SYNC_VERSION = "${SYNC_VERSION}"\nconsole.log("ok")\n`

function manifest(files) {
  return JSON.stringify({ version: "1.0.0", files }, null, 2)
}

const BASE_MANIFEST = manifest([
  { path: "shared/file.txt", mode: "content" },
  { path: "mod/index.ts", mode: "version" },
  { path: "host/ui.ts", mode: "presence" },
  { path: "scripts/verify-sync.mjs", mode: "content", version: true },
  { path: "scripts/sync-manifest.json", mode: "content", version: true },
])

function baseTree() {
  return {
    "shared/file.txt": "общий файл\n",
    "mod/index.ts": HOST,
    "host/ui.ts": "хост: содержимое может отличаться\n",
    "scripts/verify-sync.mjs": SELF,
    "scripts/sync-manifest.json": BASE_MANIFEST,
  }
}

describe("verify-sync.mjs", () => {
  it("normalize игнорирует CRLF", () => {
    expect(normalize("a\r\nb\rc\n")).toBe("a\nb\nc\n")
  })

  it("parseArgs извлекает --other, --root, --if-enabled, --baseline, --strict, --optional и --update-baseline", () => {
    const defaults = { optional: false, updateBaseline: false }
    expect(parseArgs(["node", "x", "--other", "../hrms"])).toEqual({
      other: "../hrms",
      root: null,
      ifEnabled: false,
      baseline: null,
      strict: false,
      ...defaults,
    })
    expect(parseArgs(["node", "x", "--root", "/tmp/a", "--other", "../hrms", "--if-enabled"])).toEqual({
      other: "../hrms",
      root: "/tmp/a",
      ifEnabled: true,
      baseline: null,
      strict: false,
      ...defaults,
    })
    expect(
      parseArgs([
        "node",
        "x",
        "--other",
        "../hrms",
        "--baseline",
        "scripts/sync-baseline.json",
        "--strict",
      ]),
    ).toEqual({
      other: "../hrms",
      root: null,
      ifEnabled: false,
      baseline: "scripts/sync-baseline.json",
      strict: true,
      ...defaults,
    })
    expect(parseArgs(["node", "x", "--other", "../hrms", "--optional"])).toEqual({
      other: "../hrms",
      root: null,
      ifEnabled: false,
      baseline: null,
      strict: false,
      optional: true,
      updateBaseline: false,
    })
    expect(parseArgs(["node", "x", "--other", "../hrms", "--skip-if-missing"])).toMatchObject({
      optional: true,
    })
    expect(parseArgs(["node", "x", "--other", "../hrms", "--update-baseline"])).toMatchObject({
      updateBaseline: true,
    })
    expect(parseArgs([])).toEqual({
      other: null,
      root: null,
      ifEnabled: false,
      baseline: null,
      strict: false,
      ...defaults,
    })
  })

  it("--if-enabled без KTM_SYNCGATE пропускает проверку", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
      { cwd: root, encoding: "utf8", env: envWithoutSyncgate() },
    )

    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("Синк-гейт отключён")
    expect(spawned.stdout).not.toContain("Синк-гейт пройден")
  })

  it.each(["1", "TrUe", "YeS", "oN"])(
    "--if-enabled с KTM_SYNCGATE=%s выполняет проверку независимо от регистра",
    (value) => {
      const root = makeTree(baseTree())
      const otherTree = baseTree()
      otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
      const other = makeTree(otherTree)
      const spawned = spawnSync(
        process.execPath,
        [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
        { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: value } },
      )

      expect(spawned.status).toBe(1)
      expect(spawned.stderr).toContain("version mismatch")
    },
  )

  it("--if-enabled с недопустимым KTM_SYNCGATE завершается с кодом 2", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other, "--if-enabled"],
      { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: "maybe" } },
    )

    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("1, true, yes, on")
  })

  it("ручной режим игнорирует KTM_SYNCGATE", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)
    const spawned = spawnSync(
      process.execPath,
      [SCRIPT, "--root", root, "--other", other],
      { cwd: root, encoding: "utf8", env: { ...process.env, KTM_SYNCGATE: "maybe" } },
    )

    expect(spawned.status).toBe(1)
    expect(spawned.stderr).toContain("version mismatch")
  })

  it("extractVersions читает *_VERSION и version из JSON", () => {
    const content = 'export const FOO_VERSION = "2.0.0"\nexport const BAR_VERSION = "1.0.0"\n'
    expect(extractVersions(content, "index.ts")).toEqual(
      new Map([
        ["FOO_VERSION", "2.0.0"],
        ["BAR_VERSION", "1.0.0"],
      ]),
    )
    expect(extractVersions('{ "version": "3.0.0" }', "manifest.json").get("version")).toBe("3.0.0")
  })

  it("match → ok (exit 0)", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.checked).toBe(5)

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(0)
  })

  it("version-mismatch → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("version mismatch")
    expect(result.errors.join("\n")).toContain("ожидалось 1.2.3")
    expect(result.errors.join("\n")).toContain("у соседа 9.9.9")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("hash-mismatch → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("hash mismatch")
    expect(result.errors.join("\n")).toContain("изменён без поднятия версии")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("self-check: расхождение verify-sync.mjs/манифеста тоже валит (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["scripts/verify-sync.mjs"] = 'export const SYNC_VERSION = "0.9.0"\nconsole.log("edited")\n'
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("hash mismatch")
    expect(result.errors.join("\n")).toContain("version mismatch")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", other], { cwd: root })
    expect(spawned.status).toBe(1)
  })

  it("version mode поддерживает хостовый файл директории (index.*)", () => {
    const files = baseTree()
    files["scripts/sync-manifest.json"] = manifest([
      { path: "mod", mode: "version" },
      { path: "scripts/verify-sync.mjs", mode: "content", version: true },
      { path: "scripts/sync-manifest.json", mode: "content", version: true },
    ])
    const root = makeTree(files)
    const otherTree = { ...files }
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("version mismatch")
  })

  it("неизвестный mode → fail", () => {
    const files = baseTree()
    files["scripts/sync-manifest.json"] = manifest([{ path: "mod/index.ts", mode: "checksum" }])
    const root = makeTree(files)
    const other = makeTree(files)
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("неизвестный режим")
  })

  it("пустой манифест без files → fail", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    fs.writeFileSync(path.join(root, "scripts/sync-manifest.json"), JSON.stringify({ version: "1.0.0" }))
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("не содержит files")
  })

  it("version mode без констант *_VERSION → fail", () => {
    const files = baseTree()
    files["mod/index.ts"] = "export const PI = 3.14\n"
    files["scripts/sync-manifest.json"] = manifest([{ path: "mod/index.ts", mode: "version" }])
    const root = makeTree(files)
    const otherTree = { ...files }
    otherTree["mod/index.ts"] = "export const PI = 3.14\nexport const E = 2.71\n"
    const other = makeTree(otherTree)
    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("не найдены константы *_VERSION")
  })

  it("отсутствующий файл у соседа → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    delete otherTree["mod/index.ts"]
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("отсутствует у соседа")
  })

  it("presence mode: содержимое может различаться, файл обязан существовать", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["host/ui.ts"] = "другой хост: свои импорты\n"
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.checked).toBe(5)
  })

  it("presence mode: отсутствующий файл → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    delete otherTree["host/ui.ts"]
    const other = makeTree(otherTree)

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("файл есть здесь, но отсутствует у соседа")
  })

  it("presence mode: файл есть у соседа, но отсутствует здесь → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    const other = makeTree(otherTree)
    fs.unlinkSync(path.join(root, "host/ui.ts"))

    const result = run({ root, otherRoot: other })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("файл есть у соседа, но отсутствует здесь")
  })
})

const BASELINE = "scripts/sync-baseline.json"
const VALID_HASH = "a".repeat(64)

function writeBaseline(root, entries) {
  const abs = path.join(root, BASELINE)
  fs.mkdirSync(path.dirname(abs), { recursive: true })
  fs.writeFileSync(
    abs,
    typeof entries === "string" ? entries : JSON.stringify({ version: 2, entries }, null, 2),
  )
}

/**
 * Запись снимка с фактами: kind + hash локального файла на момент снимка.
 * hash можно передать руками (например, для записи, которой файла уже нет).
 */
function baselineEntry(
  root,
  rel,
  { kind = "content", hash, reason = "auth/OIDC debt (ADR/spec: retro 2026-11-18)" } = {},
) {
  const abs = path.join(root, rel)
  let resolved = hash
  if (resolved === undefined) {
    resolved =
      fs.existsSync(abs) && fs.statSync(abs).isFile()
        ? hashContent(fs.readFileSync(abs, "utf8"))
        : NO_LOCAL_HASH
  }
  return { path: rel, kind, hash: resolved, reason, reviewed: "2026-11-18", expires: "2027-06-30" }
}

function runCli(root, other, extra = []) {
  return spawnSync(
    process.execPath,
    [SCRIPT, "--root", root, "--other", other, "--baseline", BASELINE, ...extra],
    { cwd: root, encoding: "utf8" },
  )
}

describe("verify-sync.mjs: baseline", () => {
  it("известное расхождение подавляется и печатается как known (exit 0)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    writeBaseline(root, [baselineEntry(root, "shared/file.txt")])

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.known.map((k) => k.path)).toEqual(["shared/file.txt"])
    expect(result.known[0].kind).toBe("content")

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("known")
    expect(spawned.stdout).toContain("shared/file.txt [content]")
    expect(spawned.stdout).toContain("Синк-гейт пройден")
  })

  it("новое расхождение вне baseline → fail, подавленное не мешает", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    otherTree["mod/index.ts"] = `export const DEMO_VERSION = "9.9.9"\n`
    const other = makeTree(otherTree)
    writeBaseline(root, [baselineEntry(root, "shared/file.txt")])

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(false)
    expect(result.known.map((k) => k.path)).toEqual(["shared/file.txt"])
    expect(result.errors.join("\n")).toContain("mod/index.ts")
    expect(result.errors.join("\n")).not.toContain("shared/file.txt")

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(1)
    expect(spawned.stderr).toContain("mod/index.ts")
  })

  it("новое ухудшение на известном пути (локальный файл изменился) → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    writeBaseline(root, [baselineEntry(root, "shared/file.txt")])
    // Снимок сделан на текущем содержимом; дальше локальный файл правится —
    // ровно сценарий ревью: правка useAuth.tsx не должна проходить зелёной.
    fs.writeFileSync(path.join(root, "shared/file.txt"), "локальная правка поверх долга\n")

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("shared/file.txt")
    expect(result.errors.join("\n")).toContain("изменился с момента снимка baseline")
    // Это не stale: запись с тем же path+kind есть, изменился только снимок.
    expect(result.stale).toEqual([])

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(1)
    expect(spawned.stderr).toContain("--update-baseline")
  })

  it("missing-there: запись с hash ловит правку локального файла (useAuth-сценарий) → fail", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    delete otherTree["mod/index.ts"]
    const other = makeTree(otherTree)
    writeBaseline(root, [
      baselineEntry(root, "mod/index.ts", { kind: "missing-there" }),
    ])

    const before = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(before.ok).toBe(true)
    expect(before.known[0].kind).toBe("missing-there")

    fs.appendFileSync(path.join(root, "mod/index.ts"), "// правка\n")
    const after = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(after.ok).toBe(false)
    expect(after.errors.join("\n")).toContain("mod/index.ts")
    expect(after.errors.join("\n")).toContain("изменился с момента снимка baseline")
  })

  it("--strict игнорирует baseline → fail (exit 1)", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    writeBaseline(root, [baselineEntry(root, "shared/file.txt")])

    const result = run({
      root,
      otherRoot: other,
      baselinePath: path.join(root, BASELINE),
      strict: true,
    })
    expect(result.ok).toBe(false)
    expect(result.errors.join("\n")).toContain("shared/file.txt")

    const spawned = runCli(root, other, ["--strict"])
    expect(spawned.status).toBe(1)
  })

  it("неиспользованная запись baseline печатается как stale и не валит (exit 0)", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    writeBaseline(root, [{ ...baselineEntry(root, "shared/file.txt"), reason: "долг закрыт" }])

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("stale")
    expect(spawned.stdout).toContain("shared/file.txt [content]")
  })

  it("--update-baseline пересобирает снимок с kind/hash/датами и сохраняет reason", () => {
    const root = makeTree(baseTree())
    const otherTree = baseTree()
    otherTree["shared/file.txt"] = "изменено без поднятия версии\n"
    const other = makeTree(otherTree)
    // Снимок прежнего формата: причина должна пережить пересборку.
    writeBaseline(root, [
      { path: "shared/file.txt", reason: "auth/OIDC debt (ADR/spec: retro 2026-11-18)" },
    ])

    const updated = runCli(root, other, ["--update-baseline"])
    expect(updated.status).toBe(0)

    const saved = JSON.parse(fs.readFileSync(path.join(root, BASELINE), "utf8"))
    expect(saved.version).toBe(2)
    expect(saved.entries).toHaveLength(1)
    expect(saved.entries[0]).toMatchObject({
      path: "shared/file.txt",
      kind: "content",
      hash: hashContent("общий файл\n"),
      reason: "auth/OIDC debt (ADR/spec: retro 2026-11-18)",
      reviewed: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      expires: "2027-06-30",
    })

    const after = runCli(root, other)
    expect(after.status).toBe(0)
    expect(after.stdout).toContain("known")
  })

  it.each([
    ["отсутствует", null],
    ["не JSON", "{ это не json"],
    ["нет entries", JSON.stringify({ files: [] })],
    ["entries не массив", JSON.stringify({ entries: {} })],
    ["запись без path", JSON.stringify({ entries: [{ reason: "нет пути" }] })],
    [
      "запись без kind",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2026-11-18",
            expires: "2027-06-30",
          },
        ],
      }),
    ],
    [
      "неизвестный kind",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "checksum",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2026-11-18",
            expires: "2027-06-30",
          },
        ],
      }),
    ],
    [
      "hash не sha256",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "content",
            hash: "не-hash",
            reason: "долг",
            reviewed: "2026-11-18",
            expires: "2027-06-30",
          },
        ],
      }),
    ],
    [
      "нет reviewed",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "content",
            hash: VALID_HASH,
            reason: "долг",
            expires: "2027-06-30",
          },
        ],
      }),
    ],
    [
      "нет expires",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "content",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2026-11-18",
          },
        ],
      }),
    ],
    [
      "expires раньше reviewed",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "content",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2027-01-01",
            expires: "2026-01-01",
          },
        ],
      }),
    ],
    [
      "дубль path+kind+hash",
      JSON.stringify({
        entries: [
          {
            path: "shared/file.txt",
            kind: "content",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2026-11-18",
            expires: "2027-06-30",
          },
          {
            path: "shared/file.txt",
            kind: "content",
            hash: VALID_HASH,
            reason: "долг",
            reviewed: "2026-11-18",
            expires: "2027-06-30",
          },
        ],
      }),
    ],
  ])("битый baseline (%s) → exit 2", (_label, content) => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())
    if (content !== null) writeBaseline(root, content)

    const result = run({ root, otherRoot: other, baselinePath: path.join(root, BASELINE) })
    expect(result.ok).toBe(false)
    expect(result.exitCode).toBe(2)

    const spawned = runCli(root, other)
    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("baseline")
  })

  it("--strict не читает baseline: отсутствующий файл не мешает", () => {
    const root = makeTree(baseTree())
    const other = makeTree(baseTree())

    const spawned = runCli(root, other, ["--strict"])
    expect(spawned.status).toBe(0)
  })

  it("отсутствующий sibling-проект → exit 2 с внятной причиной (ручной режим строгий)", () => {
    const root = makeTree(baseTree())
    const missing = path.join(root, "нет-такого-соседа")

    const spawned = spawnSync(process.execPath, [SCRIPT, "--root", root, "--other", missing], {
      cwd: root,
      encoding: "utf8",
    })
    expect(spawned.status).toBe(2)
    expect(spawned.stderr).toContain("sibling-проект не найден")
  })

  it.each(["--optional", "--skip-if-missing"])(
    "отсутствующий sibling-проект с %s → exit 0 и сообщение (pre-push без соседа)",
    (flag) => {
      const root = makeTree(baseTree())
      const missing = path.join(root, "нет-такого-соседа")

      const spawned = spawnSync(
        process.execPath,
        [SCRIPT, "--root", root, "--other", missing, "--baseline", BASELINE, flag],
        { cwd: root, encoding: "utf8" },
      )
      expect(spawned.status).toBe(0)
      expect(spawned.stdout).toContain("Синк-гейт пропущен")
      expect(spawned.stdout).toContain("sibling-проект не найден")
      expect(spawned.stderr).toBe("")
    },
  )
})
