/**
 * Ensure KTM2000 local dev ports are free before npm run dev.
 *
 * Ports: 8012 (backend), 5172 (Vite frontend).
 *
 * Usage:
 *   node scripts/ensure-dev-ports.js           # interactive if TTY; else fail if busy
 *   node scripts/ensure-dev-ports.js --kill    # kill without prompt; --check skips the Docker step
 *   node scripts/ensure-dev-ports.js --check   # report only; exit 1 if busy
 *   KTM_DEV_KILL=1                             # same as --kill
 *
 * Safety: LISTENING only; skips PID 0–4 and own PID; process tree kill on Windows; protects Docker processes.
 */

"use strict";

const { execFileSync, spawnSync } = require("child_process");
const readline = require("readline");
const os = require("os");

const DEFAULT_PORTS = [8012, 5172];

/** Порты заданы явно (`--ports`) — значит, это не дев-стек. */
function isDefaultPorts(ports) {
  return (
    ports.length === DEFAULT_PORTS.length &&
    ports.every((p, i) => p === DEFAULT_PORTS[i])
  );
}
const isWin = process.platform === "win32";

function parseArgs(argv) {
  const forceKill =
    argv.includes("--kill") ||
    argv.includes("--force") ||
    argv.includes("-y") ||
    process.env.KTM_DEV_KILL === "1" ||
    process.env.KTM_DEV_KILL === "true" ||
    process.env.HRMS_DEV_KILL === "1" ||
    process.env.HRMS_DEV_KILL === "true";
  const checkOnly = argv.includes("--check");
  const ports = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--ports" && argv[i + 1]) {
      ports.push(
        ...argv[i + 1]
          .split(",")
          .map((p) => Number(p.trim()))
          .filter((n) => Number.isFinite(n) && n > 0)
      );
      i++;
    }
  }
  return {
    forceKill,
    checkOnly,
    ports: ports.length ? ports : DEFAULT_PORTS,
  };
}

function run(cmd, args, opts = {}) {
  try {
    return execFileSync(cmd, args, {
      encoding: "utf8",
      windowsHide: true,
      ...opts,
    });
  } catch (err) {
    if (err && typeof err.stdout === "string") return err.stdout;
    return "";
  }
}

/** @returns {Map<number, {pid: number, addr: string}[]>} port -> listening sockets */
function listeningSnapshot(ports) {
  /** @type {Map<number, {pid: number, addr: string}[]>} */
  const map = new Map();
  for (const port of ports) map.set(port, []);

  if (isWin) {
    // netstat -ano: TCP  0.0.0.0:8010  0.0.0.0:0  LISTENING  12345
    const out = run("cmd.exe", ["/d", "/s", "/c", "netstat -ano"]);
    for (const line of out.split(/\r?\n/)) {
      if (!/LISTENING/i.test(line)) continue;
      const parts = line.trim().split(/\s+/);
      if (parts.length < 5) continue;
      const local = parts[1] || "";
      const state = parts[parts.length - 2] || "";
      const pidStr = parts[parts.length - 1] || "";
      if (!/LISTENING/i.test(state)) continue;
      const idx = local.lastIndexOf(":");
      if (idx < 0) continue;
      const port = Number(local.slice(idx + 1));
      const pid = Number(pidStr);
      if (!map.has(port) || !Number.isFinite(pid)) continue;
      map.get(port).push({ pid, addr: local.slice(0, idx) || "0.0.0.0" });
    }
  } else {
    for (const port of ports) {
      // lsof -ti :PORT  (PIDs only)
      const out = run("sh", ["-c", `lsof -tiTCP:${port} -sTCP:LISTEN 2>/dev/null || true`]);
      for (const line of out.split(/\r?\n/)) {
        const pid = Number(line.trim());
        if (Number.isFinite(pid) && pid > 0) map.get(port).push({ pid, addr: "" });
      }
    }
  }

  return map;
}

/** @returns {Map<number, Set<number>>} port -> set of PIDs */
function pidsFromSnapshot(snapshot) {
  const map = new Map();
  for (const [port, sockets] of snapshot) {
    map.set(port, new Set(sockets.map((s) => s.pid)));
  }
  return map;
}

const LOOPBACK_ADDRS = new Set(["127.0.0.1", "::1", "[::1]"]);

