import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Check, CheckCircle2, Download, ImagePlus, Info, PenLine, Save, ShieldAlert, Sparkles, Tag, Type } from 'lucide-react'
import * as CB from '@radix-ui/react-checkbox'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { TagInput } from '@/components/ui/tag-input'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BookCrumb } from './_shared'
import { useBook } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Package } from '@/lib/types'
import { cn, countWords } from '@/lib/utils'

export default function PackagePage() {
  const id = useBookId()
  const { data: book } = useBook(id)
  const q = useQuery({ queryKey: qk.package(id), queryFn: () => api.package(id) })
  const [f, setF] = useState<Package | null>(null)
  const [dirty, setDirty] = useState(false)
  const [customTitle, setCustomTitle] = useState('')
  const [ack, setAck] = useState(() => localStorage.getItem(`novelos-ack-${id}`) === '1')
  const [exporting, setExporting] = useState(false)
  const qc = useQueryClient()
  const { start } = useJobs()
  const pkgJob = useActiveJob(`package:${id}`)
  const coverJob = useActiveJob(`covers:${id}`)

  useEffect(() => { if (q.data && !dirty) setF(q.data) }, [q.data, dirty])

  const save = useMutation({
    mutationFn: (p: Partial<Package>) => api.savePackage(id, p),
    meta: { errorTitle: '保存失败' },
    onSuccess: (p) => { qc.setQueryData(qk.package(id), p); setDirty(false); qc.invalidateQueries({ queryKey: qk.book(id) }); qc.invalidateQueries({ queryKey: ['books'] }) },
  })
  const setTitle = useMutation({
    mutationFn: (title: string) => api.updateBook(id, { title }),
    meta: { errorTitle: '修改书名失败' },
    onSuccess: (b) => { qc.setQueryData(qk.book(id), b); qc.invalidateQueries({ queryKey: ['books'] }); toast.success(`书名已改为《${b.title}》`) },
  })

  if (q.isLoading || !f) return <div className="page"><Skeleton className="h-8 w-48" /><div className="mt-6 grid gap-6 lg:grid-cols-2"><Skeleton className="h-80 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div></div>
  if (q.error) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>

  const set = (p: Partial<Package>) => { setF({ ...f, ...p }); setDirty(true) }
  const empty = !f.titles.length && !f.blurb && !f.covers.length
  const genPkg = () => start(api.generatePackage(id), { key: `package:${id}`, label: '生成包装', successMsg: '书名、简介和标签已生成' })
  const genCovers = async () => {
    if (dirty) await save.mutateAsync({ cover_prompt: f.cover_prompt })
    start(api.generateCovers(id, { prompt: f.cover_prompt || undefined, n: 4 }), { key: `covers:${id}`, label: '生成封面', successMsg: '4 张封面已生成，挑一张吧' })
  }
  const doExport = async () => {
    setExporting(true)
    try { if (dirty) await save.mutateAsync(f); await api.exportBook(id, `${book?.title ?? '作品'}-发布包.zip`); toast.success('发布包已开始下载') }
    catch (e: any) { toast.error('导出失败', { description: e.message }) } finally { setExporting(false) }
  }
  const blurbWords = countWords(f.blurb)

  return (
    <div className="page">
      <BookCrumb bookId={id} page="包装发布" />
      <PageHeader className="mt-3" title="包装与发布" desc="书名、简介、标签、封面决定读者会不会点进来。生成后挑选、修改，最后导出发布包，在番茄作者后台手动上架。"
        actions={<>
          {dirty && <Button icon={<Save className="h-4 w-4" />} loading={save.isPending} onClick={() => save.mutate({ blurb: f.blurb, tags: f.tags, cover_prompt: f.cover_prompt, chosen_cover: f.chosen_cover }, { onSuccess: () => toast.success('已保存') })}>保存修改</Button>}
          <Button variant={empty ? 'primary' : 'secondary'} loading={!!pkgJob} icon={<Sparkles className="h-4 w-4" />} onClick={genPkg}>{empty ? '生成包装' : '重新生成'}</Button>
        </>} />
      {pkgJob && <JobInline job={pkgJob} className="mb-5" />}

      <Notice ack={ack} onAck={(v) => { setAck(v); localStorage.setItem(`novelos-ack-${id}`, v ? '1' : '0') }} onExport={doExport} exporting={exporting} />

      {empty && !pkgJob ? (
        <EmptyState className="mt-6" kind="package" title="还没有包装方案" desc="AI 会参考番茄同题材头部书，生成书名候选、简介和标签。" action={<Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={genPkg}>生成包装</Button>} />
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1fr]">
          <div className="space-y-6">
            <Card>
              <CardHeader title="书名" desc="点击即可设为书名，分数综合了吸引力与题材匹配度" icon={<Type className="h-4 w-4" />} />
              <CardBody className="space-y-2">
                {f.titles.map((t) => {
                  const cur = book?.title === t.title
                  return (
                    <button key={t.title} onClick={() => !cur && setTitle.mutate(t.title)} className={cn('flex w-full items-center gap-3 rounded-lg px-3.5 py-2.5 text-left transition hairline', cur ? 'bg-primary-soft ring-1 ring-primary/40' : 'hover:bg-subtle')}>
                      <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded-full border', cur ? 'border-primary bg-primary text-primary-foreground' : 'border-input')}>{cur && <Check className="h-3 w-3" />}</span>
                      <span className="min-w-0 flex-1 truncate font-medium">{t.title}</span>
                      <div className="flex w-24 shrink-0 items-center gap-2"><div className="h-1.5 flex-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${t.score}%` }} /></div><span className="num w-6 text-right text-xs text-muted-foreground">{t.score}</span></div>
                    </button>
                  )
                })}
                <div className="flex gap-2 pt-1">
                  <Input value={customTitle} onChange={(e) => setCustomTitle(e.target.value)} placeholder="或者自己起一个书名" />
                  <Button disabled={!customTitle.trim()} loading={setTitle.isPending} onClick={() => { setTitle.mutate(customTitle.trim()); setCustomTitle('') }}>使用</Button>
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="简介" icon={<PenLine className="h-4 w-4" />} action={<span className={cn('num text-xs', blurbWords > 300 ? 'text-warning' : 'text-muted-foreground')}>{blurbWords} 字 · 建议 100–300</span>} />
              <CardBody><Textarea value={f.blurb} onChange={(e) => set({ blurb: e.target.value })} className="min-h-[180px] text-[14px] leading-[1.85]" placeholder="前两句最重要：交代主角处境 + 金手指 / 反差。" /></CardBody>
            </Card>
            <Card>
              <CardHeader title="标签" desc="番茄建书时可选的分类标签" icon={<Tag className="h-4 w-4" />} />
              <CardBody><TagInput value={f.tags} onChange={(v) => set({ tags: v })} placeholder="输入标签回车" /></CardBody>
            </Card>
          </div>

          <Card className="h-fit">
            <CardHeader title="封面" desc="选中的封面会用在书架和发布包里" icon={<ImagePlus className="h-4 w-4" />} />
            <CardBody className="space-y-4">
              <div>
                <div className="mb-1.5 text-[13px] font-medium">封面提示词</div>
                <Textarea value={f.cover_prompt} onChange={(e) => set({ cover_prompt: e.target.value })} className="min-h-[96px] text-[13px]" placeholder="画面主体、氛围、色调、构图，例如：暴雪中亮着暖光的小超市……" />
                <div className="mt-2 flex items-center justify-between gap-2">
                  <p className="text-[11.5px] text-muted-foreground">使用「设置 → 任务路由」里的生图模型；书名会在本地叠加排版。</p>
                  <Button variant="primary" size="sm" loading={!!coverJob} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={genCovers}>生成 4 张</Button>
                </div>
              </div>
              {coverJob && <JobInline job={coverJob} />}
              {coverJob && !f.covers.length ? (
                <div className="grid grid-cols-2 gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="aspect-[3/4] rounded-lg" />)}</div>
              ) : f.covers.length ? (
                <div className="grid grid-cols-2 gap-3">
                  {f.covers.map((u, i) => {
                    const sel = f.chosen_cover === u
                    return (
                      <motion.button key={u + i} initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.05 }}
                        onClick={() => { set({ chosen_cover: u }); save.mutate({ chosen_cover: u }, { onSuccess: () => toast.success('已设为封面') }) }}
                        className={cn('group relative overflow-hidden rounded-lg transition', sel ? 'ring-[3px] ring-primary ring-offset-2 ring-offset-surface' : 'hover:shadow-lift')}>
                        <img src={u} alt={`封面 ${i + 1}`} className="aspect-[3/4] w-full object-cover transition group-hover:scale-[1.02]" loading="lazy" />
                        {sel ? <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground shadow"><CheckCircle2 className="h-3 w-3" />已选</span>
                          : <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent py-2 text-center text-xs text-white opacity-0 transition group-hover:opacity-100">设为封面</span>}
                      </motion.button>
                    )
                  })}
                </div>
              ) : (
                <div className="flex aspect-[2/1] flex-col items-center justify-center rounded-lg border border-dashed text-center text-[13px] text-muted-foreground">
                  <ImagePlus className="mb-2 h-6 w-6 opacity-60" />写好提示词后点「生成 4 张」
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  )
}

function Notice({ ack, onAck, onExport, exporting }: { ack: boolean; onAck: (v: boolean) => void; onExport: () => void; exporting: boolean }) {
  return (
    <div className="overflow-hidden rounded-xl border border-warning/30 bg-gradient-to-br from-warning-soft to-surface">
      <div className="flex flex-col gap-5 p-5 md:flex-row md:items-start md:p-6">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-warning/15 text-warning"><ShieldAlert className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold">发布前须知</h3>
          <ul className="mt-2.5 space-y-2 text-[13.5px] leading-relaxed text-foreground/85">
            <li className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-warning" /><span><b className="font-semibold">如实勾选 AI 申报。</b>番茄要求使用 AI 辅助创作的作品在发布时如实声明，国家《人工智能生成合成内容标识办法》也要求主动标识。</span></li>
            <li className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-warning" /><span><b className="font-semibold">先人工通读、改写，再上架。</b>平台持续整治批量 AI 水文，带着你自己的判断和修改，作品才走得远。</span></li>
            <li className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-warning" /><span><b className="font-semibold">手动上架。</b>NovelOS 不会替你自动发布；发布包里附了《AI 申报提示》，照着在作者后台填写即可。</span></li>
          </ul>
          <label className="mt-4 flex w-fit cursor-pointer items-center gap-2.5 text-[13px]">
            <CB.Root checked={ack} onCheckedChange={(v) => onAck(v === true)} className="focus-ring flex h-[18px] w-[18px] items-center justify-center rounded border border-input bg-surface data-[state=checked]:border-primary data-[state=checked]:bg-primary">
              <CB.Indicator><Check className="h-3 w-3 text-primary-foreground" /></CB.Indicator>
            </CB.Root>
            我已了解，会如实申报并人工把关
          </label>
        </div>
        <div className="flex shrink-0 flex-col items-stretch gap-1.5 md:w-[200px]">
          <Button size="lg" variant="primary" disabled={!ack} loading={exporting} icon={<Download className="h-4 w-4" />} onClick={onExport}>导出发布包</Button>
          <p className="flex items-start gap-1 text-[11.5px] leading-snug text-muted-foreground"><Info className="mt-0.5 h-3 w-3 shrink-0" />zip：建书资料、分章 txt、封面、AI 申报提示</p>
        </div>
      </div>
    </div>
  )
}
