import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// M2-03 本地工作台：前端只访问同源 /api，由 Vite 代理到唯一业务后端。
// 验收实例跑在 8004 时用 VITE_PROXY_TARGET 覆盖，默认仍指向标准端口 8000。
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
