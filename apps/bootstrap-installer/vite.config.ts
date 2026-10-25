import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { readFileSync } from 'node:fs'

// Luna launcher — shared dashboard styling inside a Tauri window.
//
// Port 5175 keeps us out of the way of:
//   web       (vite default 5173)
//   apps/desktop dev     (5174 per its package.json)
//
// `clearScreen: false` is the Tauri convention — they spawn vite as a child
// process and want our errors to stay visible.

const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  plugins: [react(), tailwindcss(), {
    name: 'luna-font-notices',
    generateBundle() {
      for (const file of ['fonts-luna/Manrope-OFL.txt', 'fonts-luna/DMSerifDisplay-OFL.txt', 'fonts-terminal/JetBrainsMono-OFL.txt']) {
        this.emitFile({ type: 'asset', fileName: `licenses/${path.basename(file)}`, source: readFileSync(path.resolve(__dirname, '../../web/public', file)) })
      }
    }
  }],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '../../web/src')
    }
  },
  clearScreen: false,
  publicDir: false, // The thin Luna screen uses its own inline vector mark.
  server: {
    port: 5175,
    strictPort: true,
    host: host || '127.0.0.1',
    hmr: host
      ? {
          protocol: 'ws',
          host,
          port: 5176
        }
      : undefined,
    watch: {
      // Don't watch the Rust side — tauri-cli handles it.
      ignored: ['**/src-tauri/**']
    }
  },
  build: {
    target: 'esnext',
    outDir: 'dist',
    emptyOutDir: true
  }
})
