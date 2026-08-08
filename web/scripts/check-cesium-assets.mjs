/**
 * Post-build gate (Phase G, 5.1): the 3D globe's Cesium runtime must exist in
 * the production bundle.
 *
 * vite-plugin-cesium copies it to dist/cesium/ (Cesium.js, Workers/, Widgets/,
 * Assets/, ThirdParty/) at build time. If that ever regresses — or the plugin
 * is dropped, or the build output is assembled incorrectly for Code Engine —
 * the JS bundles would still build and the globe would silently break in
 * deployment. Fail the build instead of shipping a globe that cannot render.
 *
 * Runs from the `build` script in package.json (and therefore in CI's `web`
 * job), after `vite build` has written dist/.
 */
import { access, readdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cesiumDir = join(webRoot, 'dist', 'cesium')
const REQUIRED = ['Cesium.js', 'Workers', 'Widgets', 'Assets', 'ThirdParty']

const missing = []
for (const name of REQUIRED) {
  try {
    await access(join(cesiumDir, name))
  } catch {
    missing.push(name)
  }
}
if (missing.length > 0) {
  console.error(
    `✗ dist/cesium/ is missing ${missing.join(', ')} — the 3D globe will not render in deployment. ` +
      'Check that vite-plugin-cesium is configured (web/vite.config.ts) and rerun the build.',
  )
  process.exit(1)
}

// Workers/ is guaranteed to exist here (the REQUIRED check above exits if not).
const workers = await readdir(join(cesiumDir, 'Workers'))
if (workers.length === 0) {
  console.error('✗ dist/cesium/Workers/ is empty — Cesium cannot run its worker threads.')
  process.exit(1)
}

console.log(`✓ Cesium runtime present: dist/cesium/ (${workers.length} worker files)`)
