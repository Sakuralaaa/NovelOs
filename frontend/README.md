# NovelOS 前端（v0.1）

Vite + React 18 + TypeScript + Tailwind v3 + React Router + TanStack Query + Radix 原语 + lucide-react + framer-motion + sonner。
严格按 `../docs/API_CONTRACT.md`（含“v0.1 增补”）调用 `/api`。

## 命令

```bash
npm install
npm run dev          # http://localhost:5173 ，/api 与 /media 代理到 http://localhost:8000
npm run dev:mock     # 无需后端：启用前端内置 fetch mock（VITE_USE_MOCK=1）
npm run build        # tsc -b && vite build → dist/（生产构建不包含 mock 代码）
npm run build:mock   # 带 mock 的构建 → dist-mock/（仅自测用）
npm run typecheck

# 截图自测（需先 npm run build:mock；首次需 npx playwright install chromium）
node scripts/screenshot.mjs      # 各页面静态截图 → screenshots/*.png（含 4 张深色）
node scripts/interactions.mjs    # 交互流程截图 → screenshots/flow-*.png
```

## 目录

```
src/
  main.tsx / App.tsx        入口、路由、QueryClient、全局 toast
  index.css                 主题变量（浅/深）、中文排版
  lib/
    api.ts                  合约全部端点 + query keys
    types.ts                合约类型
    jobs.tsx                全局任务系统：启动/轮询(1.5s)/完成回调/托盘 store
    textAnalysis.ts         句长、裸对白/概述段落识别（高亮用）、段落 diff
    utils.ts                格式化、阶段/类型常量、Job 名称映射
  hooks/                    主题、快捷键、防抖、通用查询
  components/
    ui/                     自建 shadcn 风格组件（button/card/dialog/sheet/tabs/select/switch/tooltip/tag-input…）
    layout/                 AppShell、Sidebar（含书内二级导航）、JobTray、CommandPalette(⌘K)
    common/                 空状态插画、PageHeader、封面、一键开写、写下一章(多版本)/批量写
    chapter/                编辑器(textarea+高亮镜像层)、审稿/人味/变更面板、雷达图/仪表、逐段 Diff
  pages/                    Home、Radar、Ideas、Books、Settings、NotFound
    book/                   Overview、Bible、Style、Outline、Chapters、Foreshadows、Package
  mocks/                    VITE_USE_MOCK=1 时的 fetch mock（覆盖全部端点，含增补）
```

## 快捷键
- `Ctrl/⌘ + S` 立即保存章节（另有 1.5s 防抖自动保存、离开章节自动落盘）
- `Ctrl/⌘ + K` 命令面板
- `Ctrl/⌘ + B` 收起/展开侧栏（章节页默认收起以留出写作空间）
