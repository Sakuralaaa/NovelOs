import { useCallback, useMemo, useRef, useState } from 'react'
import { ClipboardPaste, Pencil, ShieldCheck, Trash2 } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import {
  AIGC_MAX, AigcSummary, Disclaimer, HighlightToggle, HighlightedText, SegmentList, ZhuqueSetupHint, useZhuque,
} from '@/components/aigc/Aigc'
import { api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { AigcResult, AigcSegment } from '@/lib/types'
import { cn } from '@/lib/utils'

// 离开页面再回来仍保留上一次的输入与结果（不落盘，刷新页面即清空）
let memo: { text: string; result: AigcResult | null; checkedText: string } = { text: '', result: null, checkedText: '' }

const len = (s: string) => s.replace(/\s/g, '').length

export default function AigcDetectPage() {
  const cfg = useZhuque()
  const configured = !!cfg.data?.zhuque_configured
  const [text, setTextState] = useState(memo.text)
  const [result, setResult] = useState<AigcResult | null>(memo.result)
  const [checkedText, setCheckedText] = useState(memo.checkedText)
  const [mode, setMode] = useState<'edit' | 'result'>(memo.result ? 'result' : 'edit')
  const [hl, setHl] = useState(true)
  const [focus, setFocus] = useState<AigcSegment | null>(null)
  const viewRef = useRef<HTMLDivElement>(null)
  const { start } = useJobs()
  const job = useActiveJob('aigc-detect')
  const n = useMemo(() => len(text), [text])
  const over = n > AIGC_MAX
  const setText = (v: string) => { setTextState(v); memo.text = v }

  const run = () => {
    const snap = text
    start(api.detectAigc(snap), {
      key: 'aigc-detect', label: 'AI 率检测',
      successMsg: (j) => { const v = j.result?.softmax ?? 0; return `检测完成：AI 置信度 ${Math.round(v <= 1 ? v * 100 : v)}%` },
      onSuccess: (j) => {
        const r = j.result as AigcResult | null
        memo = { text: memo.text, result: r, checkedText: snap }
        setResult(r); setCheckedText(snap); setMode('result'); setFocus(null)
      },
    })
  }
  const paste = async () => {
    try {
      const t = await navigator.clipboard.readText()
      if (t) setText(t)
    } catch { toast.info('浏览器不允许直接读剪贴板，请长按文本框粘贴') }
  }
  const locate = useCallback((s: AigcSegment) => {
    setHl(true); setMode('result'); setFocus(s)
    setTimeout(() => document.getElementById(`aigc-seg-${s.start}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60)
  }, [])
  const changedSince = !!result && text !== checkedText

  return (
    <div className="page">
      <PageHeader title="AI 率检测" desc="用腾讯朱雀 AIGC 检测判断文本的 AI 生成概率，标出 AI 和疑似片段，方便自查。" />

      {cfg.data && !configured && <ZhuqueSetupHint className="mb-6 bg-surface" />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader divider title={mode === 'result' && result ? '检测结果' : '待检测文本'}
            action={result ? <Segmented size="sm" value={mode} onChange={setMode} options={[{ value: 'edit', label: <span className="inline-flex items-center gap-1"><Pencil className="h-3.5 w-3.5" />编辑</span> }, { value: 'result', label: <span className="inline-flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" />高亮</span> }]} /> : undefined} />
          {mode === 'result' && result ? (
            <div ref={viewRef} className="px-5 py-5 md:px-7">
              {changedSince && <p className="mb-4 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">输入框里的文本改过了，这里显示的是检测时的原文。</p>}
              <HighlightedText text={checkedText} segments={result.segments ?? []} show={hl} focus={focus} onPick={setFocus} />
            </div>
          ) : (
            <div className="p-4 md:p-5">
              <Textarea value={text} onChange={(e) => setText(e.target.value)} disabled={!!job}
                placeholder="把要检测的正文粘贴到这里（最多 12 万字）。建议一次检测一章或几章，结果更准。"
                className={cn('min-h-[50vh] font-serif text-[15px] leading-[1.85]', over && 'border-danger/60 focus:border-danger')} />
              <div className="mt-2">
                <div className="h-1 overflow-hidden rounded-full bg-muted">
                  <div className={cn('h-full rounded-full transition-[width] duration-300', over ? 'bg-danger' : n > AIGC_MAX * 0.9 ? 'bg-warning' : 'bg-primary/70')} style={{ width: `${Math.min(100, (n / AIGC_MAX) * 100)}%` }} />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-3 text-[12px]">
                  <span className={cn('num', over ? 'font-medium text-danger' : 'text-muted-foreground')}>
                    {n.toLocaleString('zh-CN')} / {AIGC_MAX.toLocaleString('zh-CN')} 字{over && `，超出 ${(n - AIGC_MAX).toLocaleString('zh-CN')} 字`}
                  </span>
                  <span className="flex items-center gap-1">
                    <Button size="sm" variant="ghost" className="h-9" icon={<ClipboardPaste className="h-3.5 w-3.5" />} onClick={paste} disabled={!!job}>粘贴</Button>
                    {text && <Button size="sm" variant="ghost" className="h-9" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setText('')} disabled={!!job}>清空</Button>}
                  </span>
                </div>
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-surface/80 px-4 py-3 md:px-5">
            <Disclaimer className="min-w-0 flex-1" />
            <Button variant="primary" size="lg" loading={!!job} disabled={!configured || !n || over} icon={<ShieldCheck className="h-4 w-4" />}
              onClick={() => { if (mode === 'result') setMode('edit'); run() }}>
              {job ? '检测中…' : result ? '重新检测' : '开始检测'}
            </Button>
          </div>
        </Card>

        <div className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
          {job && <JobInline job={job} />}
          {result ? (
            <>
              <AigcSummary r={result} stale={changedSince} staleNote="输入的文本改过了，结果对应的是上一次的文本" onRerun={configured ? run : undefined} running={!!job} />
              <HighlightToggle checked={hl} onChange={(v) => { setHl(v); if (v) setMode('result') }} />
              <Card className="p-4">
                <h3 className="mb-2.5 text-[13.5px] font-semibold">AI / 疑似片段 <span className="text-[12px] font-normal text-muted-foreground">点一下定位到原文</span></h3>
                <SegmentList text={checkedText} segments={result.segments ?? []} onLocate={locate} />
              </Card>
            </>
          ) : job ? (
            <Skeleton className="h-[220px] rounded-xl" />
          ) : (
            <Card className="p-5">
              <div className="text-[14px] font-semibold">怎么看结果</div>
              <ul className="mt-2 space-y-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
                <li>· <b className="text-success">低</b>：大体像人写的；<b className="text-warning">中</b>：有明显模板腔；<b className="text-danger">高</b>：大段像模型直出。</li>
                <li>· 检测后可以在原文上高亮 AI 段（红）和疑似段（黄），点片段列表定位。</li>
                <li>· 每次检测会消耗 EdgeOne Makers 的免费额度，文本越长消耗越多。</li>
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
