/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Windows Docker Desktop 下 inotify 不穿透到容器,必须走 polling 才能
    // 监听到 host 文件变更(代价:容器内每秒轮询文件系统 → 微量 CPU)。
    watch: {
      usePolling: true,
      interval: 500,
    },
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET ?? `http://localhost:${process.env.BACKEND_PORT ?? "8001"}`,
        changeOrigin: true,
      },
      "/demo": {
        target: process.env.VITE_PROXY_TARGET ?? `http://localhost:${process.env.BACKEND_PORT ?? "8001"}`,
        changeOrigin: true,
        // 浏览器导航(Accept: text/html)到 /demo/sse 时,让前端 React 路由处理;
        // EventSource 请求(Accept: text/event-stream)才真正代理到后端 SSE 端点。
        bypass: (req) => {
          if (req.headers.accept?.includes("text/html")) {
            return req.url;
          }
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
})
