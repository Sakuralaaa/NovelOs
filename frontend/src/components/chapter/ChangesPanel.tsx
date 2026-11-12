import { ArrowRightLeft, Sparkle, UserPlus } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/common/States'
import type { ChangeSet } from '@/lib/types'

const ACT = { plant: { l: '埋设', t: 'primary' }, advance: { l: '推进', t: 'warning' }, resolve: { l: '回收', t: 'success' } } as const
const show = (x: any) => (typeof x === 'string' ? x : x?.name ? `${x.name}${x.type ? `（${x.type}）` : ''}` : x?.entity ? `${x.entity}：${x.change ?? x.value ?? ''}` : JSON.stringify(x))

export function ChangesPanel({ changes }: { changes?: ChangeSet | null }) {
  if (!changes) return <EmptyState compact kind="foreshadow" className="border-0 bg-transparent" title="暂无变更声明" />
  const empty = !changes.new_entities?.length && !changes.state_changes?.length && !changes.foreshadow?.length
  if (empty) return <p className="py-8 text-center text-[13px] text-muted-foreground">本章没有新的设定变更</p>
  return (
    <div className="space-y-5">
      <Section icon={<UserPlus className="h-4 w-4" />} title="新出场" items={changes.new_entities?.map(show)} />
      <Section icon={<ArrowRightLeft className="h-4 w-4" />} title="状态变化" items={changes.state_changes?.map(show)} />
      <div>
        <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold"><Sparkle className="h-4 w-4 text-muted-foreground" />伏笔动作</h4>
        {changes.foreshadow?.length ? changes.foreshadow.map((f, i) => (
          <div key={i} className="mb-1.5 flex items-start gap-2 rounded-lg px-3 py-2 text-[13px] hairline"><Badge tone={ACT[f.action]?.t ?? 'neutral'} className="h-5 text-[11px]">{ACT[f.action]?.l ?? f.action}</Badge><span className="leading-relaxed">{f.desc}</span></div>
        )) : <p className="text-xs text-muted-foreground">无</p>}
      </div>
    </div>
  )
}
function Section({ icon, title, items }: { icon: React.ReactNode; title: string; items?: string[] }) {
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold"><span className="text-muted-foreground">{icon}</span>{title}</h4>
      {items?.length ? <ul className="space-y-1">{items.map((t, i) => <li key={i} className="rounded-lg px-3 py-2 text-[13px] hairline">{t}</li>)}</ul> : <p className="text-xs text-muted-foreground">无</p>}
    </div>
  )
}
