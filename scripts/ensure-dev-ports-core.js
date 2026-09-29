/**
 * Чистые детерминированные части scripts/ensure-dev-ports.js.
 *
 * Всё, что не трогает процессы и файловую систему, живёт здесь, чтобы
 * покрыть тестами логику живости PID (разбор снимка процессов, поиск
 * наследников у мёртвого владельца сокета, отсев хостов консолей).
 * CLI-обвязка остаётся в ensure-dev-ports.js.
 */

"use strict";

/** Разбор вывода `Get-CimInstance Win32_Process | ... | ConvertTo-Json -Compress`. */
function parseProcessTable(raw) {
  /** @type {Map<number, {name: string, cmd: string, parent: number}>} */
  const table = new Map();
  let data = [];
  try {
    data = JSON.parse(String(raw || "").trim() || "[]");
  } catch {
    return table;
  }
  if (!Array.isArray(data)) data = [data];
  for (const row of data) {
    const pid = Number(row && row.ProcessId);
    if (!Number.isFinite(pid)) continue;
    const cmd = String((row && row.CommandLine) || "").trim().replace(/\s+/g, " ");
    table.set(pid, {
      name: String((row && row.Name) || "unknown"),
      cmd: cmd.length > 160 ? cmd.slice(0, 157) + "..." : cmd,
      parent: Number(row && row.ParentProcessId) || 0,
    });
  }
  return table;
}

/**
 * Живые потомки мёртвого PID (дети и внуки) — реальные держатели сокета.
 * @param {Map<number, {parent: number}>} table
 * @param {number} deadPid
 * @returns {number[]}
 */
function orphanHeirs(table, deadPid) {
  const heirs = new Set();
  let frontier = [deadPid];
  while (frontier.length > 0) {
    const next = [];
    for (const [pid, info] of table) {
      if (frontier.includes(info.parent) && !heirs.has(pid)) {
        heirs.add(pid);
        next.push(pid);
      }
    }
    frontier = next;
  }
  return [...heirs];
}

/**
 * Хосты консолей и оболочек. Ребёнком мёртвого процесса они числятся по
 * inheritance, но держать унаследованный сокет не могут, а убивать их нельзя:
 * это чужое окно терминала пользователя.
 * @param {string} name
 */
function isShellHost(name) {
  return /^(conhost|openconsole|windowsterminal|powershell|pwsh|cmd|explorer)\.exe$/i.test(
    String(name || ""),
  );
}

/** @param {{name: string, cmd: string}} info */
function isDockerProcess(info) {
  const name = String((info && info.name) || "").toLowerCase();
  const cmd = String((info && info.cmd) || "").toLowerCase();
  return (
    name.includes("docker") ||
    cmd.includes("docker") ||
    name.includes("vmmem") ||
    name.includes("vpnkit") ||
    cmd.includes("vpnkit") ||
    name.includes("wslrelay") ||
    cmd.includes("wslrelay")
  );
}

/**
 * Достраивает строки держателей портов: к мёртвому PID добавляет живых
 * наследников, унаследовавших сокет (например, uvicorn-worker, переживший
 * свой dev_server.py). Возвращает новый массив; исходные строки-владельцы
 * получают заполненный `heirs`.
 *
 * @param {{ port: number, pid: number, name: string, cmd: string, isDocker: boolean, alive: boolean, heirs: number[] }[]} rows
 * @param {Map<number, {name: string, cmd: string, parent: number}>} table
 */
function expandDeadOwners(rows, table) {
  const out = rows.map((row) => ({ ...row, heirs: [...row.heirs] }));
  if (!table || table.size === 0) return out;
  // Наследник, уже присутствующий среди владельцев того же порта, повторно
  // не добавляется — иначе он попал бы в отчёт и в список на убийство дважды.
  const seen = new Set(out.map((row) => `${row.port}:${row.pid}`));
  for (const row of out) {
    if (row.alive) continue;
    for (const heir of orphanHeirs(table, row.pid)) {
      const info = table.get(heir) || { name: "unknown", cmd: "" };
      if (isShellHost(info.name)) continue;
      const key = `${row.port}:${heir}`;
      if (seen.has(key)) continue;
      seen.add(key);
      row.heirs.push(heir);
      out.push({
        port: row.port,
        pid: heir,
        name: info.name,
        cmd: info.cmd,
        isDocker: isDockerProcess(info),
        alive: true,
        heirs: [],
      });
    }
  }
  return out;
}

module.exports = {
  parseProcessTable,
  orphanHeirs,
  isShellHost,
  isDockerProcess,
  expandDeadOwners,
};
