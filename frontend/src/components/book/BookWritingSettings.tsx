import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Settings } from '@/components/icons'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { apiV094, qkV094 } from '@/lib/api'
import type { BookWritingSettings as BWS, BookWritingToggles } from '@/lib/types'
import { cn } from '@/lib/utils'

type Tri = 'inherit' | 'on' | 'off'
const ROWS: { key: keyof BookWritingToggles; label: string; desc: string }[] = [
  { key: 'fix_mid_before_commit', label: '提交前修中等问题', desc: '提交前先应用连续性 / 追读欲的一般问题补丁，剩下的定点改写原句' },
  { key: 'auto_rereview', label: '补丁后自动复审', desc: '写章自动应用补丁后再审一次；仍有严重问题就标记、不提交' },
]
const toTri = (v: boolean | null | undefined): Tri => (v == null ? 'inherit' : v ? 'on' : 'off')
const fromTri = (t: Tri): boolean | null => (t === 'inherit' ? null : t === 'on')

/**
 * v0.9.4：书级写作开关覆盖（跟随全局 / 开 / 关）。
 * GET/PUT /api/books/{id}/writing-settings。可挂在书概览或书设置处：`<BookWritingSettings bookId={bookId} />`
 * `bare` 时不带外层 Card（嵌进已有卡片 / 弹层）。
 */
export function BookWritingSettings({ bookId, bare, className }: { bookId: number; bare?: boolean; className?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: qkV094.bookWriting(bookId), queryFn: () => apiV094.bookWritingSettings(bookId), enabled: !!bookId, retry: false })
  const m = useMutation({
    mutationFn: (b: Partial<Record<keyof BookWritingToggles, boolean | null>>) => apiV094.saveBookWritingSettings(bookId, b),
    meta: { errorTitle: '保存本书写作设置失败' },
    onMutate: async (b) => {
      await qc.cancelQueries({ queryKey: qkV094.bookWriting(bookId) })
      const prev = qc.getQueryData<BWS>(qkV094.bookWriting(bookId))
      if (prev) qc.setQueryData<BWS>(qkV094.bookWriting(bookId), { ...prev, overrides: { ...prev.overrides, ...b } })
      return { prev }
    },
    onError: (_e, _b, ctx) => { if (ctx?.prev) qc.setQueryData(qkV094.bookWriting(bookId), ctx.prev) },
    onSuccess: (d) => { qc.setQueryData(qkV094.bookWriting(bookId), d); toast.success('本书写作设置已保存') },
  })
  const d = q.data
  const body = q.isError ? (
    <p className="px-5 py-4 text-[12.5px] text-muted-foreground">读取本书写作设置失败{(q.error as any)?.message ? `：${(q.error as any).message}` : ''}</p>
  ) : !d ? <Skeleton className="m-5 h-24" /> : (
    <div className="divide-y divide-border/70">
      {ROWS.map((r) => {
        const tri = toTri(d.overrides?.[r.key])
        const g = d.global?.[r.key]
        const eff = d.effective?.[r.key]
        return (
          <div key={r.key} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 text-[13.5px] font-medium">
                {r.label}
                <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', eff ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>当前{eff ? '开' : '关'}</span>
              </div>
              <div className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">{r.desc}</div>
            </div>
            <Segmented<Tri> size="sm" className="w-full shrink-0 sm:w-auto" block value={tri}
              onChange={(v) => { if (v !== tri && !m.isPending) m.mutate({ [r.key]: fromTri(v) }) }}
              options={[{ value: 'inherit', label: `跟随全局（${g ? '开' : '关'}）` }, { value: 'on', label: '开' }, { value: 'off', label: '关' }]} />
          </div>
        )
      })}
    </div>
  )
  if (bare) return <div className={className}>{body}</div>
  return (
    <Card className={className}>
      <CardHeader divider title="本书写作设置" desc="覆盖全局写作偏好，只对这本书生效" icon={<Settings className="h-4 w-4" />} />
      <CardBody className="p-0">{body}</CardBody>
    </Card>
  )
}