/**
 * Порты, которые слушает только loopback: снаружи (по LAN-IP) они недоступны,
 * поэтому страница «не найдена», хотя localhost отвечает.
 * @param {Map<number, {pid: number, addr: string}[]>} snapshot
 */
function loopbackOnlyPorts(snapshot) {
  const result = [];
  for (const [port, sockets] of snapshot) {
    if (sockets.length === 0) continue;
    if (sockets.every((s) => LOOPBACK_ADDRS.has(s.addr))) result.push(port);
  }
  return result;
}

/** @param {Map<number, {pid: number, addr: string}[]>} snapshot */
function addressesFor(snapshot, port, pid) {
  return [...new Set(snapshot.get(port)?.filter((s) => s.pid === pid).map((s) => s.addr))].filter(
    Boolean,
  );
}

function processInfo(pid) {
  if (!Number.isFinite(pid) || pid <= 4) {
    return { pid, name: "(system)", cmd: "", alive: true };
  }
  if (isWin) {
    let name = "unknown";
    let cmd = "";
    let alive = true;
    try {
      const tl = run("tasklist.exe", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"]);
      const m = tl.match(/"([^"]+)","(\d+)"/);
      if (m && Number(m[2]) === pid) name = m[1];
      else alive = false;
    } catch {
      /* ignore */
    }
    try {
      const ps = run("powershell.exe", [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}").CommandLine`,
      ]);
      cmd = (ps || "").trim().replace(/\s+/g, " ");
      if (cmd.length > 160) cmd = cmd.slice(0, 157) + "...";
    } catch {
      /* ignore */
    }
    return { pid, name, cmd, alive };
  }
  let name = "unknown";
  let cmd = "";
  let alive = true;
  try {
    name = run("ps", ["-p", String(pid), "-o", "comm="]).trim() || name;
    cmd = run("ps", ["-p", String(pid), "-o", "args="]).trim();
    if (cmd.length > 160) cmd = cmd.slice(0, 157) + "...";
  } catch {
    /* ignore */
  }
  if (!name || name === "unknown") alive = false;
  return { pid, name, cmd, alive };
}

