import { Command } from 'cmdk'
import * as D from '@radix-ui/react-dialog'
import { useNavigate } from 'react-router-dom'
import { BookOpen, CornerDownLeft, Home, Lightbulb, Moon, Radar, Settings } from 'lucide-react'
import { useBooks } from '@/hooks/queries'
import { toggleTheme } from '@/hooks/useTheme'
import { BOOK_NAV } from './Sidebar'

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate()
  const { data: books } = useBooks()
  const go = (to: string) => { onOpenChange(false); nav(to) }
  const itemCls = 'flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-[13.5px] data-[selected=true]:bg-muted'
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/25 backdrop-blur-[2px] animate-fade-in" />
        <D.Content className="fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-2rem)] max-w-[560px] -translate-x-1/2 overflow-hidden rounded-xl bg-popover shadow-pop hairline animate-zoom-in">
          <D.Title className="sr-only">命令面板</D.Title>
          <D.Description className="sr-only">搜索页面与作品</D.Description>
          <Command loop>
            <Command.Input autoFocus placeholder="搜索页面、作品，或输入命令…" className="h-12 w-full border-b bg-transparent px-4 text-[14.5px] outline-none placeholder:text-muted-foreground" />
            <Command.List className="max-h-[360px] overflow-y-auto p-2">
              <Command.Empty className="py-8 text-center text-sm text-muted-foreground">没有找到匹配项</Command.Empty>
              <Command.Group heading="导航" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted-foreground">
                <Command.Item className={itemCls} onSelect={() => go('/')}><Home className="h-4 w-4 opacity-70" />首页</Command.Item>
                <Command.Item className={itemCls} onSelect={() => go('/radar')}><Radar className="h-4 w-4 opacity-70" />热点雷达</Command.Item>
                <Command.Item className={itemCls} onSelect={() => go('/ideas')}><Lightbulb className="h-4 w-4 opacity-70" />选题</Command.Item>
                <Command.Item className={itemCls} onSelect={() => go('/books')}><BookOpen className="h-4 w-4 opacity-70" />我的书</Command.Item>
                <Command.Item className={itemCls} onSelect={() => go('/settings')}><Settings className="h-4 w-4 opacity-70" />设置 · 模型渠道</Command.Item>
                <Command.Item className={itemCls} onSelect={() => { toggleTheme(); onOpenChange(false) }}><Moon className="h-4 w-4 opacity-70" />切换深色 / 浅色</Command.Item>
              </Command.Group>
              {books && books.length > 0 && (
                <Command.Group heading="作品" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted-foreground">
                  {books.slice(0, 8).flatMap((b) =>
                    BOOK_NAV.map((n) => (
                      <Command.Item key={`${b.id}-${n.to}`} value={`${b.title} ${n.label}`} className={itemCls} onSelect={() => go(`/books/${b.id}${n.to ? `/${n.to}` : ''}`)}>
                        <n.icon className="h-4 w-4 opacity-70" />
                        <span className="truncate">{b.title}</span>
                        <span className="text-muted-foreground">· {n.label}</span>
                      </Command.Item>
                    )),
                  )}
                </Command.Group>
              )}
            </Command.List>
            <div className="flex items-center justify-end gap-1.5 border-t px-3 py-2 text-[11.5px] text-muted-foreground">
              <CornerDownLeft className="h-3 w-3" /> 打开　·　Esc 关闭
            </div>
          </Command>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
