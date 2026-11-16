import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  AlertTriangle, ArrowRight, Check, ChevronLeft, ClipboardPaste, CloudUpload, Feather, FileText, Layers3, Lightbulb, RefreshCw, Sparkles, Wand2, X,
} from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Segmented } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { ScoreRing } from '@/components/ui/misc'
import { ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BookCover } from '@/components/radar/BookCover'
import { chapterText } from '@/components/radar/ShelfCard'
import { DEEP_LIMIT, DeepSection, ErrorLine, IdeasSection, TeardownCards, Thinking, Warnings } from '@/components/radar/ImitatePanel'
import { BookPicker, Pill, TextSource, bareLen, type TextDoc } from '@/components/ideas/BookPicker'
import { useLastReskin, useReskin, useRunTeardown, useTeardown } from '@/hooks/queries'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { FusionResult, Gender, Idea, RankBoard, RankItem } from '@/lib/types'
import { GENRES_FEMALE, GENRES_MALE, cn, fmtNum } from '@/lib/utils'

type PathKey = 'spark' | 'imitate' | 'organize' | 'fusion'
const PATHS: Record<PathKey, { title: string; icon: React.ReactNode; desc: string; tags: string[]; steps: string[] }> = {
  spark: { title: '灵感生成', icon: <Wand2 className="h-5 w-5" />, desc: '按频道、题材和今日热点，批量抽选题卡', tags: ['男频 / 女频', '参考热点', '1–5 个'], steps: ['设置', '结果'] },
  imitate: { title: '仿写立项', icon: <Feather className="h-5 w-5" />, desc: '榜单选书或导入正文 → 结构拆解 → 换皮选题', tags: ['榜单选书', '上传 TXT', '相似自检'], steps: ['选参考', '拆解', '换皮选题'] },
  organize: { title: '一键整理', icon: <ClipboardPaste className="h-5 w-5" />, desc: '把零散脑洞、设定、聊天记录粘进来，整理成完整选题卡', tags: ['大段粘贴', '自动补全'], steps: ['粘贴想法', '整理结果'] },
  fusion: { title: '多本熔炉', icon: <Layers3 className="h-5 w-5" />, desc: '投入 1–3 本参考书，按权重融合卖点，炼出新选题', tags: ['1–3 本', '权重配比', '补充说明'], steps: ['投料', '配比', '熔炼结果'] },
}
/** 后端：熔炉每本 text 去空白 ≤20000 字；一键整理 ≤5000 字 */
const FUSION_TEXT_LIMIT = 20000
const ORGANIZE_LIMIT = 5000
const ORDER: PathKey[] = ['spark', 'imitate', 'organize', 'fusion']
const isPath = (x: string | null): x is PathKey => !!x && x in PATHS
/** 取前 limit 个非空白字符对应的原文 */
function clipBare(text: string, limit: number) {
  let n = 0
  for (let i = 0; i < text.length; i++) { if (!/\s/.test(text[i])) n++; if (n > limit) return text.slice(0, i) }
  return text
}

export default function IdeaWizard() {
  const [sp, setSp] = useSearchParams()
  const p = sp.get('path')
  const path = isPath(p) ? p : null
  const choose = (k: PathKey | null) => {
    const n = new URLSearchParams()
    if (k) n.set('path', k)
    setSp(n)
    window.scrollTo({ top: 0 })
  }
  return (
    <div className="page">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <Link to="/ideas" className="mb-1 inline-flex h-8 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground"><ChevronLeft className="h-4 w-4" />选题</Link>
          <h1 className="text-[22px] font-semibold leading-tight tracking-tight">新建立项</h1>
        </div>
        {path && <Button variant="ghost" size="sm" className="h-9" onClick={() => choose(null)}>换一种方式</Button>}
      </div>
      {!path ? (
        <>
          <Steps steps={['选择路径', '填写', '生成']} current={0} reach={0} onGo={() => {}} />
          <PathCards onPick={choose} />
        </>
      ) : path === 'spark' ? <SparkPath key="spark" onBack={() => choose(null)} />
        : path === 'imitate' ? <ImitatePath key={`imitate-${sp.get('book') ?? ''}`} onBack={() => choose(null)} />
        : path === 'organize' ? <OrganizePath key="organize" onBack={() => choose(null)} />
        : <FusionPath key="fusion" onBack={() => choose(null)} />}
    </div>
  )
}

// ---------------------------------------------------------------- 通用

