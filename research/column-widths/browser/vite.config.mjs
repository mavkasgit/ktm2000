import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const browserDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * Стенд живёт в `research/column-widths/browser/`, но импортирует `../lib/*`.
 * Корень Vite — каталог исследования, `fs.allow` — он же: ничего вне
 * research-песочницы стенд не читает.
 */
export default defineConfig({
  root: browserDir,
  appType: "mpa",
  server: {
    host: "127.0.0.1",
    strictPort: true,
    fs: {
      allow: [path.resolve(browserDir, "..")],
    },
  },
});
