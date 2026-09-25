import { describe, expect, it } from "vitest"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const ENABLED_VALUES = new Set(["1", "true", "yes", "on"])
const syncGateEnabled = ENABLED_VALUES.has((process.env.KTM_SYNCGATE ?? "").trim().toLowerCase())

describe.skipIf(!syncGateEnabled)("verify-sync integration", () => {
  it("реальный запуск --other ../hrms из репозитория → exit 0", () => {
    const spawned = spawnSync(
      process.execPath,
      ["scripts/verify-sync.mjs", "--other", "../hrms"],
      { cwd: REPO_ROOT, encoding: "utf8" },
    )
    expect(spawned.status).toBe(0)
    expect(spawned.stdout).toContain("Синк-гейт пройден")
  })
})
