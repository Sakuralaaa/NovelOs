import { NavLink, useLocation, useMatch } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  BookOpen, Feather, FileText, House, Layers, LayoutDashboard, Lightbulb, ListTree, LogOut, Moon, Package,
  PanelLeftClose, PanelLeftOpen, Radar, Search, Settings, Sun, Waypoints,
} from '@/components/icons'
import { Logo } from '@/components/common/States'
import { Kbd } from '@/components/ui/misc'
import { Tip } from '@/components/ui/tooltip'
import { useBook, useStatus } from '@/hooks/queries'
import { toggleTheme, useTheme } from '@/hooks/useTheme'
import { modKey } from '@/hooks/useHotkey'
import { api, qk } from '@/lib/api'
import { useAuth } from '@/components/auth/AuthGate'
import { cn } from '@/lib/utils'

const MAIN = [
  { to: '/', label: '首页', icon: House, end: true },
  { to: '/radar', label: '热点雷达', icon: Radar },
  { to: '/ideas', label: '选题', icon: Lightbulb },
  { to: '/books', label: '我的书', icon: BookOpen },
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
  const { data: auth } = useAuth()
  const theme = useTheme()
  const loc = useLocation()
  const qc = useQueryClient()

  const logout = async () => {
    try { await api.logout() } finally {
      qc.clear()
      qc.invalidateQueries({ queryKey: qk.auth })
    }
  }

  const item = (active: boolean) =>
    cn(
      'focus-ring group relative flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] transition-colors',
      collapsed && 'mx-auto w-9 justify-center px-0',
      active
        ? 'bg-foreground/[0.06] font-medium text-foreground dark:bg-foreground/[0.08]'
        : 'text-foreground/65 hover:bg-foreground/[0.04] hover:text-foreground',
    )
  const icon = (active: boolean) => cn('h-[17px] w-[17px] shrink-0 transition-colors', active ? 'text-primary' : 'text-foreground/50 group-hover:text-foreground/80')

  const Section = ({ label }: { label: string }) =>
    collapsed ? <div className="mx-auto my-3 h-px w-6 bg-border" /> : <div className="mb-1 mt-5 px-3 text-[11.5px] font-medium text-muted-foreground/80">{label}</div>

  const footBtn = 'focus-ring flex h-9 w-9 items-center justify-center rounded-lg text-foreground/55 transition-colors hover:bg-foreground/[0.05] hover:text-foreground'

  return (
    <aside className={cn('flex h-full flex-col border-r bg-surface/60 transition-[width] duration-200 dark:bg-background', collapsed ? 'w-[64px]' : 'w-[240px]')}>
      <div className={cn('flex h-16 shrink-0 items-center', collapsed ? 'justify-center' : 'justify-between pl-5 pr-3')}>
        <NavLink to="/" onClick={onNavigate} className="focus-ring rounded-lg"><Logo collapsed={collapsed} /></NavLink>
        {!collapsed && (
          <Tip content={`收起侧栏 (${modKey}+B)`} side="right">
            <button onClick={onToggle} className={cn(footBtn, 'hidden h-8 w-8 md:flex')} aria-label="收起侧栏">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </Tip>
        )}
      </div>

      <div className={cn('px-3', collapsed && 'px-0')}>
        <Tip content={collapsed ? '搜索' : null} side="right">
          <button
            onClick={onSearch}
            className={cn(
              'focus-ring flex h-9 items-center gap-2.5 rounded-lg border bg-background px-3 text-[13px] text-muted-foreground transition hover:border-foreground/15 hover:text-foreground dark:bg-subtle',
              collapsed ? 'mx-auto w-9 justify-center px-0' : 'w-full',
            )}
          >
            <Search className="h-[15px] w-[15px] shrink-0" />
            {!collapsed && <><span className="flex-1 text-left">搜索</span><span className="flex gap-0.5"><Kbd>{modKey}</Kbd><Kbd>K</Kbd></span></>}
          </button>
        </Tip>
      </div>

      <nav className={cn('flex-1 overflow-y-auto px-3 pb-3 pt-3', collapsed && 'px-0')}>
        <div className="space-y-0.5">
          {MAIN.map((n) => {
            return (
              <Tip key={n.to} content={collapsed ? n.label : null} side="right">
                <div>
                  <NavLink to={n.to} end={n.end} onClick={onNavigate} className={({ isActive }) => item(n.to === '/books' ? loc.pathname === '/books' : isActive)}>
                    {({ isActive }) => {
                      const a = n.to === '/books' ? loc.pathname === '/books' : isActive
                      return <><n.icon className={icon(a)} weight={a ? 'duotone' : 'regular'} />{!collapsed && <span>{n.label}</span>}</>
                    }}
                  </NavLink>
                </div>
              </Tip>
            )
          })}
        </div>

        {bookId > 0 && (
          <>
            {collapsed ? <Section label="" /> : (
              <div className="mb-1 mt-5 px-3">
                <div className="text-[11.5px] font-medium text-muted-foreground/80">当前作品</div>
                <div className="mt-0.5 truncate text-[13px] font-semibold" title={book?.title}>{book?.title || '…'}</div>
              </div>
            )}
            <div className="space-y-0.5">
              {BOOK_NAV.map((n) => (
                <Tip key={n.to} content={collapsed ? n.label : null} side="right">
                  <div>
                    <NavLink to={`/books/${bookId}${n.to ? `/${n.to}` : ''}`} end={n.end} onClick={onNavigate} className={({ isActive }) => item(isActive)}>
                      {({ isActive }) => <><n.icon className={icon(isActive)} weight={isActive ? 'duotone' : 'regular'} />{!collapsed && <span>{n.label}</span>}</>}
                    </NavLink>
                  </div>
                </Tip>
              ))}
            </div>
          </>
        )}
      </nav>

      <div className={cn('border-t p-3', collapsed && 'px-0')}>
        {status?.mock_mode && !collapsed && (
          <NavLink to="/settings" onClick={onNavigate} className="mb-2 flex h-8 items-center gap-2 rounded-lg bg-warning-soft px-3 text-[12.5px] font-medium text-warning transition hover:brightness-95">
            <span className="h-1.5 w-1.5 rounded-full bg-warning" />演示模式
          </NavLink>
        )}
        <div className={cn('flex items-center gap-1', collapsed ? 'flex-col' : 'justify-between')}>
          <Tip content={collapsed ? '设置' : null} side="right">
            <div className={cn(!collapsed && 'flex-1')}>
              <NavLink to="/settings" onClick={onNavigate} className={({ isActive }) => item(isActive)}>
                {({ isActive }) => <><Settings className={icon(isActive)} weight={isActive ? 'duotone' : 'regular'} />{!collapsed && <span>设置</span>}</>}
              </NavLink>
            </div>
          </Tip>
          <div className={cn('flex items-center gap-0.5', collapsed && 'flex-col')}>
            <Tip content={theme === 'dark' ? '浅色模式' : '深色模式'} side={collapsed ? 'right' : 'top'}>
              <button onClick={toggleTheme} className={footBtn} aria-label="切换主题">
                {theme === 'dark' ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
              </button>
            </Tip>
            {auth?.enabled && (
              <Tip content="退出登录" side={collapsed ? 'right' : 'top'}>
                <button onClick={logout} className={footBtn} aria-label="退出登录"><LogOut className="h-[17px] w-[17px]" /></button>
              </Tip>
            )}
            {collapsed && (
              <Tip content={`展开侧栏 (${modKey}+B)`} side="right">
                <button onClick={onToggle} className={cn(footBtn, 'hidden md:flex')} aria-label="展开侧栏"><PanelLeftOpen className="h-[17px] w-[17px]" /></button>
              </Tip>
            )}
          </div>
        </div>
      </div>
    </aside>
  )
}
