import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import * as CB from '@radix-ui/react-checkbox'
import { toast } from 'sonner'
import { AlertTriangle, Check, CheckCircle2, Copy, Flask, ImagePlus, RefreshCw, Sparkles } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { EmptyState, ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { BookTestField, BookTestVariant, Package } from '@/lib/types'
import { cn, copyText, fmtDateTime } from '@/lib/utils'

export const BT_FIELDS: { key: BookTestField; label: string; to: string }[] = [
  { key: 'title', label: '书名', to: '书名' },
  { key: 'subtitle', label: '副标题', to: '一句话简介' },
  { key: 'hook', label: '钩子', to: '包装简介' },
  { key: 'cover_prompt', label: '封面提示词', to: '包装封面提示词' },
]
const DEFAULT_FIELDS: BookTestField[] = ['title', 'subtitle']

/** 方案风格名形如「A 番茄情绪爽感」：拆出字母和名字 */
export function splitStyle(style: string) {
  const m = /^([A-Z])\s*[·.、:：]?\s*(.*)$/.exec(style.trim())
  return m ? { letter: m[1], name: m[2] || style } : { letter: '', name: style }
}

export function FieldPicker({ value, onChange, disabled }: { value: BookTestField[]; onChange: (v: BookTestField[]) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {BT_FIELDS.map((f) => {
        const on = value.includes(f.key)
        return (
          <label key={f.key} title={`${f.label} → ${f.to}`} className={cn('flex h-8 cursor-pointer select-none items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] transition',
            on ? 'border-primary/50 bg-primary-soft/60 text-primary' : 'border-border text-muted-foreground hover:text-foreground', disabled && 'pointer-events-none opacity-50')}>
            <CB.Root checked={on} disabled={disabled} onCheckedChange={(c) => onChange(c === true ? [...value, f.key] : value.filter((x) => x !== f.key))}
              className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-input bg-surface data-[state=checked]:border-primary data-[state=checked]:bg-primary">
              <CB.Indicator><Check className="h-3 w-3 text-primary-foreground" strokeWidth={3} /></CB.Indicator>
            </CB.Root>
            {f.label}
          </label>
        )
      })}
    </div>
  )
}

/** v0.9 书测：4 组包装方案（书名 / 副标题 / 钩子 / 封面提示词），挑一组采纳 */
export function BookTestSection({ bookId, onCoverPrompt, onAdopted }: { bookId: number; onCoverPrompt: (prompt: string) => void; onAdopted?: (pkg: Package, applied: BookTestField[]) => void }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const job = useActiveJob(`book-test:${bookId}`)
  const q = useQuery({
    queryKey: qk.bookTest(bookId),
    queryFn: () => api.bookTest(bookId),
    retry: (n, e: any) => e?.status !== 404 && n < 2,
  })
  const notFound = (q.error as any)?.status === 404
  const data = q.data
  const [fields, setFields] = useState<Record<number, BookTestField[]>>({})
  useEffect(() => { setFields({}) }, [data?.created_at])

  const gen = () => start(api.generateBookTest(bookId), { key: `book-test:${bookId}`, label: '书测', successMsg: '4 组书测方案已生成' })
  const undo = useMutation({
    mutationFn: () => api.undoBook(bookId), meta: { errorTitle: '撤回失败' },
    onSuccess: (b) => { qc.setQueryData(qk.book(bookId), b); qc.invalidateQueries({ queryKey: ['books'] }); toast.success('书名和简介已退回上一版') },
  })
  const adopt = useMutation({
    mutationFn: (b: { index: number; fields: BookTestField[] }) => api.adoptBookTest(bookId, b),
    meta: { errorTitle: '采纳失败' },
    onSuccess: (r) => {
      qc.setQueryData(qk.book(bookId), r.book)
      qc.setQueryData(qk.package(bookId), (old: Package | undefined) => ({ ...(old ?? r.package), ...r.package }))
      qc.invalidateQueries({ queryKey: ['books'] })
      qc.invalidateQueries({ queryKey: qk.bookTest(bookId) })
      onAdopted?.(r.package, r.adopted.applied)
      const used = r.adopted.applied.map((k) => BT_FIELDS.find((f) => f.key === k)?.label ?? k).join('、')
      const infoChanged = r.adopted.applied.some((k) => k === 'title' || k === 'subtitle')
      toast.success(`已采纳方案 ${splitStyle(r.adopted.variant.style).letter || r.adopted.index + 1}`, {
        description: `写入：${used}${infoChanged ? '。书名/简介的旧版本已保留，可撤回' : ''}`,
        action: infoChanged ? { label: '撤回', onClick: () => undo.mutate() } : undefined,
        duration: 8000,
      })
    },
  })

  const copy = async (t: string) => { (await copyText(t)) ? toast.success('已复制封面提示词') : toast.info('复制失败，请长按选中后手动复制') }

  return (
    <Card>
      <CardHeader divider title="书测" icon={<Flask className="h-4 w-4" />}
        desc={data ? `生成于 ${fmtDateTime(data.created_at)}${data.model ? ` · ${data.model}` : ''}` : '四种包装路线各出一组书名、副标题、钩子和封面提示词，挑一组采纳'}
        action={data ? <Button size="sm" loading={!!job} icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={gen}>重新书测</Button> : undefined} />
      <div className="p-4 md:p-5">
        {job && <JobInline job={job} className="mb-4" />}
        {q.isLoading ? (
          <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-64 rounded-xl" />)}</div>
        ) : notFound || (data && !data.variants.length) ? (
          !job && <EmptyState compact kind="package" className="border-0 bg-transparent" title="还没做过书测"
            desc="番茄情绪爽感、悬疑规则脑洞、轻松沙雕、起点正剧四个方向各出一组，对比看哪种最抓人。"
            action={<Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={gen}>开始书测</Button>} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : data ? (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              {data.variants.map((v, i) => (
                <VariantCard key={i} v={v} i={i} adopted={data.adopted === i} adoptedFields={data.adopted === i ? data.adopted_fields : []}
                  fields={fields[i] ?? DEFAULT_FIELDS} setFields={(f) => setFields((cur) => ({ ...cur, [i]: f }))}
                  adopting={adopt.isPending && adopt.variables?.index === i} disabled={adopt.isPending}
                  onAdopt={() => adopt.mutate({ index: i, fields: fields[i] ?? DEFAULT_FIELDS })}
                  onCopy={() => copy(v.cover_prompt)} onCoverPrompt={() => onCoverPrompt(v.cover_prompt)} />
              ))}
            </div>
            {!!data.warnings.length && (
              <ul className="mt-4 space-y-1.5">
                {data.warnings.map((w, i) => <li key={i} className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] leading-relaxed"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />{w}</li>)}
              </ul>
            )}
          </>
        ) : null}
      </div>
    </Card>
  )
}

function VariantCard({ v, i, adopted, adoptedFields, fields, setFields, onAdopt, adopting, disabled, onCopy, onCoverPrompt }: {
  v: BookTestVariant; i: number; adopted: boolean; adoptedFields: BookTestField[]; fields: BookTestField[]; setFields: (f: BookTestField[]) => void
  onAdopt: () => void; adopting: boolean; disabled: boolean; onCopy: () => void; onCoverPrompt: () => void
}) {
  const st = splitStyle(v.style)
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.3 }}
      className={cn('flex flex-col rounded-xl bg-surface p-4 hairline', adopted && 'ring-2 ring-primary/50')}>
      <div className="flex items-center gap-2">
        {st.letter && <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground text-[13px] font-semibold text-background">{st.letter}</span>}
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-muted-foreground">{st.name}</span>
        {adopted && <Badge tone="success" dot>已采纳</Badge>}
      </div>
      <div className="mt-3 break-words font-serif text-[19px] font-semibold leading-snug">《{v.title}》</div>
      {v.subtitle && <div className="mt-1 text-[13.5px] text-foreground/80">{v.subtitle}</div>}
      {v.hook && <p className="mt-3 rounded-lg bg-subtle px-3 py-2 text-[13px] leading-relaxed">{v.hook}</p>}
      {v.cover_prompt && (
        <div className="mt-3 rounded-lg border border-dashed px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-medium text-muted-foreground">封面提示词</span>
            <span className="flex gap-1">
              <Button size="xs" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={onCopy}>复制</Button>
              <Button size="xs" variant="ghost" icon={<ImagePlus className="h-3.5 w-3.5" />} onClick={onCoverPrompt}>带入封面</Button>
            </span>
          </div>
          <p className="mt-1 line-clamp-4 text-[12.5px] leading-relaxed text-foreground/75">{v.cover_prompt}</p>
        </div>
      )}
      {adopted && !!adoptedFields.length && (
        <div className="mt-3 flex items-center gap-1.5 text-[12px] text-success">
          <CheckCircle2 className="h-3.5 w-3.5" />已写入：{adoptedFields.map((k) => BT_FIELDS.find((f) => f.key === k)?.label ?? k).join('、')}
        </div>
      )}
      <div className="mt-auto space-y-2.5 pt-4">
        <FieldPicker value={fields} onChange={setFields} disabled={disabled} />
        <Button className="w-full" variant={adopted ? 'secondary' : 'primary'} loading={adopting} disabled={disabled || !fields.length} icon={<Check className="h-4 w-4" />} onClick={onAdopt}>
          {adopted ? '再次采纳这组' : '采纳这组'}
        </Button>
      </div>
    </motion.div>
  )
}
