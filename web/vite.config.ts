import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Development only: same-origin /api avoids CORS. In production the
      // built frontend is served by FastAPI itself (see server/app.py).
      '/api': { target: BACKEND, changeOrigin: true },
    },
  },
})
