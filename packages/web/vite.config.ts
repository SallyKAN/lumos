import type { Plugin } from 'vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

type ConfigWithLogger = { logger?: { error?: (msg: string, opts?: { error?: Error }) => void } }

/** 过滤 Vite 内置的 ws proxy 对 EPIPE/ECONNRESET 的 socket 报错，避免控制台刷屏 */
function suppressWsProxySocketErrors(): Plugin {
  return {
    name: 'suppress-ws-proxy-socket-errors',
    config(config) {
      const logger = (config as ConfigWithLogger).logger
      if (!logger?.error) return
      const orig = logger.error.bind(logger)
      logger.error = (msg: string, opts?: unknown) => {
        if (typeof msg === 'string' && msg.includes('ws proxy socket error')) {
          const code = (opts as { error?: NodeJS.ErrnoException } | undefined)?.error?.code
          if (code === 'EPIPE' || code === 'ECONNRESET') return
        }
        orig(msg, opts as { error?: Error } | undefined)
      }
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [suppressWsProxySocketErrors(), react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,  // 强制使用 5173 端口
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:19000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://127.0.0.1:19000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err, _req, _res) => {
            const code = (err as NodeJS.ErrnoException).code
            if (code === 'EPIPE' || code === 'ECONNRESET') {
              return
            }
            console.error('[vite] ws proxy error:', err.message)
          })
        },
      },
    },
  },
})
