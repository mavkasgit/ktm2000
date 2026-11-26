/**
 * Запуск Vite с портом, который выбрал `playwright.config.mjs` (свободный
 * порт ОС на этот прогон). Отдельный скрипт нужен, чтобы Playwright мог
 * поднять `webServer` на уже известном URL.
 */
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const port = Number(process.argv[2]);
if (!Number.isInteger(port) || port <= 0) {
  throw new Error(`serve.mjs: нужен порт, получено ${process.argv[2]}`);
}

const server = await createServer({
  configFile: fileURLToPath(new URL("./vite.config.mjs", import.meta.url)),
  server: { host: "127.0.0.1", port, strictPort: true },
});

await server.listen();
server.printUrls();

const close = async () => {
  await server.close();
  process.exit(0);
};
process.on("SIGINT", close);
process.on("SIGTERM", close);
