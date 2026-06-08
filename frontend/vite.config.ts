import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // Serve from a sub-path when needed (GitHub Pages project sites live under
  // /<repo>/). Set VITE_BASE at build time; defaults to '/' for local + Docker.
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
  server: {
    watch: {
      usePolling: true, // 確保 Windows / WSL2 的檔案變更監聽正常
    },
    host: '0.0.0.0',    // 允許 Docker 容器外（你的 Windows 瀏覽器）連線
    port: 5173,
  },
})