function isDockerProcess(info) {
  const name = (info.name || "").toLowerCase();
  const cmd = (info.cmd || "").toLowerCase();
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
 * Снимок процессов Windows: pid -> {name, cmd, parent}.
 * Нужен для случая, когда владелец listening-сокета из netstat уже мёртв:
 * сокет унаследован живым сиротой (uvicorn-worker пережил свой dev_server.py),
 * и taskkill по «мёртвому» PID порт не освобождает.
 * @returns {Map<number, {name: string, cmd: string, parent: number}>}
 */
function winProcessTable() {
  if (!isWin) return new Map();
  const raw = run("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress",
  ]);
  let data = [];
  try {
    data = JSON.parse((raw || "").trim() || "[]");
  } catch {
    return new Map();
  }
  if (!Array.isArray(data)) data = [data];
  const table = new Map();
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
 * Хосты консолей и оболочки. Ребёнком мёртвого процесса они числятся по
 * inheritance, но держать унаследованный сокет не могут, а убивать их нельзя:
 * это чужое окно терминала пользователя.
 * @param {string} name
 */
function isShellHost(name) {
  return /^(conhost|openconsole|windowsterminal|powershell|pwsh|cmd|explorer)\.exe$/i.test(
    String(name || ""),
  );
}

function collectOccupants(portMap) {
  /** @type {{ port: number, pid: number, name: string, cmd: string, isDocker: boolean, alive: boolean, heirs: number[] }[]} */
  const rows = [];
  const seen = new Set();
  for (const [port, pids] of portMap) {
    for (const pid of pids) {
      if (pid <= 4 || pid === process.pid) continue;
      const key = `${port}:${pid}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const info = processInfo(pid);
      const isDocker = isDockerProcess(info);
      rows.push({ port, pid, name: info.name, cmd: info.cmd, isDocker, alive: info.alive, heirs: [] });
    }
  }

  // Мёртвый PID в netstat при живом порте = сокет унаследован сиротой. Такого
  // сироту (например, uvicorn-worker, переживший dev_server.py) скрипт раньше
  // не видел и уходил с «kill не сработает», хотя порт освобождается тривиально.
  const table = rows.some((r) => !r.alive) ? winProcessTable() : new Map();
  for (const row of rows) {
    if (row.alive || table.size === 0) continue;
    for (const heir of orphanHeirs(table, row.pid)) {
      const info = table.get(heir) || { name: "unknown", cmd: "" };
      if (isShellHost(info.name)) continue;
      const key = `${row.port}:${heir}`;
      if (seen.has(key)) continue;
      seen.add(key);
      row.heirs.push(heir);
      rows.push({
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
  return rows;
}

function killTree(pid) {
  if (!Number.isFinite(pid) || pid <= 4 || pid === process.pid) return false;
  if (isWin) {
    const r = spawnSync("taskkill.exe", ["/F", "/T", "/PID", String(pid)], {
      encoding: "utf8",
      windowsHide: true,
    });
    return r.status === 0 || r.status === 128;
  }
  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      /* ignore */
    }
  }
  const deadline = Date.now() + 1500;
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    } catch {
      return true;
    }
  }
  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      /* ignore */
    }
  }
  return true;
}

function sleepMs(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      /* spin */
    }
  }
}

function printOccupants(rows, snapshot) {
  console.log("");
  console.log("⚠  Ports already in use (LISTENING):");
  console.log("   (old uvicorn/vite orphans cause WinError 10048 / EADDRINUSE and stale API)");
  console.log("");
  for (const row of rows) {
    const addrs = addressesFor(snapshot, row.port, row.pid);
    const bind = addrs.length > 0 ? ` [${addrs.join(", ")}]` : "";
    if (row.isDocker) {
      console.log(`   :${row.port}${bind}  PID ${row.pid}  ${row.name} [DOCKER - PROTECTED]`);
      if (row.cmd) console.log(`           ${row.cmd}`);
      console.log(`           ℹ Docker process detected — skipping kill to protect Docker Desktop.`);
    } else {
      console.log(`   :${row.port}${bind}  PID ${row.pid}  ${row.name}`);
      if (row.cmd) console.log(`           ${row.cmd}`);
      if (!row.alive) {
        if (row.heirs.length > 0) {
          console.log(
            `           ℹ PID ${row.pid} мёртв — сокет унаследован сиротой PID ${row.heirs.join(", ")}.`,
          );
        } else {
          console.log(
            `           ℹ PID ${row.pid} не виден в списке процессов (другая сессия/WSL/Hyper-V):`,
          );
          console.log(`           kill по нему не сработает. Освободить порт вручную или перезапустите стенд.`);
        }
      }
    }
  }
  for (const port of loopbackOnlyPorts(snapshot)) {
    console.log("");
    console.log(`⚠ :${port} слушает только loopback (127.0.0.1).`);
    console.log(`   localhost:${port} отвечает, а http://<LAN-IP>:${port}/ — нет: снаружи это`);
    console.log(`   выглядит как «страница не найдена». Нужен запуск с --host 0.0.0.0.`);
  }
  console.log("");
}

function askYesNo(question) {
  return new Promise((resolve) => {
    if (!process.stdin.isTTY || !process.stdout.isTTY) {
      resolve(false);
      return;
    }
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(question, (answer) => {
      rl.close();
      const a = String(answer || "").trim().toLowerCase();
      // Pressing Enter (empty string) defaults to YES (true). Also accepts y/yes/д/да.
      resolve(a === "" || a === "y" || a === "yes" || a === "д" || a === "да");
    });
  });
}

function isDockerDaemonReady() {
  try {
    const r = spawnSync("docker", ["info"], {
      encoding: "utf8",
      timeout: 4000,
      windowsHide: true,
    });
    return r.status === 0;
  } catch {
    return false;
  }
}

function startDockerDesktop() {
  if (isWin) {
    const exePath = "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe";
    try {
      spawnSync(
        "powershell.exe",
        [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          `if (Test-Path '${exePath}') { Start-Process '${exePath}' } else { Start-Process 'Docker Desktop' }`,
        ],
        { windowsHide: true }
      );
      return true;
    } catch {
      return false;
    }
  } else if (process.platform === "darwin") {
    try {
      spawnSync("open", ["-a", "Docker"]);
      return true;
    } catch {
      return false;
    }
  } else {
    try {
      spawnSync("sudo", ["systemctl", "start", "docker"]);
      return true;
    } catch {
      return false;
    }
  }
}

function ensureDockerRunning(maxWaitSeconds = 45) {
  if (isDockerDaemonReady()) {
    return true;
  }

  console.log("⚠ Docker daemon is not responding. Launching Docker Desktop...");
  startDockerDesktop();

  const startTime = Date.now();
  const timeoutMs = maxWaitSeconds * 1000;

  while (Date.now() - startTime < timeoutMs) {
    sleepMs(2500);
    if (isDockerDaemonReady()) {
      console.log("\n✓ Docker Desktop is ready.");
      return true;
    }
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    process.stdout.write(`   Waiting for Docker daemon to initialize... (${elapsed}s)\r`);
  }

  console.log("");
  console.error("✗ Docker daemon did not respond within timeout. Please check Docker Desktop.");
  return false;
}

async function main() {
  const { forceKill, checkOnly, ports } = parseArgs(process.argv.slice(2));

  let snapshot = listeningSnapshot(ports);
  let portMap = pidsFromSnapshot(snapshot);
  let rows = collectOccupants(portMap);

  if (rows.length > 0) {
    printOccupants(rows, snapshot);

    const killableRows = rows.filter((r) => !r.isDocker);

    // Подсказка обязана совпадать с тем, что реально будет убито: `npm run
    // dev:kill` жмёт по 8012/5172, а для любых других портов (в т.ч. портов
    // стенда E2E, доставленных прогону) он бессмыслен — там нужен явный
    // `--ports` с теми же номерами.
    const killHint = isDefaultPorts(ports)
      ? "npm run dev:kill   or   KTM_DEV_KILL=1 npm run dev"
      : `node scripts/ensure-dev-ports.js --kill --ports ${ports.join(",")}`;

    if (checkOnly && killableRows.length > 0) {
      console.log(`Use: ${killHint}`);
      process.exit(1);
    }

    if (killableRows.length > 0) {
      let shouldKill = forceKill;
      if (!shouldKill) {
        if (process.stdin.isTTY && process.stdout.isTTY) {
          const promptMsg = `Kill non-Docker processes (${killableRows.length} tree(s)) and continue? [Y/n] (Press Enter for Yes): `;
          shouldKill = await askYesNo(promptMsg);
          if (!shouldKill) {
            console.error(`Aborted. Free ports manually or run: ${killHint}`);
            process.exit(1);
          }
        } else {
          console.error(
            "Non-interactive shell: ports busy. Run " + killHint + " or set KTM_DEV_KILL=1"
          );
          process.exit(1);
        }
      }

      const uniquePids = [...new Set(killableRows.filter((r) => r.alive).map((r) => r.pid))];
      console.log(`Killing ${uniquePids.length} process tree(s) (Docker processes excluded)...`);
      for (const pid of uniquePids) {
        const ok = killTree(pid);
        console.log(ok ? `  ✓ tree PID ${pid}` : `  ✗ failed PID ${pid}`);
      }

      sleepMs(800);
      snapshot = listeningSnapshot(ports);
      portMap = pidsFromSnapshot(snapshot);
      rows = collectOccupants(portMap);
      const remainingKillable = rows.filter((r) => !r.isDocker);

      if (remainingKillable.length > 0) {
        console.log("Still busy after kill — second pass...");
        for (const pid of new Set(remainingKillable.filter((r) => r.alive).map((r) => r.pid))) {
          killTree(pid);
        }
        sleepMs(500);
        snapshot = listeningSnapshot(ports);
        portMap = pidsFromSnapshot(snapshot);
        rows = collectOccupants(portMap);
      }

      const finalKillable = rows.filter((r) => !r.isDocker);
      if (finalKillable.length > 0) {
        printOccupants(finalKillable, snapshot);
        console.error(
          "✗ Could not free all dev ports from non-Docker processes. Close them manually and retry."
        );
        process.exit(1);
      }
    }
  }

  console.log(`✓ Ports free: ${ports.map((p) => ":" + p).join(", ")}`);

  // Раньше здесь был флаг --no-docker («убить порты, но не трогать Docker»)
  // вместе с skipDocker. Он удалён: вызывающих нет ни в npm-скриптах, ни в
  // e2e/global-teardown.ts (уборка после прогона режет осиротевшие браузеры
  // сама, порты не трогает), а сам флаг в неинтерактивном шелле не делал
  // обещанного — не выставлял forceKill, поэтому упирался в отказ по занятым
  // портам вместо kill. Пропуск шага Docker теперь покрывает --check.

  if (!checkOnly) {
    const dockerOk = ensureDockerRunning();
    if (!dockerOk) process.exit(1);
  }

  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
