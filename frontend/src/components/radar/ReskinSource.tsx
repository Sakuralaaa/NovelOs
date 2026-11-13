import { useState } from 'react'
import { AlertTriangle, ArrowRight, Check, ChevronDown, Feather, ShieldCheck } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import type { IdeaSource } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Warnings } from './ImitatePanel'

/** 选题详情：榜单仿写选题的来源、保留/改动、相似点自检 */
export function ReskinSource({ src, className }: { src: IdeaSource; className?: string }) {
  src = { ...src, kept: src.kept ?? [], changed: src.changed ?? [], self_check: src.self_check ?? [], warnings: src.warnings ?? [], overlap: src.overlap ?? { count: 0, segments: [] } }
  const similar = src.self_check.filter((c) => c.similar).length
  const overlap = src.overlap?.count ?? 0
  const titleOverlap = Number(src.overlap?.title ?? 0)
  const risky = similar > 0 || overlap > 0 || titleOverlap > 0 || src.warnings.length > 0
  const [open, setOpen] = useState(risky)

  return (
    <Card className={cn('overflow-hidden', className)}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3.5 text-left">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><Feather className="h-[15px] w-[15px]" weight="duotone" /></span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14.5px] font-semibold tracking-tight">参考：《{src.ref_title}》</div>
          <div className="text-[12.5px] text-muted-foreground">榜单仿写选题{src.ref_category ? ` · ${src.ref_category}` : ''} · 只借结构，皮已换</div>
        </div>
        <span className="flex shrink-0 items-center gap-1.5">
          {risky
            ? <Badge tone="warning"><AlertTriangle className="h-3 w-3" />{similar ? `${similar} 项偏像` : `${src.warnings.length || overlap} 条提醒`}</Badge>
            : <Badge tone="success"><ShieldCheck className="h-3 w-3" />自检通过</Badge>}
          <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t px-5 py-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Col tone="success" label="保留的结构" items={src.kept} />
            <Col tone="primary" label="换掉的皮" items={src.changed} />
          </div>

          {src.self_check.length > 0 && (
            <div>
              <div className="mb-2 text-[13px] font-medium text-foreground/85">相似点自检</div>
              <div className="overflow-hidden rounded-xl border">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-[12.5px]">
                    <thead>
                      <tr className="border-b bg-subtle/50 text-left text-[11.5px] text-muted-foreground">
                        <th className="h-9 w-[88px] pl-3 font-medium">维度</th>
                        <th className="h-9 px-2 font-medium">原书</th>
                        <th className="h-9 px-2 font-medium">我们</th>
                        <th className="h-9 w-[72px] pr-3 text-right font-medium">判断</th>
                      </tr>
                    </thead>
                    <tbody>
                      {src.self_check.map((c, i) => (
                        <tr key={i} className={cn('border-b border-border/60 align-top last:border-0', c.similar && 'bg-danger-soft/50')}>
                          <td className="py-2.5 pl-3 font-medium">{c.aspect}</td>
                          <td className="px-2 py-2.5 leading-relaxed text-muted-foreground">{c.original || '—'}</td>
                          <td className={cn('px-2 py-2.5 leading-relaxed', c.similar && 'font-medium text-danger')}>{c.ours || '—'}</td>
                          <td className="py-2.5 pr-3 text-right">
                            {c.similar ? <Badge tone="danger">偏像</Badge> : <Badge tone="success">已区分</Badge>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {(overlap > 0 || titleOverlap > 0) && (
            <div className="rounded-xl border border-danger/20 bg-danger-soft/40 px-4 py-3">
              <div className="text-[12.5px] font-medium text-danger">
                与原书书名/简介的连续重合：{overlap} 处{titleOverlap > 0 ? `，书名重合 ${titleOverlap} 处` : ''}
              </div>
              {src.overlap.segments?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {src.overlap.segments.map((s, i) => <mark key={i} className="rounded bg-danger/15 px-1.5 py-0.5 font-serif text-[12.5px] text-foreground">{s}</mark>)}
                </div>
              )}
              <p className="mt-2 text-[12px] text-muted-foreground">建议改写这些片段，或用下方「让 AI 改」换个说法。</p>
            </div>
          )}

          <Warnings items={src.warnings} />
        </div>
      )}
    </Card>
  )
}

function Col({ tone, label, items }: { tone: 'success' | 'primary'; label: string; items: string[] }) {
  return (
    <div className={cn('rounded-xl border px-4 py-3', tone === 'success' ? 'border-success/20 bg-success-soft/40' : 'border-primary/20 bg-primary-soft/40')}>
      <div className={cn('text-[12px] font-medium', tone === 'success' ? 'text-success' : 'text-primary')}>{label}</div>
      {items.length ? (
        <ul className="mt-1.5 space-y-1.5">
          {items.map((x, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
              {tone === 'success' ? <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-success" strokeWidth={2.5} /> : <ArrowRight className="mt-[3px] h-3.5 w-3.5 shrink-0 text-primary" strokeWidth={2.5} />}
              <span className="min-w-0 break-words">{x}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-1 text-[13px] text-muted-foreground">—</p>}
    </div>
  )
}
