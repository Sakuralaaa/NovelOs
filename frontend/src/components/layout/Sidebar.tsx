import { NavLink, useLocation, useMatch } from 'react-router-dom'
import {
  BookOpen, Feather, FileText, Home, Layers, LayoutDashboard, Lightbulb, ListTree, Moon, Package,
  PanelLeftClose, PanelLeftOpen, Radar, Search, Settings, Sparkles, Sun, Waypoints,
} from 'lucide-react'
import { Logo } from '@/components/common/States'
import { Kbd } from '@/components/ui/misc'
import { Tip } from '@/components/ui/tooltip'
import { useBook, useStatus } from '@/hooks/queries'
import { toggleTheme, useTheme } from '@/hooks/useTheme'
import { modKey } from '@/hooks/useHotkey'
import { cn } from '@/lib/utils'

const MAIN = [
  { to: '/', label: '首页', icon: Home, end: true },
  { to: '/radar', label: '热点雷达', icon: Radar },
  { to: '/ideas', label: '选题', icon: Lightbulb },
  { to: '/books', label: '我的书', icon: BookOpen },
  { to: '/settings', label: '设置', icon: Settings },
]

export const BOOK_NAV = [
  { to: '', label: '概览', icon: LayoutDashboard, end: true },
  { to: 'bible', label: '设定库', icon: Layers },
  { to: 'style', label: '文风', icon: Feather },
  { to: 'outline', label: '大纲', icon: ListTree },
  { to: 'chapters', label: '章节', icon: FileText },
  { to: 'foreshadows', label: '伏笔', icon: Waypoints },
  { to: 'package', label: '包装发布', icon: Package },
]

export function Sidebar({ collapsed, onToggle, onSearch, onNavigate }: { collapsed: boolean; onToggle: () => void; onSearch: () => void; onNavigate?: () => void }) {
  const m = useMatch('/books/:bookId/*')
  const bookId = m && /^\d+$/.test(m.params.bookId ?? '') ? Number(m.params.bookId) : 0
  const { data: book } = useBook(bookId)
  const { data: status } = useStatus()
  const theme = useTheme()
  const loc = useLocation()

  const item = (active: boolean) =>
    cn(
      'focus-ring group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] transition-colors',
      collapsed && 'justify-center px-0',
      active ? 'bg-surface font-medium text-foreground shadow-card hairline' : 'text-foreground/70 hover:bg-foreground/[0.045] hover:text-foreground',
    )

  return (
    <aside className={cn('flex h-full flex-col border-r bg-subtle/70 transition-[width] duration-200', collapsed ? 'w-[60px]' : 'w-[232px]')}>
      <div className={cn('flex h-14 shrink-0 items-center', collapsed ? 'justify-center' : 'justify-between px-4')}>
        <NavLink to="/" onClick={onNavigate}><Logo collapsed={collapsed} /></NavLink>
        {!collapsed && (
          <Tip content={`收起侧栏 (${modKey}+B)`} side="right">
            <button onClick={onToggle} className="focus-ring hidden rounded-md p-1.5 text-muted-foreground hover:bg-muted md:block" aria-label="收起侧栏">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </Tip>
        )}
      </div>

      <div className={cn('px-3 pb-2', collapsed && 'px-2')}>
        <button
          onClick={onSearch}
          className={cn('focus-ring flex h-8 w-full items-center gap-2 rounded-md bg-surface px-2.5 text-[13px] text-muted-foreground hairline transition hover:text-foreground', collapsed && 'justify-center px-0')}
        >
          <Search className="h-3.5 w-3.5" />
          {!collapsed && <><span className="flex-1 text-left">搜索与跳转</span><Kbd>{modKey}</Kbd><Kbd>K</Kbd></>}
        </button>
      </div>

      <nav className={cn('flex-1 space-y-0.5 overflow-y-auto px-3 py-1', collapsed && 'px-2')}>
        {MAIN.map((n) => (
          <Tip key={n.to} content={collapsed ? n.label : null} side="right">
            <div>
              <NavLink
                to={n.to}
                end={n.end}
                onClick={onNavigate}
                className={({ isActive }) => item(n.to === '/books' ? loc.pathname === '/books' : isActive)}
              >
                <n.icon className="h-4 w-4 shrink-0 opacity-80" />
                {!collapsed && <span>{n.label}</span>}
              </NavLink>
            </div>
          </Tip>
        ))}

        {bookId > 0 && (
          <div className="pt-4">
            {!collapsed ? (
              <div className="mb-1.5 flex items-center gap-2 px-2.5">
                <div className="h-5 w-[3px] rounded-full bg-gradient-to-b from-primary to-violet-500" />
                <div className="min-w-0">
                  <div className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">当前作品</div>
                  <div className="truncate text-[13px] font-semibold" title={book?.title}>{book?.title || '加载中…'}</div>
                </div>
              </div>
            ) : (
              <div className="mx-auto mb-2 h-px w-6 bg-border" />
            )}
            <div className="space-y-0.5">
              {BOOK_NAV.map((n) => (
                <Tip key={n.to} content={collapsed ? n.label : null} side="right">
                  <div>
                    <NavLink to={`/books/${bookId}${n.to ? `/${n.to}` : ''}`} end={n.end} onClick={onNavigate} className={({ isActive }) => cn(item(isActive), !collapsed && 'pl-4')}>
                      <n.icon className="h-4 w-4 shrink-0 opacity-80" />
                      {!collapsed && <span>{n.label}</span>}
                    </NavLink>
                  </div>
                </Tip>
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className={cn('space-y-2 border-t p-3', collapsed && 'p-2')}>
        {status?.mock_mode && !collapsed && (
          <NavLink to="/settings" onClick={onNavigate} className="flex items-start gap-2 rounded-lg bg-warning-soft px-2.5 py-2 text-[12px] leading-snug text-warning transition hover:opacity-90">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span><b className="font-semibold">演示模式</b><br /><span className="opacity-90">生成内容为示例数据，去设置接入模型</span></span>
          </NavLink>
        )}
        <div className={cn('flex items-center gap-1', collapsed ? 'flex-col' : 'justify-between')}>
          <Tip content={theme === 'dark' ? '切换浅色' : '切换深色'} side="right">
            <button onClick={toggleTheme} className="focus-ring flex h-8 items-center gap-2 rounded-md px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground">
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {!collapsed && <span>{theme === 'dark' ? '浅色模式' : '深色模式'}</span>}
            </button>
          </Tip>
          {collapsed && (
            <Tip content={`展开侧栏 (${modKey}+B)`} side="right">
              <button onClick={onToggle} className="focus-ring hidden rounded-md p-2 text-muted-foreground hover:bg-muted md:block" aria-label="展开侧栏">
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </Tip>
          )}
          {!collapsed && <span className="pr-1 text-[11px] text-muted-foreground/70">v0.1</span>}
        </div>
      </div>
    </aside>
  )
}
