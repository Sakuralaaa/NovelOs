// 交互流程截图：npm run build:mock && node scripts/interactions.mjs
import { preview } from 'vite'
import { chromium } from 'playwright'

const server = await preview({ preview: { port: 4180, strictPort: true }, build: { outDir: 'dist-mock' } })
const base = 'http://localhost:4180'
const browser = await chromium.launch()
const errors = []
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'zh-CN' })
const page = await ctx.newPage()
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => m.type() === 'error' && errors.push('console: ' + m.text()))
const shot = async (n) => { await page.screenshot({ path: `screenshots/flow-${n}.png` }); console.log('saved', n) }

// 1. 人味面板 + 高亮
await page.goto(base + '/books/1/chapters/200'); await page.waitForTimeout(1200)
await page.getByRole('tab', { name: '人味' }).click(); await page.waitForTimeout(400)
const switches = page.locator('aside button[role=switch]')
await switches.nth(0).click(); await switches.nth(1).click(); await page.waitForTimeout(400)
await shot('lint-highlight')
// 2. 审稿引文定位
await page.getByRole('tab', { name: '审稿' }).click(); await page.waitForTimeout(300)
await page.locator('aside button:has-text("门外人第一次开口")').click(); await page.waitForTimeout(900)
await shot('review-quote')
// 3. 描写增厚 → diff
await page.getByRole('button', { name: '描写增厚' }).first().click(); await page.waitForTimeout(1500)
await shot('thicken-running')
await page.waitForTimeout(4000)
await shot('thicken-diff')
await page.locator('button:has-text("撤销这处")').first().click(); await page.waitForTimeout(300)
await page.getByRole('button', { name: '确定' }).click(); await page.waitForTimeout(1200)
// 4. 多版本采纳
await page.goto(base + '/books/1/chapters/205'); await page.waitForTimeout(1200)
await page.locator('button:has-text("版本 C")').click(); await page.waitForTimeout(300)
await shot('variants')
await page.getByRole('button', { name: '采纳此版' }).click(); await page.waitForTimeout(1000)
await shot('variant-adopted')
// 5. 人物卡编辑
await page.goto(base + '/books/1/bible'); await page.waitForTimeout(1200)
await page.locator('button:has-text("前便利店店员")').first().click(); await page.waitForTimeout(600)
await shot('character-editor')
await page.keyboard.press('Escape')
// 6. 文风提炼
await page.goto(base + '/books/1/style'); await page.waitForTimeout(1000)
await page.getByRole('button', { name: '提炼文风' }).click(); await page.waitForTimeout(4200)
await shot('style-extracted')
// 7. 选题生成
await page.goto(base + '/ideas?genre=末世求生&gender=male&from_trends=1'); await page.waitForTimeout(1000)
await page.getByRole('button', { name: '生成选题' }).click(); await page.waitForTimeout(1500)
await shot('ideas-running')
await page.waitForTimeout(3500)
await shot('ideas-done')
// 8. 写下一章（2 版）
await page.goto(base + '/books/1'); await page.waitForTimeout(1000)
await page.getByRole('button', { name: '版本数设置' }).click(); await page.waitForTimeout(300)
await page.getByRole('tab', { name: '2 版' }).click(); await page.waitForTimeout(300)
await shot('variants-popover')
await page.keyboard.press('Escape')
await page.getByRole('button', { name: /写下一章/ }).first().click(); await page.waitForTimeout(2500)
await shot('write-next-running')
// 9. 命令面板
await page.keyboard.press('Control+k'); await page.waitForTimeout(400)
await shot('command')
await page.keyboard.press('Escape')
// 10. 添加渠道
await page.goto(base + '/settings'); await page.waitForTimeout(800)
await page.getByRole('button', { name: '添加渠道' }).click(); await page.waitForTimeout(300)
await page.locator('button:has-text("DeepSeek")').last().click()
await page.getByPlaceholder('sk-…').fill('sk-test-1234567890'); await page.waitForTimeout(200)
await shot('channel-sheet')
await page.getByRole('button', { name: '保存' }).click(); await page.waitForTimeout(1200)
await page.getByRole('button', { name: '测试连接' }).click(); await page.waitForTimeout(900)
await shot('channel-added')
// 11. 窄屏
await page.setViewportSize({ width: 390, height: 844 })
await page.goto(base + '/books/1/chapters/200'); await page.waitForTimeout(1200)
await shot('mobile-chapter')
await page.goto(base + '/'); await page.waitForTimeout(1000)
await shot('mobile-home')

if (errors.length) console.log('ERRORS:\n' + errors.join('\n'))
await browser.close(); server.httpServer.close(); process.exit(0)
