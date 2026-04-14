/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/demo": {
        target: "http://localhost:8000",
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
