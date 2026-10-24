import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Allow ngrok tunnels (the free subdomain changes on each restart,
    // so allow the whole ngrok-free.dev domain rather than one host).
    allowedHosts: ['.ngrok-free.dev'],
    proxy: {
      '/auth': 'http://localhost:8080',
      '/users': 'http://localhost:8080',
      '/twilio-numbers': 'http://localhost:8080',
      '/contacts': 'http://localhost:8080',
      '/clients': 'http://localhost:8080',
      '/projects': 'http://localhost:8080',
      '/lead-research': 'http://localhost:8080',
      // ws:true so Twilio's Media Stream (wss://.../calls/media-stream/:id)
      // upgrades through to the backend, not just plain HTTP webhooks.
      '/calls': {
        target: 'http://localhost:8080',
        ws: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
        timeout: 0, // No timeout - keep WebSocket alive indefinitely
      },
    },
  },
})