/** 顶部步骤条：前置未完成的步骤禁用；0 = 选择路径 */
function Steps({ steps, current, reach, onGo }: { steps: string[]; current: number; reach: number; onGo: (i: number) => void }) {
  return (
    <ol className="-mx-1 mb-5 flex items-center gap-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
      {steps.map((s, i) => {
        const done = i < current
        const on = i === current
        const ok = i <= reach
        return (
          <li key={s + i} className="flex shrink-0 items-center gap-1">
            {i > 0 && <span className={cn('h-px w-4 sm:w-8', i <= reach ? 'bg-primary/40' : 'bg-border')} />}
            <button type="button" disabled={!ok || on} onClick={() => onGo(i)} aria-current={on ? 'step' : undefined}
              className={cn('flex h-10 items-center gap-2 rounded-full pl-1.5 pr-3.5 text-[13px] font-medium transition disabled:cursor-default',
                on ? 'bg-foreground text-background' : ok ? 'bg-surface text-foreground hairline hover:bg-subtle' : 'text-muted-foreground/60')}>
              <span className={cn('num flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold',
                on ? 'bg-background/15' : done ? 'bg-primary text-primary-foreground' : ok ? 'bg-muted' : 'bg-muted/60')}>
                {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
              </span>
              {s}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/** 底部操作条：吸底，整页滚动时一直够得着 */
function Footer({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div data-sticky-footer className="sticky bottom-0 z-10 -mx-5 mt-6 flex flex-wrap items-center justify-end gap-2 border-t bg-background/90 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur md:-mx-10 md:px-10">
      {hint && <div className="mr-auto min-w-0 text-[12.5px] text-muted-foreground">{hint}</div>}
      {children}
    </div>
  )
}

function Panel({ title, desc, children, className, action }: { title?: React.ReactNode; desc?: React.ReactNode; children: React.ReactNode; className?: string; action?: React.ReactNode }) {
  return (
    <section className={cn('rounded-xl border bg-surface p-4 shadow-card sm:p-5', className)}>
      {(title || action) && (
        <div className="mb-3.5 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>}
            {desc && <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{desc}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

function PathCards({ onPick }: { onPick: (k: PathKey) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {ORDER.map((k, i) => {
        const x = PATHS[k]
        return (
          <motion.button key={k} type="button" onClick={() => onPick(k)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.25 }}
            className="card-hover group flex flex-col rounded-xl border bg-surface p-4 text-left shadow-card active:scale-[0.995] sm:p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">{x.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[16px] font-semibold tracking-tight">{x.title}</div>
                <div className="mt-0.5 text-[12.5px] text-muted-foreground">{x.steps.length} 步 · {x.steps.join(' → ')}</div>
              </div>
            </div>
            <p className="mt-3 text-[13.5px] leading-relaxed text-foreground/80">{x.desc}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">{x.tags.map((t) => <span key={t} className="rounded-full bg-muted/80 px-2.5 py-0.5 text-[12px] text-muted-foreground">{t}</span>)}</div>
            <span className="mt-4 inline-flex items-center gap-1 text-[13.5px] font-medium text-primary">开始<ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
          </motion.button>
        )
      })}
    </div>
  )
}

/** 结果里的紧凑选题卡 */
function IdeaMini({ idea: i, onOpen, busy, label = '打开' }: { idea: Idea; onOpen: () => void; busy?: boolean; label?: string }) {
  const warns = i.source?.warnings ?? []
  return (
    <div className="flex flex-col rounded-xl border bg-surface p-4 shadow-card">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="break-words text-[15.5px] font-bold leading-snug tracking-tight">{i.title}</div>
          {i.genre && <div className="mt-0.5 text-[12px] text-muted-foreground">{i.genre}</div>}
        </div>
        {i.scores?.overall ? <ScoreRing value={i.scores.overall} size={44} label="综合" /> : null}
      </div>
      {i.logline && <p className="mt-2 text-[13.5px] font-medium leading-relaxed text-primary">{i.logline}</p>}
      {!!i.selling_points?.length && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">{i.selling_points.slice(0, 3).map((s) => <span key={s} className="inline-flex min-h-[24px] items-center rounded-full bg-sky-50 px-2.5 text-[12px] font-medium text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">{s}</span>)}</div>
      )}
      {i.hook && <p className="mt-2.5 line-clamp-2 text-[12.5px] leading-relaxed text-foreground/70"><span className="text-muted-foreground">钩子：</span>{i.hook}</p>}
      {warns.length > 0 && <p className="mt-2 line-clamp-2 text-[12px] text-warning"><AlertTriangle className="mr-1 inline h-3 w-3" />{warns[0]}</p>}
      <div className="mt-auto pt-3.5">
        <Button variant="primary" className="h-10 w-full" loading={busy} icon={<ArrowRight className="h-4 w-4" />} onClick={onOpen}>{label}</Button>
      </div>
    </div>
  )
}

function GenderGenre({ gender, setGender, genre, setGenre, optional }: { gender: Gender; setGender: (g: Gender) => void; genre: string; setGenre: (g: string) => void; optional?: boolean }) {
  const genres = gender === 'male' ? GENRES_MALE : GENRES_FEMALE
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="频道"><Segmented value={gender} onChange={setGender} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} /></Field>
        <Field label={optional ? '题材（可选）' : '题材'} className="min-w-[200px] flex-1">
          <Input className="h-10" value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="例如：末世求生、年代重生…" />
        </Field>
      </div>
      <div className="flex flex-wrap gap-1.5">{genres.map((g) => <Pill key={g} active={genre === g} onClick={() => setGenre(genre === g ? '' : g)}>{g}</Pill>)}</div>
    </div>
  )
}

// ---------------------------------------------------------------- a) 灵感生成

function SparkPath({ onBack }: { onBack: () => void }) {
  const nav = useNavigate()
  const [step, setStep] = useState(1)
  const [gender, setGender] = useState<Gender>('male')
  const [genre, setGenre] = useState('')
  const [fromTrends, setFromTrends] = useState(true)
  const [count, setCount] = useState(3)
  const [ids, setIds] = useState<number[]>([])
  const { start } = useJobs()
  const job = useActiveJob('ideas')
  const ideas = useQuery({ queryKey: qk.ideas, queryFn: api.ideas, enabled: ids.length > 0 })
  const res = (ideas.data ?? []).filter((x) => ids.includes(x.id))
  const go = () => start(api.generateIdeas({ genre: genre.trim() || undefined, gender, from_trends: fromTrends, count }), {
    key: 'ideas', label: '生成选题', successMsg: (j) => `已生成 ${(j.result?.idea_ids as number[] | undefined)?.length ?? count} 个选题`,
    onSuccess: (j) => { setIds((j.result?.idea_ids as number[]) ?? []); setStep(2); window.scrollTo({ top: 0, behavior: 'smooth' }) },
  })
  return (
    <>
      <Steps steps={['选择路径', ...PATHS.spark.steps]} current={step} reach={ids.length ? 2 : 1} onGo={(i) => (i === 0 ? onBack() : setStep(i))} />
      {step === 1 ? (
        <>
          <Panel title="灵感生成" desc="每张选题卡带书名、一句话卖点、钩子、长线规划和评分，存进选题库。">
            <div className="space-y-4">
              <GenderGenre gender={gender} setGender={setGender} genre={genre} setGenre={setGenre} optional />
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <Field label="数量"><Segmented value={String(count)} onChange={(v) => setCount(Number(v))} options={[1, 3, 5].map((n) => ({ value: String(n), label: `${n} 个` }))} /></Field>
                <label className="flex min-h-[40px] cursor-pointer items-center gap-2.5 self-end text-[13.5px]"><Switch checked={fromTrends} onCheckedChange={setFromTrends} />参考今日热点</label>
              </div>
            </div>
            {job && <JobInline job={job} className="mt-4" />}
          </Panel>
          <Footer hint="不填题材时按今日热点和频道自动选">
            <Button variant="primary" size="lg" loading={!!job} icon={<Wand2 className="h-4 w-4" />} onClick={go}>{job ? '生成中…' : '生成选题'}</Button>
          </Footer>
        </>
      ) : (
        <>
          <ResultHead n={res.length} onAgain={() => setStep(1)} />
          {ideas.isLoading ? <Thinking text="读取选题…" rows={1} /> : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{res.map((i) => <IdeaMini key={i.id} idea={i} onOpen={() => nav(`/ideas/${i.id}`)} />)}</div>
          )}
        </>
      )}
    </>
  )
}

function ResultHead({ n, onAgain, extra }: { n: number; onAgain: () => void; extra?: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-[15px] font-semibold"><Sparkles className="h-4 w-4 text-primary" />得到 {n} 个选题<span className="text-[12.5px] font-normal text-muted-foreground">已存进选题库，选一个进入</span></div>
      <div className="flex items-center gap-1.5">{extra}<Button size="sm" variant="ghost" className="h-9" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onAgain}>调整后再来</Button></div>
    </div>
  )
}

// ---------------------------------------------------------------- b) 仿写立项

function ImitatePath({ onBack }: { onBack: () => void }) {
  const [sp] = useSearchParams()
  const loc = useLocation()
  const preExt = sp.get('book')
  const preItem = (loc.state as { item?: RankItem } | null)?.item
  const preG = (sp.get('gender') as Gender) || preItem?.gender || 'male'
  const preB = (sp.get('board') as RankBoard) || preItem?.board || 'read'
  const [src, setSrc] = useState<'rank' | 'upload' | 'paste'>('rank')
  const [book, setBook] = useState<RankItem | null>(preItem && preItem.book_id_ext === preExt ? preItem : null)
  const [doc, setDoc] = useState<TextDoc | null>(null)
  const [step, setStep] = useState(book ? 2 : 1)
  const [tdReady, setTdReady] = useState(false)

  // 从雷达跳来但没带 state（刷新页面）：按书号在榜单里找回
  const look = useQuery({ queryKey: qk.radarLatest(preG, '', preB), queryFn: () => api.radarLatest({ gender: preG, board: preB }), enabled: !!preExt && !book })
  const looked = useRef(false)
  useEffect(() => {
    if (looked.current || book || !preExt || !look.data) return
    looked.current = true
    const hit = look.data.items.find((i) => i.book_id_ext === preExt)
    if (hit) { setBook(hit); setStep(2) } else toast.info('榜单里没找到这本书，请重新选择')
  }, [look.data, preExt, book])

  const ok1 = !!book || !!doc
  const reach = !ok1 ? 1 : book ? (tdReady ? 3 : 2) : 3
  const goStep = (i: number) => { if (i === 0) onBack(); else { setStep(i); window.scrollTo({ top: 0, behavior: 'smooth' }) } }

  return (
    <>
      <Steps steps={['选择路径', ...PATHS.imitate.steps]} current={step} reach={reach} onGo={goStep} />
      {step === 1 && (
        <>
          <Panel title="选一本参考书" desc="从榜单选书可做结构拆解；另外附上试读正文（上传 TXT 或粘贴）还能按章拆节奏。只导入正文也可以，直接换皮。">
            <Segmented className="mb-4" value={src} onChange={setSrc} options={[
              { value: 'rank', label: <span className="inline-flex items-center gap-1.5"><Lightbulb className="h-3.5 w-3.5" />从榜单选</span> },
              { value: 'upload', label: <span className="inline-flex items-center gap-1.5"><CloudUpload className="h-3.5 w-3.5" />上传 TXT</span> },
              { value: 'paste', label: <span className="inline-flex items-center gap-1.5"><FileText className="h-3.5 w-3.5" />粘贴正文</span> },
            ]} />
            {(book || doc) && (
              <div className="mb-4 flex flex-wrap gap-2">
                {book && <SelChip cover={book.cover} title={book.title} sub={`${book.author} · ${book.category}`} onRemove={() => setBook(null)} />}
                {doc && <SelChip title={doc.title} sub={`${doc.from === 'upload' ? 'TXT' : '粘贴'} · ${doc.chapters.length ? `${doc.chapters.length} 章 · ` : ''}${bareLen(doc.text).toLocaleString('zh-CN')} 字`} onRemove={() => setDoc(null)} icon={<FileText className="h-4 w-4" />} />}
              </div>
            )}
            {src === 'rank' ? (
              <BookPicker single selected={book ? [book] : []} initial={{ gender: preG, board: preB }} onToggle={(i) => setBook((b) => (b?.book_id_ext === i.book_id_ext ? null : i))} />
            ) : (
              <TextSource mode={src} value={doc} onChange={setDoc} maxChars={book ? DEEP_LIMIT : undefined} />
            )}
          </Panel>
          <Footer hint={book ? `已选《${book.title}》${doc ? ' + 正文' : ''}` : doc ? '只用正文：跳过结构拆解' : '先选一本书，或导入正文'}>
            <Button variant="primary" size="lg" disabled={!ok1} icon={<ArrowRight className="h-4 w-4" />} onClick={() => goStep(2)}>下一步：拆解</Button>
          </Footer>
        </>
      )}
      {step === 2 && (book ? (
        <ImitateTeardown key={book.book_id_ext} item={book} text={doc ? clipBare(doc.text, DEEP_LIMIT) : undefined} onReady={setTdReady} onNext={() => goStep(3)} />
      ) : doc ? (
        <>
          <Panel title={`《${doc.title}》`} desc="没有关联榜单书，跳过结构拆解；下一步按这段正文熔炼换皮选题（只学结构、不抄内容）。">
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <Tile label="字数" value={fmtNum(bareLen(doc.text))} />
              <Tile label="章节" value={doc.chapters.length ? `${doc.chapters.length} 章` : '未分章'} />
              <Tile label="来源" value={doc.from === 'upload' ? 'TXT 文件' : '粘贴'} />
            </div>
          </Panel>
          <Footer><Button variant="primary" size="lg" icon={<ArrowRight className="h-4 w-4" />} onClick={() => goStep(3)}>下一步：换皮选题</Button></Footer>
        </>
      ) : null)}
      {step === 3 && (book ? <ImitateReskin key={book.book_id_ext} item={book} /> : doc ? <TextReskin doc={doc} /> : null)}
    </>
  )
}

function SelChip({ cover, title, sub, onRemove, icon }: { cover?: string | null; title: string; sub: string; onRemove: () => void; icon?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 max-w-full items-center gap-2.5 rounded-xl border border-primary/30 bg-primary-soft/40 py-1.5 pl-1.5 pr-1">
      {icon ? <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface text-primary">{icon}</span> : <BookCover src={cover} title={title} size="sm" className="w-[30px] shrink-0" />}
      <div className="min-w-0">
        <div className="truncate text-[13.5px] font-semibold">{title}</div>
        <div className="truncate text-[11.5px] text-muted-foreground">{sub}</div>
      </div>
      <button type="button" aria-label="移除" onClick={onRemove} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-surface hover:text-foreground"><X className="h-4 w-4" /></button>
    </div>
  )
}
function Tile({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded-xl border bg-subtle/40 px-3 py-2.5"><div className="text-[11.5px] text-muted-foreground">{label}</div><div className="num mt-0.5 text-[16px] font-semibold">{value}</div></div>
}

function BookHead({ item }: { item: RankItem }) {
  return (
    <div className="mb-4 flex items-center gap-3 rounded-xl border bg-surface p-3 shadow-card">
      <BookCover src={item.cover} title={item.title} size="sm" className="w-[44px] shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-semibold">仿写《{item.title}》</div>
        <div className="num truncate text-[12.5px] text-muted-foreground">{item.author} · {item.category} · {chapterText(item.chapter_count)} · 在读 {fmtNum(item.read_count)}</div>
      </div>
    </div>
  )
}

function ImitateTeardown({ item, text, onReady, onNext }: { item: RankItem; text?: string; onReady: (b: boolean) => void; onNext: () => void }) {
  const id = item.id ?? 0
  const q = useTeardown(id || undefined)
  const run = useRunTeardown(id)
  const td = q.data?.teardown ?? null
  useEffect(() => onReady(!!td), [td, onReady])
  const auto = useRef(false)
  useEffect(() => {
    if (!id || auto.current || q.isLoading || q.error || !run.ready || run.busy || run.error) return
    if (q.data === null || (q.data && !q.data.teardown)) { auto.current = true; void run.run(false) }
  }, [id, q.isLoading, q.data, q.error, run.ready, run.busy, run.error]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <BookHead item={item} />
      {!id ? (
        <ErrorLine text="这条榜单数据缺少编号（旧快照），刷新一次榜单后再试。" />
      ) : (
        <Panel title="结构拆解" action={td && <Button size="sm" variant="ghost" className="h-9" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={run.busy} onClick={() => void run.run(true)}>重新拆解</Button>}>
          {q.isLoading || (run.busy && !td) ? (
            <Thinking text="正在拆这本书的爽点、金手指和开篇……" sub="后台任务，通常 20–60 秒，离开页面也会继续。" progress={run.busy ? run.progress : undefined} message={run.message} />
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} className="py-10" />
          ) : !td ? (
            <div className="rounded-xl border border-dashed px-5 py-8 text-center">
              {run.error && <p className="mx-auto mb-3 max-w-sm break-words text-[12.5px] text-danger">{run.error}</p>}
              <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={() => void run.run(false)}>{run.error ? '再试一次' : '开始拆解'}</Button>
            </div>
          ) : (
            <div className={cn('transition-opacity', run.busy && 'pointer-events-none opacity-50')}><TeardownCards td={td} /></div>
          )}
          {td && <DeepSection itemId={id} deep={q.data?.deep ?? null} initialText={text} num={2} />}
        </Panel>
      )}
      <Footer hint={td ? '拆解完成，可以换皮了' : '拆解完成后才能换皮'}>
        <Button variant="primary" size="lg" disabled={!td} icon={<ArrowRight className="h-4 w-4" />} onClick={onNext}>下一步：换皮选题</Button>
      </Footer>
    </>
  )
}

function ImitateReskin({ item }: { item: RankItem }) {
  const nav = useNavigate()
  const id = item.id ?? 0
  const reskin = useReskin(id)
  const last = useLastReskin(id)
  return (
    <>
      <BookHead item={item} />
      <Panel title="换皮选题" desc="保留爽点结构，换掉人设、金手指外形和世界观；每个选题都会和原书做相似点自检。点一个进入选题详情。">
        <IdeasSection busy={reskin.busy} error={reskin.error} result={last} progress={reskin.progress} message={reskin.message}
          onRun={() => void reskin.run()} onOpen={(i) => nav(`/ideas/${i.id}`)} onAll={() => nav('/ideas')} />
      </Panel>
      {last && (
        <Footer>
          <Button variant="secondary" size="lg" loading={reskin.busy} icon={<Lightbulb className="h-4 w-4" />} onClick={() => void reskin.run()}>再生成 3 个</Button>
        </Footer>
      )}
    </>
  )
}

/** 只有正文（没有榜单书）：用单本熔炉出换皮选题 */
function TextReskin({ doc }: { doc: TextDoc }) {
  const nav = useNavigate()
  const { start } = useJobs()
  const key = 'wizard-imitate-text'
  const job = useActiveJob(key)
  const [res, setRes] = useState<FusionResult | null>(null)
  const go = () => start(api.fusionIdeas({ refs: [{ title: doc.title, text: clipBare(doc.text, FUSION_TEXT_LIMIT), weight: 100 }], notes: '仿写立项：只学结构与节奏，换掉人设、金手指外形和世界观', n: 3 }), {
    key, label: '换皮选题', successMsg: (j) => `得到 ${(j.result?.ideas as Idea[] | undefined)?.length ?? 0} 个选题`, onSuccess: (j) => setRes(j.result as FusionResult),
  })
  const started = useRef(false)
  useEffect(() => { if (!started.current && !res && !job) { started.current = true; void go() } }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <Panel title={`换皮《${doc.title}》`} desc="按这段正文的结构与节奏出 3 个皮完全不同的选题。">
        {job ? <Thinking text="正在换皮……" progress={job.progress} message={job.message} rows={1} /> : res ? <FusionResults res={res} onOpen={(i) => nav(`/ideas/${i.id}`)} />
          : <div className="py-6 text-center"><Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={go}>生成换皮选题</Button></div>}
      </Panel>
      {res && !job && <Footer><Button variant="secondary" size="lg" icon={<RefreshCw className="h-4 w-4" />} onClick={go}>再生成一组</Button></Footer>}
    </>
  )
}

// ---------------------------------------------------------------- c) 一键整理

function OrganizePath({ onBack }: { onBack: () => void }) {
  const nav = useNavigate()
  const [step, setStep] = useState(1)
  const [text, setText] = useState('')
  const [gender, setGender] = useState<Gender>('male')
  const [genre, setGenre] = useState('')
  const [idea, setIdea] = useState<Idea | null>(null)
  const { start } = useJobs()
  const key = 'wizard-organize'
  const job = useActiveJob(key)
  const n = bareLen(text)
  const go = () => start(api.organizeIdea({ text, genre: genre.trim() || undefined, gender }), {
    key, label: '整理选题', successMsg: '已整理成选题卡',
    onSuccess: (j) => { const i = j.result?.idea as Idea | undefined; if (i) { setIdea(i); setStep(2); window.scrollTo({ top: 0, behavior: 'smooth' }) } },
  })
  return (
    <>
      <Steps steps={['选择路径', ...PATHS.organize.steps]} current={step} reach={idea ? 2 : 1} onGo={(i) => (i === 0 ? onBack() : setStep(i))} />
      {step === 1 ? (
        <>
          <Panel title="把想法粘进来" desc="脑洞、设定片段、和朋友的聊天记录、零散的笔记都行，AI 整理成书名、一句话卖点、钩子、主线规划。">
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} className="min-h-[260px] text-[14px]"
              placeholder={'例如：\n主角是殡仪馆夜班化妆师，能看到死者最后 7 秒的记忆……\n想写都市悬疑，前期每章破一个小案，后期牵出一个跨越二十年的局……'} />
            <div className="mt-1.5 text-right"><span className={cn('num text-[12px]', text.length > ORGANIZE_LIMIT ? 'font-medium text-danger' : 'text-muted-foreground')}>{text.length.toLocaleString('zh-CN')} / {ORGANIZE_LIMIT.toLocaleString('zh-CN')} 字</span></div>
            <div className="mt-3"><GenderGenre gender={gender} setGender={setGender} genre={genre} setGenre={setGenre} optional /></div>
            {job && <JobInline job={job} className="mt-4" />}
          </Panel>
          <Footer hint={n < 10 ? '至少写 10 个字' : text.length > ORGANIZE_LIMIT ? `超出 ${(text.length - ORGANIZE_LIMIT).toLocaleString('zh-CN')} 字，删短一些` : undefined}>
            <Button variant="primary" size="lg" disabled={n < 10 || text.length > ORGANIZE_LIMIT} loading={!!job} icon={<Wand2 className="h-4 w-4" />} onClick={go}>{job ? '整理中…' : '一键整理'}</Button>
          </Footer>
        </>
      ) : idea ? (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-[15px] font-semibold"><Check className="h-4 w-4 text-success" />已整理成选题</div>
            <Button size="sm" variant="ghost" className="h-9" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => { setStep(1) }}>改一改再整理</Button>
          </div>
          <div className="max-w-xl"><IdeaMini idea={idea} onOpen={() => nav(`/ideas/${idea.id}`)} label="打开选题详情" /></div>
        </>
      ) : null}
    </>
  )
}

// ---------------------------------------------------------------- d) 多本熔炉

interface Ref { key: string; title: string; sub: string; cover?: string | null; item?: RankItem; text?: string; weight: number }
const SLOT_COLORS = ['hsl(var(--primary))', '#2f7fb8', '#c58a1a']

function FusionPath({ onBack }: { onBack: () => void }) {
  const nav = useNavigate()
  const [step, setStep] = useState(1)
  const [src, setSrc] = useState<'rank' | 'paste' | 'upload'>('rank')
  const [refs, setRefs] = useState<Ref[]>([])
  const [doc, setDoc] = useState<TextDoc | null>(null)
  const [notes, setNotes] = useState('')
  const [count, setCount] = useState(3)
  const [res, setRes] = useState<FusionResult | null>(null)
  const [opening, setOpening] = useState<number | null>(null)
  const { start } = useJobs()
  const key = 'wizard-fusion'
  const job = useActiveJob(key)
  const full = refs.length >= 3
  const sum = refs.reduce((s, r) => s + r.weight, 0) || 1
  const pct = (w: number) => Math.round((w / sum) * 100)

  const toggleBook = (i: RankItem) => setRefs((rs) => rs.some((r) => r.key === `b:${i.book_id_ext}`)
    ? rs.filter((r) => r.key !== `b:${i.book_id_ext}`)
    : rs.length >= 3 ? rs : [...rs, { key: `b:${i.book_id_ext}`, title: i.title, sub: `${i.author} · ${i.category}`, cover: i.cover, item: i, weight: 50 }])
  const addDoc = () => {
    if (!doc || full) return
    setRefs((rs) => [...rs, { key: `t:${Date.now()}`, title: doc.title, sub: `${doc.from === 'upload' ? 'TXT' : '粘贴'} · ${bareLen(doc.text).toLocaleString('zh-CN')} 字`, text: clipBare(doc.text, FUSION_TEXT_LIMIT), weight: 50 }])
    setDoc(null)
    toast.success('已投入熔炉')
  }
  const go = () => start(api.fusionIdeas({
    refs: refs.map((r) => (r.item ? { book_id_ext: r.item.book_id_ext, title: r.title, weight: pct(r.weight) } : { title: r.title, text: r.text, weight: pct(r.weight) })),
    notes: notes.trim() || undefined, n: count,
  }), {
    key, label: '熔炉仿写', successMsg: (j) => `炼出 ${(j.result?.ideas as Idea[] | undefined)?.length ?? 0} 个选题`,
    onSuccess: (j) => { setRes(j.result as FusionResult); setStep(3); window.scrollTo({ top: 0, behavior: 'smooth' }) },
  })
  const open = async (i: Idea, k: number) => {
    if (i.id) { nav(`/ideas/${i.id}`); return }
    setOpening(k)
    try {
      const { idea } = await api.ideaFromSeed({ title: i.title, logline: i.logline, selling_points: i.selling_points, genre: i.genre, source: { type: 'fusion', ref: refs.map((r) => r.title).join(' + ') } })
      nav(`/ideas/${idea.id}`)
    } catch (e: any) { toast.error('保存失败', { description: e?.message }) } finally { setOpening(null) }
  }
  const reach = refs.length ? (res ? 3 : 2) : 1

  return (
    <>
      <Steps steps={['选择路径', ...PATHS.fusion.steps]} current={step} reach={reach} onGo={(i) => (i === 0 ? onBack() : setStep(i))} />
      {/* 熔炉槽位（三步都显示） */}
      {step < 3 && (
        <section className="mb-4 rounded-xl border bg-gradient-to-br from-primary-soft/50 via-surface to-surface p-4 shadow-card sm:p-5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-[14.5px] font-semibold"><Layers3 className="h-4 w-4 text-primary" />熔炉<span className="text-[12.5px] font-normal text-muted-foreground">投入 1–3 本参考书{step === 2 ? ' · 拖动权重条调整比例' : ''}</span></div>
            <Badge tone={refs.length ? 'primary' : 'neutral'} className="num">{refs.length}/3 本</Badge>
          </div>
          {refs.length ? (
            <>
              <div className="mb-3 flex h-2.5 overflow-hidden rounded-full bg-muted">
                {refs.map((r, k) => <motion.div key={r.key} layout className="h-full" style={{ width: `${pct(r.weight)}%`, background: SLOT_COLORS[k] }} />)}
              </div>
              <div className="grid gap-2.5 md:grid-cols-3">
                {refs.map((r, k) => (
                  <div key={r.key} className="rounded-xl border bg-surface p-2.5">
                    <div className="flex items-center gap-2.5">
                      {r.item ? <BookCover src={r.cover} title={r.title} size="sm" className="w-[34px] shrink-0" /> : <span className="flex h-11 w-[34px] shrink-0 items-center justify-center rounded-md bg-muted text-primary"><FileText className="h-4 w-4" /></span>}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13.5px] font-semibold">{r.title}</div>
                        <div className="truncate text-[11.5px] text-muted-foreground">{r.sub}</div>
                      </div>
                      <span className="num shrink-0 text-[15px] font-bold" style={{ color: SLOT_COLORS[k] }}>{pct(r.weight)}%</span>
                      <button type="button" aria-label="移出熔炉" onClick={() => setRefs((rs) => rs.filter((x) => x.key !== r.key))} className="-mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></button>
                    </div>
                    {step === 2 && <Slider className="mt-1.5" label={`${r.title} 权重`} min={10} max={100} step={5} value={r.weight} color={SLOT_COLORS[k]} onChange={(v) => setRefs((rs) => rs.map((x) => (x.key === r.key ? { ...x, weight: v } : x)))} />}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="rounded-xl border border-dashed bg-surface/60 px-4 py-6 text-center">
              <div className="text-[14px] font-medium">投入参考书到熔炉</div>
              <div className="mt-1 text-[12.5px] text-muted-foreground">从下方排行榜选择，或粘贴正文、上传 TXT</div>
            </div>
          )}
        </section>
      )}

      {step === 1 && (
        <>
          <Panel>
            <Segmented className="mb-4" value={src} onChange={setSrc} options={[
              { value: 'rank', label: '排行榜搜索' }, { value: 'paste', label: '粘贴正文' }, { value: 'upload', label: '上传 TXT' },
            ]} />
            {src === 'rank' ? (
              <BookPicker selected={refs.filter((r) => r.item).map((r) => r.item!)} max={3 - refs.filter((r) => !r.item).length} onToggle={toggleBook} />
            ) : (
              <>
                <TextSource key={src} mode={src} value={doc} onChange={setDoc} />
                <div className="mt-3 flex justify-end">
                  <Button variant="primary" className="h-10" disabled={!doc || full} icon={<Layers3 className="h-4 w-4" />} onClick={addDoc}>{full ? '熔炉已满（3 本）' : '投入熔炉'}</Button>
                </div>
              </>
            )}
          </Panel>
          <Footer hint={refs.length ? `已投入 ${refs.length} 本` : '至少投入 1 本'}>
            <Button variant="primary" size="lg" disabled={!refs.length} icon={<ArrowRight className="h-4 w-4" />} onClick={() => setStep(2)}>下一步：配比</Button>
          </Footer>
        </>
      )}

      {step === 2 && (
        <>
          <Panel title="补充信息（可选）" desc="会带入熔炉分析与后续立项生成，例如：更偏男频爆款、主角更冷一点、避免校园背景。">
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} className="min-h-[110px]" placeholder="想保留什么、想避开什么……" />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Field label="出几个选题"><Segmented value={String(count)} onChange={(v) => setCount(Number(v))} options={[1, 3, 5].map((n) => ({ value: String(n), label: `${n} 个` }))} /></Field>
            </div>
            {job && <JobInline job={job} className="mt-4" />}
          </Panel>
          <Footer hint={refs.length ? refs.map((r) => `${r.title} ${pct(r.weight)}%`).join(' · ') : '先投入参考书'}>
            <Button variant="ghost" size="lg" onClick={() => setStep(1)}>返回上一步</Button>
            <Button variant="primary" size="lg" disabled={!refs.length} loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={go}>{job ? '熔炼中…' : '开始熔炼'}</Button>
          </Footer>
        </>
      )}

      {step === 3 && res && (
        <>
          <ResultHead n={res.ideas?.length ?? 0} onAgain={() => setStep(2)} />
          <FusionResults res={res} onOpen={open} opening={opening} />
        </>
      )}
    </>
  )
}

function FusionResults({ res, onOpen, opening }: { res: FusionResult; onOpen: (i: Idea, k: number) => void; opening?: number | null }) {
  const ideas = res.ideas ?? []
  return (
    <div className="space-y-3">
      {res.dropped > 0 && (
        <div className="flex items-start gap-2 rounded-xl border border-warning/25 bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning">
          <AlertTriangle className="mt-[2px] h-4 w-4 shrink-0" /><span>有 {res.dropped} 个结果和参考书太像或不完整，已丢弃。</span>
        </div>
      )}
      {ideas.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {ideas.map((i, k) => <IdeaMini key={i.id || k} idea={i} busy={opening === k} label={i.id ? '打开' : '保存并打开'} onOpen={() => onOpen(i, k)} />)}
        </div>
      ) : <div className="rounded-xl border border-dashed px-4 py-8 text-center text-[13px] text-muted-foreground">这次没有可用的结果，换个配比或补充说明再试</div>}
      <Warnings items={res.warnings} />
    </div>
  )
}

