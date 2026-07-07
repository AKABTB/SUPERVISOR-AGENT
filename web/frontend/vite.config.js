import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端构建产物输出到 dist/，由 FastAPI 托管（app.py 的 _FRONTEND_DIST）。
// 开发期 npm run dev：/api 代理到本地跑的 python -m supervisor web（默认 8000）。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
