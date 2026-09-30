import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: '127.0.0.1',
    proxy: { '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true } },
  },
  envPrefix: ['VITE_', 'TAURI_'],
})
