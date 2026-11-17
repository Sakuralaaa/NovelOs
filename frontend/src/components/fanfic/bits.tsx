import { Plus, X } from '@/components/icons'
import { Input } from '@/components/ui/input'
import type { FanficDepth, FanficFidelity, OocLevel, OverlapLevel } from '@/lib/types'
import { cn } from '@/lib/utils'

export const DEPTHS: { value: FanficDepth; label: string; desc: string }[] = [
  { value: 'quick', label: '快速', desc: '1 轮提炼，几分钟出主角与主线' },
  { value: 'standard', label: '标准', desc: '2 轮提炼，覆盖主要角色与势力' },
  { value: 'deep', label: '深入', desc: '4 轮提炼，配角、时间线更全，耗时更长' },
]
export const depthLabel = (d?: string) => DEPTHS.find((x) => x.value === d)?.label ?? d ?? ''
/** v0.11.1 来源标签：联网 / 粘贴 / TXT（原文 + 联网补充显示「+联网」） */
export const sourceLabel = (s: { source: string; web_rounds?: number }) =>
  s.source === 'search' ? '联网' : `${s.source === 'txt' ? 'TXT' : '粘贴'}${s.web_rounds ? '+联网' : ''}`

export const FIDELITY_FALLBACK: { id: FanficFidelity; label: string; desc: string; pass_score: number }[] = [
  { id: 'strict', label: '严格遵循', desc: '原著设定与时间线都不改', pass_score: 80 },
  { id: 'moderate', label: '有据延展', desc: '可改支线与结局，人设不变', pass_score: 70 },
  { id: 'loose', label: '分歧世界（AU）', desc: '只保留人物核心', pass_score: 55 },
]

export const LEVEL_TONE: Record<OocLevel, 'success' | 'warning' | 'danger'> = { pass: 'success', warn: 'warning', fail: 'danger' }
export const LEVEL_LABEL: Record<OocLevel, string> = { pass: '通过', warn: '注意', fail: '不通过' }
export const OVERLAP_TONE: Record<OverlapLevel, 'success' | 'neutral' | 'warning' | 'danger'> = { ok: 'success', info: 'neutral', warn: 'warning', high: 'danger' }
export const OVERLAP_LABEL: Record<OverlapLevel, string> = { ok: '无重合', info: '少量重合', warn: '重合偏多', high: '重合严重' }

/** 字符串列表编辑：每行一个输入框，可增删（触控目标 ≥40px） */
export function StrList({ value, onChange, placeholder, addLabel = '添加一条', max }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string; addLabel?: string; max?: number
}) {
  return (
    <div className="space-y-1.5">
      {value.map((v, i) => (
        <div key={i} className="flex min-w-0 items-center gap-1.5">
          <Input value={v} placeholder={placeholder} className="h-10 min-w-0 flex-1"
            onChange={(e) => onChange(value.map((x, k) => (k === i ? e.target.value : x)))} />
          <RemoveBtn onClick={() => onChange(value.filter((_, k) => k !== i))} />
        </div>
      ))}
      {(!max || value.length < max) && (
        <button type="button" onClick={() => onChange([...value, ''])}
          className="focus-ring inline-flex h-10 items-center gap-1 rounded-md px-2 text-[13px] text-primary hover:bg-primary-soft/60">
          <Plus className="h-3.5 w-3.5" />{addLabel}
        </button>
      )}
    </div>
  )
}

export function RemoveBtn({ onClick, label = '删除', className }: { onClick: () => void; label?: string; className?: string }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className={cn('focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-danger-soft hover:text-danger', className)}>
      <X className="h-4 w-4" />
    </button>
  )
}

