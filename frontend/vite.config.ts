import { writeFileSync } from "node:fs"
import { resolve } from "node:path"
import { fileURLToPath, URL } from "node:url"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

const proxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8012"

function appVersionPlugin(): Plugin {
  let buildId = "dev"
  return {
    name: "app-version",
    config(_config, { command }) {
      buildId = command === "build" ? String(Date.now()) : "dev"
      return {
        define: {
          __APP_BUILD_ID__: JSON.stringify(buildId),
        },
      }
    },
    closeBundle() {
      if (buildId === "dev") return
      const outDir = resolve(fileURLToPath(new URL(".", import.meta.url)), "dist")
      writeFileSync(resolve(outDir, "version.json"), JSON.stringify({ buildId }))
    },
  }
}

export default defineConfig({
  plugins: [react(), appVersionPlugin()],
  resolve: {
    alias: {
      shared: fileURLToPath(new URL("./src/shared", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5172,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
      "/static": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
})
