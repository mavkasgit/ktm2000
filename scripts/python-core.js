"use strict";
// Какой интерпретатор Python берёт гейт (T-384).
//
// `python` из PATH — это чужой интерпретатор в смешанной сессии: 2026-11-19
// `npm run gate` из KTM подхватил python 3.12 из venv соседнего проекта, и шаги
// `pins` и `backend-test-count` покраснели на зелёном дереве. Проектный
// интерпретатор — `backend/.venv` (mise.toml: `_.python.venv`), и он резолвится
// здесь явно, а не первым `python` из PATH.
//
// Порядок:
//   1. `KTM_PYTHON` / `TEST_PYTHON` — осознанный override человека (ночное
//      дерево без своего venv ссылается на venv основного);
//   2. `backend/.venv` проекта — источник правды;
//   3. `python` из PATH — запасной путь дерева без venv, печатается
//      предупреждением: тихий выбор чужого интерпретатора и был предметом
//      тикета.
//
// Модуль намеренно чистый (`exists` и `platform` подставляются), чтобы правило
// проверялось юнит-тестом, а не руками на одной машине.

const { existsSync } = require("node:fs");
const { join } = require("node:path");

/** Путь интерпретатора внутри venv: Windows и POSIX раскладывают его по-разному. */
function venvPython(root, platform = process.platform) {
  return platform === "win32"
    ? join(root, "backend", ".venv", "Scripts", "python.exe")
    : join(root, "backend", ".venv", "bin", "python");
}

/**
 * @param {{ root: string, env?: NodeJS.ProcessEnv, platform?: NodeJS.Platform, exists?: (path: string) => boolean }} options
 * @returns {{ exe: string, source: "env" | "venv" | "path", venv: string }}
 */
function resolvePython({ root, env = process.env, platform = process.platform, exists = existsSync }) {
  const venv = venvPython(root, platform);
  const override = (env.KTM_PYTHON || env.TEST_PYTHON || "").trim();
  if (override) return { exe: override, source: "env", venv };
  if (exists(venv)) return { exe: venv, source: "venv", venv };
  return { exe: "python", source: "path", venv };
}

module.exports = { resolvePython, venvPython };
