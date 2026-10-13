import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  clearScreen: false,
  build: {
    rollupOptions: {
      output: {
        // Keep the reusable editor/runtime modules independently cacheable.
        // This also avoids giant single-chunk transforms on Windows hosts.
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return
          if (id.includes('prosemirror-') || id.includes('@tiptap/pm')) return 'editor-prosemirror'
          if (id.includes('@tiptap/')) return 'editor-tiptap'
          if (id.includes('/@vue/') || id.includes('/vue/')) return 'vue-runtime'
        },
      },
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    host: '127.0.0.1',
    proxy: { '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true } },
  },
  envPrefix: ['VITE_', 'TAURI_'],
})
