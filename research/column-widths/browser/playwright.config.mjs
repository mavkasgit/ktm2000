import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const researchRoot = path.resolve(here, "..");

/**
 * Свободный порт у ОС на этот прогон: стенд не делит порт с dev/e2e и не
 * падает, если прошлый осиротевший Vite ещё жив. `strictPort` в serve.mjs
 * гарантирует, что Vite не уедет на другой порт молча.
 *
 * Playwright грузит конфиг и в runner, и в worker-процессах; порт обязан быть
 * одним на прогон, поэтому первый вызов фиксирует его в окружении, а worker
 * наследует `KTM_RESEARCH_BROWSER_PORT` при спавне.
 */
function pickFreePort() {
  if (process.env.KTM_RESEARCH_BROWSER_PORT) {
    return Number(process.env.KTM_RESEARCH_BROWSER_PORT);
  }
  const script =
    "const net=require('node:net');const s=net.createServer();" +
    "s.unref();s.listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close();});";
  const port = Number(
    execFileSync(process.execPath, ["-e", script], { encoding: "utf8" }).trim(),
  );
  process.env.KTM_RESEARCH_BROWSER_PORT = String(port);
  return port;
}

const port = pickFreePort();
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: here,
  testMatch: /(validation|runtime)\.spec\.mjs$/,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1600, height: 1000 },
        deviceScaleFactor: 1,
      },
    },
  ],
  webServer: {
    command: `node browser/serve.mjs ${port}`,
    cwd: researchRoot,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
