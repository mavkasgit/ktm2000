import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { fileURLToPath, URL } from "node:url"

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
    port: 5200,
    proxy: {
      "/api": {
        target: "http://localhost:5201",
        changeOrigin: true,
      },
      "/static": {
        target: "http://localhost:5201",
        changeOrigin: true,
      },
    },
  },
})
