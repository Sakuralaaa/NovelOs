import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Copy, LogOut, ShieldCheck, Eye, EyeOff, KeyRound, Moon, Pencil, Plug, Plus, Radar, Route, Sun, Trash2, XCircle, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Select, type Opt } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tag-input'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { useChannels } from '@/hooks/queries'
import { useAuth } from '@/components/auth/AuthGate'
import { toggleTheme, useTheme } from '@/hooks/useTheme'
import { api, qk } from '@/lib/api'
import type { Channel, RouteKey, Routing } from '@/lib/types'
import { cn } from '@/lib/utils'

const PRESETS = [
  { key: 'openai', name: 'OpenAI', base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4o-mini', 'text-embedding-3-small', 'gpt-image-1'], color: '#10a37f' },
  { key: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', models: ['deepseek-chat', 'deepseek-reasoner'], color: '#4d6bfe' },
  { key: 'qwen', name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-plus', 'qwen-max', 'qwen-turbo', 'text-embedding-v3'], color: '#615ced' },
  { key: 'kimi', name: 'Kimi', base_url: 'https://api.moonshot.cn/v1', models: ['kimi-latest', 'moonshot-v1-32k', 'moonshot-v1-128k'], color: '#1f1f1f' },
  { key: 'openrouter', name: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', models: ['openai/gpt-4o', 'anthropic/claude-sonnet-4', 'deepseek/deepseek-chat'], color: '#6467f2' },
  { key: 'custom', name: '自定义', base_url: '', models: [], color: '#64748b' },
]

const ROUTES: { key: RouteKey; label: string; desc: string }[] = [
  { key: 'planner', label: '规划', desc: '选题、设定、大纲。建议用推理能力强的模型' },
  { key: 'writer', label: '正文写作', desc: '最费 token 的环节，建议文笔好、长上下文的模型' },
  { key: 'reviewer', label: '审稿', desc: '证据式审稿与人味修整，可用性价比模型' },
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
            action={<div className="flex flex-wrap justify-center gap-2">{PRESETS.slice(0, 5).map((p) => <Button key={p.key} size="sm" onClick={() => setEditing({ id: 0, name: p.name, base_url: p.base_url, models: p.models, api_key_masked: '', enabled: true })}><span className="h-2 w-2 rounded-full" style={{ background: p.color }} />{p.name}</Button>)}</div>} />
        ) : (
          <div className="space-y-2.5">
            {q.data.map((c) => {
              const t = tests[c.id]
              return (
                <div key={c.id} className={cn('rounded-xl p-4 transition hairline', !c.enabled && 'opacity-60')}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">{c.name}</span>
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
  const [f, setF] = useState({ name: '', base_url: '', api_key: '', models: [] as string[] })
  const [preset, setPreset] = useState('custom')
  const [show, setShow] = useState(false)
  const [cur, setCur] = useState<typeof value>(null)
  if (value !== cur) {
    setCur(value)
    if (value && value !== 'new') { setF({ name: value.name, base_url: value.base_url, api_key: '', models: value.models }); setPreset(PRESETS.find((p) => p.base_url === value.base_url)?.key ?? 'custom') }
    else if (value === 'new') { setF({ name: '', base_url: '', api_key: '', models: [] }); setPreset('custom') }
  }
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), base_url: f.base_url.trim().replace(/\/+$/, ''), models: f.models, ...(f.api_key ? { api_key: f.api_key.trim() } : {}) }
      return isNew ? api.createChannel({ ...body, api_key: f.api_key.trim() }) : api.updateChannel((value as Channel).id, body)
    },
    meta: { errorTitle: '保存失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.channels }); qc.invalidateQueries({ queryKey: qk.status }); toast.success(isNew ? '渠道已添加，记得到「任务路由」里分配模型' : '已保存'); onClose() },
  })
  const p = PRESETS.find((x) => x.key === preset)!
  const valid = f.name.trim() && /^https?:\/\//.test(f.base_url.trim()) && (!isNew || f.api_key.trim()) && f.models.length > 0
  return (
    <Sheet open={!!value} onOpenChange={(o) => !o && onClose()} title={isNew ? '添加模型渠道' : `编辑：${(value as Channel | null)?.name ?? ''}`}
      footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" disabled={!valid} loading={m.isPending} onClick={() => m.mutate()}>保存</Button></>}>
      <div className="space-y-5">
        <Field label="服务商">
          <div className="grid grid-cols-3 gap-2">
            {PRESETS.map((x) => (
              <button key={x.key} onClick={() => { setPreset(x.key); if (x.key !== 'custom') setF({ ...f, name: f.name && !PRESETS.some((pp) => pp.name === f.name) ? f.name : x.name, base_url: x.base_url, models: f.models.length ? f.models : x.models.slice(0, 2) }) }}
                className={cn('flex h-10 items-center justify-center gap-1.5 rounded-lg border text-[13px] font-medium transition', preset === x.key ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-subtle')}>
                <span className="h-2 w-2 rounded-full" style={{ background: x.color }} />{x.name}
              </button>
            ))}
          </div>
        </Field>
        <Field label="名称"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="例如：我的 DeepSeek" /></Field>
        <Field label="Base URL"><Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="https://api.example.com/v1" className="font-mono text-[13px]" /></Field>
        <Field label="API Key" hint={isNew ? undefined : `当前：${(value as Channel)?.api_key_masked || '未设置'}`}>
          <div className="relative">
            <Input type={show ? 'text' : 'password'} value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} placeholder={isNew ? 'sk-…' : '留空则不修改'} className="pr-9 font-mono text-[13px]" autoComplete="off" />
            <button type="button" onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground" aria-label={show ? '隐藏' : '显示'}>{show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>
          </div>
        </Field>
        <Field label="模型列表">
          <TagInput value={f.models} onChange={(v) => setF({ ...f, models: v })} placeholder="例如：deepseek-chat" suggestions={p.models} />
        </Field>
      </div>
    </Sheet>
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
              <div key={x.key} className="grid min-h-[60px] items-center gap-3 px-5 py-3 sm:grid-cols-[1fr_240px]">
                <div className="text-[13.5px] font-medium">{x.label}</div>
                <Select value={r[x.key]} onChange={(v) => { setR({ ...r, [x.key]: v }); setDirty(true) }} options={opts} allowEmpty emptyLabel={noCh ? '演示模式（mock）' : '自动（使用默认）'} placeholder={noCh ? '演示模式（mock）' : '选择模型'} />
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
