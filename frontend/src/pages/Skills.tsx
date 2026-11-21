import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Download, Pencil, Plus, RotateCcw, Search, Sparkles, Trash2 } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Switch } from '@/components/ui/switch'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { api, qk } from '@/lib/api'
import type { SkillItem } from '@/lib/types'
import { cn } from '@/lib/utils'

const SOURCE_LABEL: Record<SkillItem['source'], string> = {
  builtin: '内置',
  github: 'GitHub',
  custom: '自建',
}

export default function SkillsPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: qk.skills, queryFn: () => api.skills() })
  const [stage, setStage] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<SkillItem | 'new' | null>(null)
  const [ghOpen, setGhOpen] = useState(false)
  const [del, setDel] = useState<SkillItem | null>(null)

  const stages = q.data?.stages ?? []
  const stageMap = useMemo(() => Object.fromEntries(stages.map((s) => [s.key, s.label])), [stages])
  const items = useMemo(() => {
    const all = q.data?.items ?? []
    const kw = search.trim().toLowerCase()
    return all.filter((sk) => {
      if (stage !== 'all' && sk.stage !== stage) return false
      if (kw && !`${sk.name} ${sk.description} ${sk.body ?? ''}`.toLowerCase().includes(kw)) return false
      return true
    })
  }, [q.data, stage, search])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: qk.skills })
    qc.invalidateQueries({ queryKey: ['book-skills'] })
  }

  const toggle = useMutation({
    mutationFn: (sk: SkillItem) => api.updateSkill(sk.id, { enabled: !sk.enabled }),
    meta: { errorTitle: '更新失败' },
    onSuccess: invalidate,
  })
  const dup = useMutation({
    mutationFn: (id: number) => api.duplicateSkill(id),
    meta: { errorTitle: '复制失败' },
    onSuccess: (sk) => { invalidate(); toast.success(`已复制「${sk.name}」`) },
  })
  const reset = useMutation({
    mutationFn: (id: number) => api.resetSkill(id),
    meta: { errorTitle: '重置失败' },
    onSuccess: (sk) => { invalidate(); toast.success(`已重置「${sk.name}」`) },
  })
  const rm = useMutation({
    mutationFn: (id: number) => api.deleteSkill(id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { invalidate(); setDel(null); toast.success('技能已删除') },
  })

  return (
    <div className="page">
      <PageHeader
        title="技能库"
        desc="可插拔的写作、规划与拆书方法论。手动写作和外接 Agent 共用同一套；在每本书的「文风」页可单独勾选本书启用的技能。"
        actions={
          <>
            <Button icon={<Download className="h-4 w-4" />} onClick={() => setGhOpen(true)}>从 GitHub 导入</Button>
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing('new')}>新建技能</Button>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1 max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索技能名称或正文…" className="pl-9" />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setStage('all')}
            className={cn('h-8 rounded-full border px-3 text-xs transition', stage === 'all' ? 'border-primary bg-primary-soft font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
          >
            全部 ({q.data?.items.length ?? 0})
          </button>
          {stages.map((st) => {
            const cnt = (q.data?.items ?? []).filter((x) => x.stage === st.key).length
            if (!cnt && stage !== st.key) return null
            return (
              <button
                key={st.key}
                type="button"
                onClick={() => setStage(st.key)}
                className={cn('h-8 rounded-full border px-3 text-xs transition', stage === st.key ? 'border-primary bg-primary-soft font-medium text-primary' : 'text-muted-foreground hover:text-foreground')}
              >
                {st.label} ({cnt})
              </button>
            )
          })}
        </div>
      </div>

      {q.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-36 rounded-xl" />)}</div>
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !items.length ? (
        <EmptyState kind="style" title="没有匹配的技能" action={<Button variant="primary" onClick={() => setEditing('new')}>新建技能</Button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.map((sk) => (
            <Card key={sk.id} className={cn('transition', !sk.enabled && 'opacity-60')}>
              <CardBody className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                      <h3 className="truncate text-[14.5px] font-semibold">{sk.name}</h3>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge tone="primary">{stageMap[sk.stage] ?? sk.stage}</Badge>
                      <Badge tone="outline">{SOURCE_LABEL[sk.source] ?? sk.source}</Badge>
                      {sk.is_default && <Badge tone="success">默认启用</Badge>}
                      <span className="num text-[11.5px] text-muted-foreground">{sk.chars.toLocaleString()} 字</span>
                      {sk.ref_count > 0 && <span className="text-[11.5px] text-muted-foreground">· {sk.ref_count} 份参考</span>}
                    </div>
                  </div>
                  <Switch checked={sk.enabled} onCheckedChange={() => toggle.mutate(sk)} />
                </div>
                {sk.description && <p className="line-clamp-2 text-[13px] text-muted-foreground">{sk.description}</p>}
                {sk.body && <pre className="line-clamp-3 overflow-hidden whitespace-pre-wrap rounded-lg bg-subtle/70 p-2.5 font-sans text-[12px] leading-relaxed text-foreground/75">{sk.body}</pre>}
                <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
                  <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(sk)}>编辑</Button>
                  <Button size="sm" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => dup.mutate(sk.id)}>复制</Button>
                  {sk.source === 'builtin' ? (
                    <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => reset.mutate(sk.id)}>重置</Button>
                  ) : (
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDel(sk)}>删除</Button>
                  )}
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      <SkillEditor value={editing} stages={stages} onClose={() => setEditing(null)} onSaved={invalidate} />
      <GithubImportDialog open={ghOpen} stages={stages} onOpenChange={setGhOpen} onImported={invalidate} />
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent title={`删除技能「${del?.name}」？`} desc="已绑定它的作品会自动解绑。"
          footer={<><Button variant="ghost" onClick={() => setDel(null)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => del && rm.mutate(del.id)}>删除</Button></>} />
      </Dialog>
    </div>
  )
}

function SkillEditor({ value, stages, onClose, onSaved }: {
  value: SkillItem | 'new' | null
  stages: { key: string; label: string }[]
  onClose: () => void
  onSaved: () => void
}) {
  const isNew = value === 'new'
  const [cur, setCur] = useState<typeof value>(null)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [stage, setStage] = useState('writing')
  const [body, setBody] = useState('')
  const [isDefault, setIsDefault] = useState(false)

  if (value !== cur) {
    setCur(value)
    if (value && value !== 'new') {
      setName(value.name); setDesc(value.description); setStage(value.stage); setBody(value.body ?? ''); setIsDefault(value.is_default)
    } else if (value === 'new') {
      setName(''); setDesc(''); setStage('writing'); setBody(''); setIsDefault(false)
    }
  }

  const m = useMutation({
    mutationFn: () => isNew
      ? api.createSkill({ name: name.trim(), description: desc.trim(), stage, body: body.trim(), is_default: isDefault })
      : api.updateSkill((value as SkillItem).id, { name: name.trim(), description: desc.trim(), stage, body: body.trim(), is_default: isDefault }),
    meta: { errorTitle: '保存技能失败' },
    onSuccess: () => { onSaved(); toast.success(isNew ? '技能已创建' : '技能已保存'); onClose() },
  })

  return (
    <Sheet open={!!value} onOpenChange={(o) => !o && onClose()} title={isNew ? '新建技能' : `编辑技能：${(value as SkillItem | null)?.name ?? ''}`}
      footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" disabled={!name.trim() || !body.trim()} loading={m.isPending} onClick={() => m.mutate()}>保存</Button></>}>
      <div className="space-y-4">
        <Field label="技能名称"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：番茄快节奏打脸写法" /></Field>
        <Field label="适用环节">
          <div className="flex flex-wrap gap-1.5">
            {stages.map((st) => (
              <button key={st.key} type="button" onClick={() => setStage(st.key)}
                className={cn('h-8 rounded-lg border px-2.5 text-xs transition', stage === st.key ? 'border-primary bg-primary-soft font-medium text-primary' : 'hover:bg-subtle')}>
                {st.label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="简介"><Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="一句话说明这个技能解决什么问题" /></Field>
        <Field label="技能正文（Markdown）" hint={`当前 ${body.length.toLocaleString()} 字；单条技能建议精炼在 1500 字以内`}>
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-[300px] font-mono text-[13px] leading-relaxed" placeholder="# 写法要点&#10;1. ..." />
        </Field>
        <div className="flex items-center justify-between rounded-xl bg-subtle/60 px-3.5 py-3">
          <div>
            <div className="text-[13px] font-medium">新书默认启用</div>
            <div className="text-xs text-muted-foreground">未单独配置技能的作品会自动加载它</div>
          </div>
          <Switch checked={isDefault} onCheckedChange={setIsDefault} />
        </div>
      </div>
    </Sheet>
  )
}

function GithubImportDialog({ open, stages, onOpenChange, onImported }: {
  open: boolean
  stages: { key: string; label: string }[]
  onOpenChange: (o: boolean) => void
  onImported: () => void
}) {
  const [url, setUrl] = useState('')
  const [stage, setStage] = useState('writing')
  const [token, setToken] = useState('')
  const m = useMutation({
    mutationFn: () => api.importGithubSkill({ url: url.trim(), stage, ...(token.trim() ? { token: token.trim() } : {}) }),
    meta: { errorTitle: '导入失败' },
    onSuccess: (sk) => { onImported(); toast.success(`已导入技能「${sk.name}」`); setUrl(''); setToken(''); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setToken(''); onOpenChange(o) }}>
      <DialogContent wide title="从 GitHub 导入技能" desc="支持仓库、子目录（自动读 SKILL.md 与 references/*.md）或具体 .md 文件链接。"
        footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button><Button variant="primary" disabled={!url.trim()} loading={m.isPending} onClick={() => m.mutate()}>导入</Button></>}>
        <div className="space-y-4">
          <Field label="GitHub 链接">
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo/tree/main/skills/xxx 或 SKILL.md 链接" className="font-mono text-[13px]" />
          </Field>
          <Field label="归属环节">
            <div className="flex flex-wrap gap-1.5">
              {stages.map((st) => (
                <button key={st.key} type="button" onClick={() => setStage(st.key)}
                  className={cn('h-8 rounded-lg border px-2.5 text-xs transition', stage === st.key ? 'border-primary bg-primary-soft font-medium text-primary' : 'hover:bg-subtle')}>
                  {st.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="GitHub Token（可选）" hint="遇到匿名频率限制或私有仓库时填写，仅用于本次请求，不落库">
            <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="ghp_..." className="font-mono text-[13px]" />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  )
}
