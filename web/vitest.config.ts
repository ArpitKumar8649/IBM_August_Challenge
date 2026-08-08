import { defineConfig } from 'vitest/config'

// Kept separate from vite.config.ts so tests never load the Cesium plugin.
// Node environment: these specs exercise pure client helpers (no DOM/Cesium).
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
