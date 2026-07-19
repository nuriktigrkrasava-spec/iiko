import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Фронт функционального демо-сайта ходит в живой FastAPI-бэкенд (api.py) на :8000.
// Прокси убирает CORS-боль: /api/* → localhost:8000/api/*
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    proxy: {
      // ИИ-слой аналитики — отдельный сервис (:8010). Правило выше общего /api.
      '/api/insights': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    css: false,
  },
})
