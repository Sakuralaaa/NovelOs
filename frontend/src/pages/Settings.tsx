import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckCircle2, Copy, Download, LogOut, ShieldCheck, Eye, EyeOff, KeyRound, Moon, Pencil, Plug, Plus, Radar, Route, Search, Sun, Trash2, XCircle, Zap } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Select, type Opt } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { TagInput } from '@/components/ui/tag-input'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { useChannels } from '@/hooks/queries'
import { useAuth } from '@/components/auth/AuthGate'
import { toggleTheme, useTheme } from '@/hooks/useTheme'
import { api, qk } from '@/lib/api'
import type { ApiFormat, Channel, ImageMode, RouteKey, Routing } from '@/lib/types'
import { cn } from '@/lib/utils'

const PRESETS: { key: string; name: string; base_url: string; format: ApiFormat; models: string[]; color: string }[] = [
  { key: 'openai', name: 'OpenAI', base_url: 'https://api.openai.com/v1', format: 'openai', models: ['gpt-4o', 'gpt-4o-mini', 'text-embedding-3-small', 'gpt-image-1'], color: '#10a37f' },
  { key: 'anthropic', name: 'Anthropic', base_url: 'https://api.anthropic.com/v1', format: 'anthropic', models: ['claude-sonnet-4-5', 'claude-opus-4-1'], color: '#d97757' },
  { key: 'gemini', name: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta', format: 'gemini', models: ['gemini-2.5-pro', 'gemini-2.5-flash'], color: '#4285f4' },
  { key: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', format: 'openai', models: ['deepseek-chat', 'deepseek-reasoner'], color: '#4d6bfe' },
  { key: 'qwen', name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', format: 'openai', models: ['qwen-plus', 'qwen-max', 'text-embedding-v3'], color: '#615ced' },
  { key: 'openrouter', name: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', format: 'openai', models: ['openai/gpt-4o', 'anthropic/claude-sonnet-4'], color: '#6467f2' },
]

const FORMATS: { value: ApiFormat; label: string; path: string }[] = [
  { value: 'openai', label: 'OpenAI Chat', path: '/chat/completions' },
  { value: 'responses', label: 'OpenAI Responses', path: '/responses' },
  { value: 'anthropic', label: 'Anthropic', path: '/messages' },
  { value: 'gemini', label: 'Gemini', path: '/models/{model}:generateContent' },
]
const fmtLabel = (f?: ApiFormat) => FORMATS.find((x) => x.value === (f ?? 'openai'))?.label ?? 'OpenAI Chat'

const STRICT: RouteKey[] = ['search', 'embedding', 'image']

const ROUTES: { key: RouteKey; label: string; desc: string }[] = [
  { key: 'planner', label: '规划', desc: '选题、设定、大纲。建议用推理能力强的模型' },
  { key: 'writer', label: '正文写作', desc: '最费 token 的环节，建议文笔好、长上下文的模型' },
  { key: 'reviewer', label: '审稿', desc: '证据式审稿与人味修整，可用性价比模型' },
  { key: 'search', label: '联网搜索', desc: '拿不准的现实细节先联网查证' },
  { key: 'embedding', label: '向量检索', desc: '长篇记忆回读，需要 embedding 模型' },
  { key: 'image', label: '生图', desc: '封面生成，需要支持 images 接口的模型' },
]

export default function SettingsPage() {
  return (
    <div className="page">
      <PageHeader title="设置" />
      <div className="space-y-6">
        <Channels />
        <RoutingCard />
        <WritingCard />
        <RadarCard />
        <AccountCard />
        <Appearance />
      </div>
    </div>
  )
}

function Channels() {
  const q = useChannels()
  const [editing, setEditing] = useState<Channel | 'new' | null>(null)
  const [del, setDel] = useState<Channel | null>(null)
  const [tests, setTests] = useState<Record<number, { ok: boolean; latency_ms: number; error?: string } | 'loading'>>({})
  const qc = useQueryClient()
  const toggle = useMutation({
    mutationFn: (c: Channel) => api.updateChannel(c.id, { enabled: !c.enabled }),
    meta: { errorTitle: '更新失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.channels }); qc.invalidateQueries({ queryKey: qk.status }) },
  })
  const rm = useMutation({
    mutationFn: (id: number) => api.deleteChannel(id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.channels }); qc.invalidateQueries({ queryKey: qk.status }); qc.invalidateQueries({ queryKey: qk.routing }); toast.success('渠道已删除'); setDel(null) },
  })
  const test = async (c: Channel) => {
    setTests((t) => ({ ...t, [c.id]: 'loading' }))
    try {
      const r = await api.testChannel(c.id)
      setTests((t) => ({ ...t, [c.id]: r }))
      r.ok ? toast.success(`${c.name} 连接正常`, { description: `延迟 ${r.latency_ms} ms` }) : toast.error(`${c.name} 连接失败`, { description: r.error })
    } catch (e: any) {
      setTests((t) => ({ ...t, [c.id]: { ok: false, latency_ms: 0, error: e.message } }))
      toast.error('测试失败', { description: e.message })
    }
  }
  return (
    <Card>
      <CardHeader divider title="模型渠道" icon={<Plug className="h-4 w-4" />} action={<Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setEditing('new')}>添加渠道</Button>} />
      <CardBody className="pt-5">
        {q.isLoading ? <div className="space-y-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div> : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data?.length ? (
          <EmptyState compact kind="channel" className="border-0 bg-transparent" title="还没有模型渠道"
            action={<div className="flex flex-wrap justify-center gap-2">{PRESETS.map((p) => <Button key={p.key} size="sm" onClick={() => setEditing({ id: 0, name: p.name, base_url: p.base_url, models: p.models.slice(0, 2), api_key_masked: '', enabled: true, api_format: p.format })}><span className="h-2 w-2 rounded-full" style={{ background: p.color }} />{p.name}</Button>)}</div>} />
        ) : (
          <div className="space-y-2.5">
            {q.data.map((c) => {
              const t = tests[c.id]
              return (
                <div key={c.id} className={cn('rounded-xl p-4 transition hairline', !c.enabled && 'opacity-60')}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-semibold">{c.name}</span>
                        <Badge tone="outline">{fmtLabel(c.api_format)}</Badge>
                        {c.enabled ? <Badge tone="success" dot>启用</Badge> : <Badge>已停用</Badge>}
                        {t && t !== 'loading' && (t.ok ? <Badge tone="success"><CheckCircle2 className="h-3 w-3" />{t.latency_ms} ms</Badge> : <Badge tone="danger"><XCircle className="h-3 w-3" />失败</Badge>)}
                      </div>
                      <div className="mt-1 truncate font-mono text-[12px] text-muted-foreground">{c.base_url}</div>
                      <div className="mt-0.5 flex items-center gap-1 font-mono text-[12px] text-muted-foreground"><KeyRound className="h-3 w-3" />{c.api_key_masked || '未设置'}</div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" loading={t === 'loading'} icon={<Zap className="h-3.5 w-3.5" />} onClick={() => test(c)}>测试连接</Button>
                      <Button size="icon-sm" variant="ghost" onClick={() => setEditing(c)} aria-label="编辑"><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button size="icon-sm" variant="ghost" onClick={() => setDel(c)} aria-label="删除"><Trash2 className="h-3.5 w-3.5" /></Button>
                      <Switch checked={c.enabled} onCheckedChange={() => toggle.mutate(c)} className="ml-1" />
                    </div>
                  </div>
                  {t && t !== 'loading' && !t.ok && t.error && <p className="mt-2 rounded-md bg-danger-soft px-2.5 py-1.5 text-xs text-danger">{t.error}</p>}
                  <div className="mt-3 flex flex-wrap gap-1.5">{c.models.map((m) => <span key={m} className="rounded-md bg-muted px-2 py-0.5 font-mono text-[11.5px]">{m}</span>)}</div>
                </div>
              )
            })}
          </div>
        )}
      </CardBody>
      <ChannelSheet value={editing} onClose={() => setEditing(null)} />
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent title={`删除渠道「${del?.name}」？`} desc="使用它的任务路由会被清空。" footer={<><Button variant="ghost" onClick={() => setDel(null)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => del && rm.mutate(del.id)}>删除</Button></>} />
      </Dialog>
    </Card>
  )
}

function ChannelSheet({ value, onClose }: { value: Channel | 'new' | null; onClose: () => void }) {
  const isNew = value === 'new' || (value !== null && value.id === 0)
  const empty = { name: '', base_url: '', api_key: '', models: [] as string[], api_format: 'openai' as ApiFormat }
  const [f, setF] = useState(empty)
  const [show, setShow] = useState(false)
  const [fetched, setFetched] = useState<string[] | null>(null)
  const [cur, setCur] = useState<typeof value>(null)
  if (value !== cur) {
    setCur(value)
    setFetched(null)
    if (value && value !== 'new') setF({ name: value.name, base_url: value.base_url, api_key: '', models: value.models, api_format: value.api_format ?? 'openai' })
    else if (value === 'new') setF(empty)
  }
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), base_url: f.base_url.trim().replace(/\/+$/, ''), models: f.models, api_format: f.api_format, ...(f.api_key ? { api_key: f.api_key.trim() } : {}) }
      return isNew ? api.createChannel({ ...body, api_key: f.api_key.trim() }) : api.updateChannel((value as Channel).id, body)
    },
    meta: { errorTitle: '保存失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.channels }); qc.invalidateQueries({ queryKey: qk.status }); toast.success(isNew ? '渠道已添加，记得到「任务路由」里分配模型' : '已保存'); onClose() },
  })
  const fetchM = useMutation({
    mutationFn: () => api.fetchModels({
      base_url: f.base_url.trim().replace(/\/+$/, ''),
      api_format: f.api_format,
      ...(f.api_key.trim() ? { api_key: f.api_key.trim() } : {}),
      ...(!isNew && !f.api_key.trim() ? { channel_id: (value as Channel).id } : {}),
    }),
    meta: { errorTitle: '拉取模型失败' },
    onSuccess: (d) => setFetched(d.models),
  })
  const canFetch = /^https?:\/\//.test(f.base_url.trim()) && (!isNew || !!f.api_key.trim())
  const preset = PRESETS.find((x) => x.base_url === f.base_url.trim().replace(/\/+$/, ''))
  const fmt = FORMATS.find((x) => x.value === f.api_format)!
  const valid = f.name.trim() && /^https?:\/\//.test(f.base_url.trim()) && (!isNew || f.api_key.trim()) && f.models.length > 0
  const applyPreset = (x: (typeof PRESETS)[number]) => setF({
    ...f,
    name: f.name.trim() && !PRESETS.some((pp) => pp.name === f.name) ? f.name : x.name,
    base_url: x.base_url, api_format: x.format, models: f.models.length ? f.models : x.models.slice(0, 2),
  })
  return (
    <Sheet open={!!value} onOpenChange={(o) => !o && onClose()} title={isNew ? '添加模型渠道' : `编辑：${(value as Channel | null)?.name ?? ''}`}
      footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" disabled={!valid} loading={m.isPending} onClick={() => m.mutate()}>保存</Button></>}>
      <div className="space-y-5">
        {isNew && (
          <Field label="快速填充">
            <div className="grid grid-cols-3 gap-2">
              {PRESETS.map((x) => (
                <button key={x.key} type="button" onClick={() => applyPreset(x)}
                  className={cn('flex h-10 min-w-0 items-center justify-center gap-1.5 rounded-lg border px-2 text-[13px] font-medium transition', preset?.key === x.key ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-subtle')}>
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: x.color }} /><span className="truncate">{x.name}</span>
                </button>
              ))}
            </div>
          </Field>
        )}
        <Field label="名称"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="例如：我的中转站" /></Field>
        <Field label="接口格式">
          <div className="grid grid-cols-2 gap-2">
            {FORMATS.map((x) => (
              <button key={x.value} type="button" onClick={() => setF({ ...f, api_format: x.value })}
                className={cn('flex h-10 items-center justify-center rounded-lg border px-2 text-[13px] font-medium transition', f.api_format === x.value ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-subtle')}>
                {x.label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Base URL">
          <Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder={f.api_format === 'gemini' ? 'https://generativelanguage.googleapis.com/v1beta' : 'https://api.example.com/v1'} className="font-mono text-[13px]" />
          {/^https?:\/\//.test(f.base_url.trim()) && <div className="mt-1.5 truncate font-mono text-[11.5px] text-muted-foreground">{f.base_url.trim().replace(/\/+$/, '')}{fmt.path}</div>}
        </Field>
        <Field label="API Key" hint={isNew ? undefined : `当前：${(value as Channel)?.api_key_masked || '未设置'}`}>
          <div className="relative">
            <Input type={show ? 'text' : 'password'} value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} placeholder={isNew ? 'sk-…' : '留空则不修改'} className="pr-9 font-mono text-[13px]" autoComplete="off" />
            <button type="button" onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground" aria-label={show ? '隐藏' : '显示'}>{show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>
          </div>
        </Field>
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[13px] font-medium text-foreground/85">模型列表{f.models.length > 0 && <span className="ml-1 text-muted-foreground">{f.models.length}</span>}</span>
            <Button size="sm" variant="ghost" className="-mr-2 h-7" disabled={!canFetch} loading={fetchM.isPending} icon={<Download className="h-3.5 w-3.5" />} onClick={() => fetchM.mutate()}>拉取模型</Button>
          </div>
          <TagInput value={f.models} onChange={(v) => setF({ ...f, models: v })} placeholder="输入模型 ID 回车添加" suggestions={preset?.models} />
        </div>
      </div>
      <ModelPicker models={fetched} selected={f.models} onClose={() => setFetched(null)}
        onConfirm={(v) => { setF({ ...f, models: v }); setFetched(null) }} />
    </Sheet>
  )
}

type Kind = 'all' | 'chat' | 'reason' | 'search' | 'embed' | 'image'
const KINDS: { key: Kind; label: string }[] = [
  { key: 'all', label: '全部' }, { key: 'chat', label: '对话' }, { key: 'reason', label: '推理' },
  { key: 'search', label: '联网' }, { key: 'embed', label: '向量' }, { key: 'image', label: '生图' },
]
const kindOf = (m: string): Exclude<Kind, 'all'> => {
  const x = m.toLowerCase()
  if (/embed|bge|m3e|text-embedding/.test(x)) return 'embed'
  if (/image|imagine|dall-?e|flux|wanx|sdxl|stable-diffusion|midjourney|seedream|cogview|kolors/.test(x)) return 'image'
  if (/search|sonar|online|multi-agent|web/.test(x)) return 'search'
  if (/reason|think|\bo[134](-|$)|r1|qwq|deepseek-reasoner/.test(x)) return 'reason'
  return 'chat'
}

function ModelPicker({ models, selected, onConfirm, onClose }: {
  models: string[] | null; selected: string[]; onConfirm: (v: string[]) => void; onClose: () => void
}) {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const [pick, setPick] = useState<Set<string>>(new Set())
  const [cur, setCur] = useState<string[] | null>(null)
  if (models !== cur) { setCur(models); setPick(new Set(selected)); setQ(''); setKind('all') }
  const all = models ?? []
  const counts = all.reduce<Record<string, number>>((a, m) => { const k = kindOf(m); a[k] = (a[k] ?? 0) + 1; return a }, {})
  const list = all.filter((m) => (kind === 'all' || kindOf(m) === kind) && m.toLowerCase().includes(q.trim().toLowerCase()))
  const allOn = list.length > 0 && list.every((m) => pick.has(m))
  const toggle = (m: string) => setPick((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n })
  const toggleAll = () => setPick((s) => { const n = new Set(s); list.forEach((m) => (allOn ? n.delete(m) : n.add(m))); return n })
  // 保持原有顺序，新勾选的按列表顺序追加；手填但接口里没有的模型保留
  const result = () => [...selected.filter((m) => pick.has(m) || !all.includes(m)), ...all.filter((m) => pick.has(m) && !selected.includes(m))]
  return (
    <Dialog open={!!models} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={`选择模型（共 ${all.length} 个）`}
        footer={<div className="flex w-full items-center justify-between gap-2">
          <span className="text-[13px] text-muted-foreground">已选 {pick.size}</span>
          <div className="flex gap-2"><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" onClick={() => onConfirm(result())}>确定</Button></div>
        </div>}>
        <div className="sticky -top-4 z-10 -mx-6 -mt-4 space-y-3 bg-popover px-6 pb-3 pt-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索模型" className="pl-9 font-mono text-[13px]" />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {KINDS.filter((k) => k.key === 'all' || counts[k.key]).map((k) => (
              <button key={k.key} type="button" onClick={() => setKind(k.key)}
                className={cn('h-7 rounded-full border px-3 text-[12.5px] transition', kind === k.key ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-subtle')}>
                {k.label}<span className="ml-1 tabular-nums opacity-60">{k.key === 'all' ? all.length : counts[k.key]}</span>
              </button>
            ))}
            <button type="button" onClick={toggleAll} disabled={!list.length} className="ml-auto h-7 rounded-md px-2 text-[12.5px] text-primary hover:bg-primary-soft disabled:opacity-40">{allOn ? '取消全选' : '全选'}</button>
          </div>
        </div>
        {!list.length ? <div className="py-10 text-center text-[13px] text-muted-foreground">没有匹配的模型</div> : (
          <div className="grid gap-1 sm:grid-cols-2">
            {list.map((m) => {
              const on = pick.has(m)
              return (
                <button key={m} type="button" onClick={() => toggle(m)}
                  className={cn('flex h-9 min-w-0 items-center gap-2.5 rounded-md px-2.5 text-left transition', on ? 'bg-primary-soft' : 'hover:bg-subtle')}>
                  <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border transition', on ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-surface')}>
                    {on && <Check className="h-3 w-3" weight="bold" />}
                  </span>
                  <span className="truncate font-mono text-[12.5px]" title={m}>{m}</span>
                </button>
              )
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function RoutingCard() {
  const { data: channels } = useChannels()
  const q = useQuery({ queryKey: qk.routing, queryFn: api.routing })
  const [r, setR] = useState<Routing | null>(null)
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (q.data && !dirty) setR(q.data) }, [q.data, dirty])
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (b: Routing) => api.saveRouting(b),
    meta: { errorTitle: '保存路由失败' },
    onSuccess: (d) => { qc.setQueryData(qk.routing, d); setDirty(false); toast.success('任务路由已保存') },
  })
  const opts: Opt[] = (channels ?? []).filter((c) => c.enabled).flatMap((c) => c.models.map((mm) => ({ value: `${c.id}:${mm}`, label: <span className="font-mono text-[12.5px]">{mm}</span>, group: c.name })))
  const noCh = !opts.length
  return (
    <Card>
      <CardHeader divider title="任务路由" icon={<Route className="h-4 w-4" />} action={dirty && <Button size="sm" variant="primary" loading={m.isPending} onClick={() => r && m.mutate(r)}>保存</Button>} />
      <CardBody className="p-0">
        {q.isLoading || !r ? <Skeleton className="m-5 h-60" /> : (
          <div className="divide-y divide-border/70">
            {ROUTES.map((x) => (
              <div key={x.key} className="grid min-h-[60px] items-start gap-3 px-5 py-3 sm:grid-cols-[1fr_240px] sm:items-center">
                <div className="text-[13.5px] font-medium">{x.label}</div>
                <div className="space-y-2">
                  <Select value={r[x.key]} onChange={(v) => { setR({ ...r, [x.key]: v }); setDirty(true) }} options={opts} allowEmpty emptyLabel={noCh ? '演示模式（mock）' : STRICT.includes(x.key) ? '不使用' : '自动（使用默认）'} placeholder={noCh ? '演示模式（mock）' : '选择模型'} />
                  {x.key === 'image' && r.image && (
                    <Segmented size="sm" block value={r.image_mode ?? 'images'} onChange={(v: ImageMode) => { setR({ ...r, image_mode: v }); setDirty(true) }}
                      options={[{ value: 'images', label: '生图接口' }, { value: 'chat', label: '对话接口' }]} />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function WritingCard() {
  const q = useQuery({ queryKey: qk.writing, queryFn: api.writingSettings, retry: false })
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: api.saveWritingSettings,
    meta: { errorTitle: '保存失败' },
    onSuccess: (d) => { qc.setQueryData(qk.writing, d); localStorage.setItem('novelos-variants', String(d.default_variants)); toast.success('写作偏好已保存') },
  })
  if (q.isError) return null
  const c = q.data
  return (
    <Card>
      <CardHeader divider title="写作偏好" icon={<Copy className="h-4 w-4" />} />
      <CardBody className="p-0">
        {!c ? <Skeleton className="m-5 h-28" /> : (
          <div className="divide-y divide-border/70">
            <div className="flex min-h-[60px] items-center justify-between gap-4 px-5 py-3">
              <div className="text-[13.5px] font-medium">默认版本数</div>
              <div className="w-[240px]"><Select value={String(c.default_variants)} onChange={(v) => v && m.mutate({ default_variants: Number(v) as 1 | 2 | 3 })} options={[1, 2, 3].map((n) => ({ value: String(n), label: `${n} 个版本` }))} /></div>
            </div>
            <label className="flex min-h-[60px] cursor-pointer items-center justify-between gap-4 px-5 py-3">
              <div className="text-[13.5px] font-medium">自动采纳最高分版本</div>
              <Switch checked={c.auto_adopt_best} onCheckedChange={(v) => m.mutate({ auto_adopt_best: v })} />
            </label>
            <label className="flex min-h-[60px] cursor-pointer items-center justify-between gap-4 px-5 py-3">
              <div className="text-[13.5px] font-medium">审稿通过后自动提交</div>
              <Switch checked={c.auto_commit} onCheckedChange={(v) => m.mutate({ auto_commit: v })} />
            </label>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function RadarCard() {
  const q = useQuery({ queryKey: qk.radarConfig, queryFn: api.radarConfig })
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: api.saveRadarConfig,
    meta: { errorTitle: '保存失败' },
    onSuccess: (d) => { qc.setQueryData(qk.radarConfig, d); toast.success('雷达设置已保存') },
  })
  const c = q.data
  return (
    <Card>
      <CardHeader divider title="热点雷达" icon={<Radar className="h-4 w-4" />} />
      <CardBody className="p-0">
        {!c ? <Skeleton className="m-5 h-20" /> : (
          <div className="divide-y divide-border/70">
            <label className="flex min-h-[60px] cursor-pointer items-center justify-between gap-4 px-5 py-3">
              <div className="text-[13.5px] font-medium">每日自动抓取</div>
              <Switch checked={c.enabled} onCheckedChange={(v) => m.mutate({ ...c, enabled: v })} />
            </label>
            <div className={cn('flex min-h-[60px] items-center justify-between gap-4 px-5 py-3', !c.enabled && 'opacity-50')}>
              <div className="text-[13.5px] font-medium">抓取时间</div>
              <div className="w-[240px]"><Select value={String(c.daily_hour)} onChange={(v) => v && m.mutate({ ...c, daily_hour: Number(v) })} options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `每天 ${String(h).padStart(2, '0')}:00` }))} /></div>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function Appearance() {
  const t = useTheme()
  return (
    <Card>
      <CardHeader divider title="外观" icon={t === 'dark' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />} />
      <CardBody className="p-0">
        <div className="flex min-h-[60px] items-center justify-between px-5 py-3">
          <div className="text-[13.5px] font-medium">深色模式</div>
          <Switch checked={t === 'dark'} onCheckedChange={toggleTheme} />
        </div>
      </CardBody>
    </Card>
  )
}

function AccountCard() {
  const { data: auth } = useAuth()
  const qc = useQueryClient()
  const [f, setF] = useState({ current: '', next: '', confirm: '' })
  const min = auth?.min_password_len ?? 8
  const err = f.next && f.next.length < min ? `至少 ${min} 位` : f.confirm && f.confirm !== f.next ? '两次输入不一致' : ''
  const m = useMutation({
    mutationFn: () => api.changePassword(f.current, f.next),
    meta: { errorTitle: '修改失败' },
    onSuccess: () => { setF({ current: '', next: '', confirm: '' }); toast.success('密码已修改，其他设备需要重新登录') },
  })
  const logout = async () => { try { await api.logout() } finally { qc.clear(); qc.invalidateQueries({ queryKey: qk.auth }) } }
  if (!auth?.enabled) return null
  return (
    <Card>
      <CardHeader divider title="账户安全" icon={<ShieldCheck className="h-4 w-4" />} action={<Button size="sm" variant="ghost" icon={<LogOut className="h-3.5 w-3.5" />} onClick={logout}>退出登录</Button>} />
      <CardBody className="pt-5">
        {auth.managed_by_env ? (
          <div className="text-[13.5px] text-muted-foreground">密码由 .env 中的 NOVELOS_PASSWORD 管理</div>
        ) : (
          <form className="grid gap-4 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); if (!err && f.current && f.next && f.confirm) m.mutate() }}>
            <Field label="当前密码"><Input type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
            <Field label="新密码"><Input type="password" autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} /></Field>
            <Field label="确认新密码" hint={err ? <span className="text-danger">{err}</span> : undefined}><Input type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></Field>
            <div className="flex justify-end sm:col-span-3">
              <Button type="submit" variant="primary" loading={m.isPending} disabled={!!err || !f.current || !f.next || !f.confirm}>修改密码</Button>
            </div>
          </form>
        )}
      </CardBody>
    </Card>
  )
}