/** 小标题 + 内容 */
export function Lbl({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return <div className="mb-1 flex items-baseline justify-between gap-2 text-[12px] font-medium text-muted-foreground"><span>{children}</span>{hint && <span className="font-normal">{hint}</span>}</div>
}

/** 短标签编辑（别称、口癖、成员…）：回车/逗号添加，点标签移除；每个标签本身就是 40px 高的按钮 */
export function Chips({ value, onChange, placeholder = '输入后回车添加', max }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; max?: number }) {
  const add = (raw: string, el: HTMLInputElement) => {
    const parts = raw.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean)
    if (!parts.length) return
    const next = Array.from(new Set([...value, ...parts]))
    onChange(max ? next.slice(0, max) : next)
    el.value = ''
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {value.map((t) => (
        <button key={t} type="button" aria-label={`移除 ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}
          className="focus-ring inline-flex h-10 max-w-full items-center gap-1 rounded-md bg-muted px-2.5 text-[13px] hover:bg-danger-soft hover:text-danger">
          <span className="truncate">{t}</span><X className="h-3 w-3 shrink-0 opacity-60" />
        </button>
      ))}
      {(!max || value.length < max) && (
        <input placeholder={placeholder}
          className="h-10 min-w-[120px] flex-1 rounded-md border border-input bg-surface px-2.5 text-[13px] outline-none focus:border-primary/60"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); add(e.currentTarget.value, e.currentTarget) } }}
          onChange={(e) => { if (/[,，]/.test(e.target.value)) add(e.target.value, e.target) }}
          onBlur={(e) => add(e.target.value, e.target)} />
      )}
    </div>
  )
}

/** 翻页：上一页 / 页码 / 下一页（总页数 ≤1 时不显示） */
export function Pager({ page, pages, onChange }: { page: number; pages: number; onChange: (p: number) => void }) {
  if (pages <= 1) return null
  return (
    <div className="num mt-3 flex items-center justify-center gap-2 text-[13px]">
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)} className="focus-ring h-9 rounded-lg border px-3 disabled:opacity-40 hover:bg-muted">上一页</button>
      <span className="min-w-[64px] text-center text-muted-foreground">{page} / {pages}</span>
      <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)} className="focus-ring h-9 rounded-lg border px-3 disabled:opacity-40 hover:bg-muted">下一页</button>
    </div>
  )
}

/** v0.14.0 常用创作想法：点一下把成型的设想填进想法框（「原著」会换成所选作品名），同时选上对应方向 */
export const IDEAS: { label: string; direction: import('@/lib/types').FanficDirectionId; text: string }[] = [
  { label: '穿成炮灰逆袭', direction: 'transmigration', text: '主角穿进《原著》，成了开篇就该领盒饭的炮灰。靠着对剧情的先知先苟住性命，再一步步截胡机缘、抢在原著主角前面崛起，最终改写自己的结局。' },
  { label: '带系统闯原著', direction: 'system', text: '主角带着系统进入《原著》世界，完成和原著剧情挂钩的任务就能拿奖励（功法、血脉、道具）。系统只给好处不添堵，主角越改剧情奖励越大，一路升级碾压。' },
  { label: '重生改命', direction: 'rebirth', text: '《原著》中的角色带着前世记忆重生回到故事开头。这一次知道谁是敌人、哪里有机缘，先补上最大的遗憾，再把前世欺负过自己的人一个个收拾掉。' },
  { label: '原创天才加入', direction: 'if_line', text: '一个原创天才角色在《原著》开篇出现在主角团身边，天赋不输原著主角。他的加入让原著几场关键战斗换了打法，人物关系也跟着重新洗牌。' },
  { label: '配角逆袭成主角', direction: 'side_pov', text: '以《原著》里一个戏份不多的配角为主角，从他的视角重走原著主线，补上他没被写到的奋斗和高光，最后打出不输原著主角的名声。' },
  { label: '反派洗白', direction: 'villain_redemption', text: '主角成了《原著》里的大反派，提前知道自己的下场。他不想再当垫脚石，开始换一种活法：收拢手下、避开死局，把反派阵营带成能和主角分庭抗礼的一方。' },
  { label: '主角提前开挂', direction: 'if_line', text: '《原著》主角在故事开头就提前觉醒了后期才有的能力，开局即强者。原著里压着他的人和事都提前被掀翻，剧情走向完全不同。' },
  { label: '诸天穿越', direction: 'multi_transmigration', text: '主角以《原著》为起点，在多个作品世界之间轮流穿越，每个世界拿到关键机缘后带回来，实力和底牌在不同世界里叠加。' },
  { label: '原著角色穿到现代', direction: 'reverse_transmigration', text: '《原著》里的强者意外来到现代都市，用原著世界的本事在现代混得风生水起，同时引出原著世界跟着打通的后续。' },
  { label: '复活意难平', direction: 'revival', text: '《原著》里死得最让人意难平的角色被救了回来。他的存活让后面的剧情全部改写，主角团多了一份关键战力。' },
  { label: '结局后新冒险', direction: 'epilogue', text: '《原著》大结局之后，主角团的下一代（或主角本人）迎来新的危机，在更大的世界里继续冒险，原著老角色以长辈和强援身份登场。' },
  { label: '烂尾续写', direction: 'unfinished', text: '接着《原著》没写完的地方往下写，把埋下的伏笔一一回收，给主角和重要角色一个完整、爽快的结局。' },
  { label: '都市 AU', direction: 'au_modern', text: '把《原著》的人物放进现代都市，保留各自性格和关系，原著里的势力换成公司、家族和学院，原著的大事件换成都市里的对应冲突。' },
  { label: 'CP 甜文', direction: 'cp', text: '以《原著》中的一对 CP 为主线，在原著剧情之外多写两人的相处、并肩作战和感情升温，甜为主、虐点少。' },
]
