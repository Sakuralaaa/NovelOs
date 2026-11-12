import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Menu } from '@/components/icons'
import { Sidebar } from './Sidebar'
import { JobTray } from './JobTray'
import { CommandPalette } from './CommandPalette'
import { Logo } from '@/components/common/States'
import { useHotkey } from '@/hooks/useHotkey'
import { cn } from '@/lib/utils'

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('novelos-sidebar') === '1')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [cmdOpen, setCmdOpen] = useState(false)
  const loc = useLocation()
  // 写作页面默认收起主侧栏，给正文留出空间（不影响用户在其他页面的偏好）
  const onWriting = /\/books\/\d+\/chapters/.test(loc.pathname)
  const [writingExpanded, setWritingExpanded] = useState(false)
  const effCollapsed = onWriting ? !writingExpanded : collapsed
  const toggle = () => (onWriting ? setWritingExpanded((x) => !x) : setCollapsed((c) => !c))

  useEffect(() => { localStorage.setItem('novelos-sidebar', collapsed ? '1' : '0') }, [collapsed])
  useEffect(() => { setMobileOpen(false) }, [loc.pathname])
  useHotkey('mod+k', () => setCmdOpen((o) => !o))
  useHotkey('mod+b', toggle)

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      <div className="hidden md:block">
        <Sidebar collapsed={effCollapsed} onToggle={toggle} onSearch={() => setCmdOpen(true)} />
      </div>
      {/* 移动端抽屉 */}
      <div className={cn('fixed inset-0 z-40 md:hidden', mobileOpen ? 'pointer-events-auto' : 'pointer-events-none')}>
        <div className={cn('absolute inset-0 bg-black/30 transition-opacity', mobileOpen ? 'opacity-100' : 'opacity-0')} onClick={() => setMobileOpen(false)} />
        <div className={cn('absolute inset-y-0 left-0 bg-background transition-transform duration-200', mobileOpen ? 'translate-x-0' : '-translate-x-full')}>
          <Sidebar collapsed={false} onToggle={() => {}} onSearch={() => { setMobileOpen(false); setCmdOpen(true) }} onNavigate={() => setMobileOpen(false)} />
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b px-3 md:hidden">
          <button onClick={() => setMobileOpen(true)} className="rounded-md p-1.5 hover:bg-muted" aria-label="打开菜单"><Menu className="h-5 w-5" /></button>
          <Logo />
        </header>
        <main id="main" className="relative min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <JobTray />
      <CommandPalette open={cmdOpen} onOpenChange={setCmdOpen} />
    </div>
  )
}
