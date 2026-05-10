import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { fileURLToPath, URL } from "node:url"

const proxyTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8010"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      shared: fileURLToPath(new URL("./src/shared", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5180,
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
