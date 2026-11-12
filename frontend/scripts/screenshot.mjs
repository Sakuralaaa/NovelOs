// 用法：npm run build:mock && node scripts/screenshot.mjs [only]
import { preview } from 'vite'
import { chromium } from 'playwright'
import fs from 'node:fs'

const only = process.argv[2]
const server = await preview({ preview: { port: 4179, strictPort: true }, build: { outDir: 'dist-mock' } })
const base = 'http://localhost:4179'
const OUT=process.env.OUT||'screenshots';fs.mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
const shots = [
  ['login', '/?auth=out'],
  ['home', '/'],
  ['radar', '/radar'],
  ['ideas', '/ideas'],
  ['books', '/books'],
  ['book-overview', '/books/1'],
  ['bible', '/books/1/bible'],
  ['style', '/books/1/style'],
  ['outline', '/books/1/outline'],
  ['chapter', '/books/1/chapters/200'],
  ['chapter-variants', '/books/1/chapters/205'],
  ['foreshadows', '/books/1/foreshadows'],
  ['package', '/books/1/package'],
  ['settings', '/settings'],
]
const errors = []
for (const dark of [false, true]) {
  for (const [name, path] of shots) {
    if (only && !name.includes(only)) continue
    if (dark && !['home', 'chapter', 'radar', 'settings'].includes(name)) continue
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, colorScheme: dark ? 'dark' : 'light', locale: 'zh-CN' })
    const page = await ctx.newPage()
    page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`))
    page.on('console', (m) => m.type() === 'error' && errors.push(`${name} console: ${m.text()}`))
    if (name !== 'login') await page.addInitScript(() => sessionStorage.setItem('mock-auth', '1'))
    await page.goto(base + path)
    await page.waitForTimeout(1800)
    const file = `${OUT}/${name}${dark ? '-dark' : ''}.png`
    await page.screenshot({ path: file, fullPage: false })
    console.log('saved', file)
    await ctx.close()
  }
}
if (errors.length) console.log('ERRORS:\n' + errors.join('\n'))
await browser.close()
server.httpServer.close()
process.exit(0)
