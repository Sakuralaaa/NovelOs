import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Segmented } from '@/components/ui/tabs'
import { Select } from '@/components/ui/select'
import { EmptyState } from '@/components/common/States'
import { TrendBriefCard, boardScope, parseScope } from '@/components/radar/TrendBrief'
import { api, qk } from '@/lib/api'
import type { Gender, RankBoard } from '@/lib/types'

export { scopeLabel } from '@/components/radar/TrendBrief'

const LS_SCOPE = 'novelos.trend-scope'
type Mode = 'overall' | 'board' | 'category'

/** 「风向标」独立标签：总榜 / 单榜 / 题材的完整视图（与榜单页内嵌卡共用 TrendBriefCard，始终展开） */
export function TrendReportView() {
  const [scope, setScopeState] = useState<string>(() => localStorage.getItem(LS_SCOPE) || 'overall')
  const setScope = (s: string) => { setScopeState(s); localStorage.setItem(LS_SCOPE, s) }
  const p = parseScope(scope)
  const [mode, setMode] = useState<Mode>(p.kind)
  const [gender, setGender] = useState<Gender>(p.kind !== 'overall' ? p.gender : 'male')
  const [board, setBoard] = useState<RankBoard>(p.kind !== 'overall' ? p.board : 'read')
  const cat = p.kind === 'category' && p.gender === gender && p.board === board ? p.category : null

  const snapCats = useQuery({
    queryKey: qk.radarLatest(gender, '', board),
    queryFn: () => api.radarLatest({ gender, board }),
    enabled: mode === 'category',
  })
  const cats = useMemo(() => {
    const m = new Map<string, number>()
    ;(snapCats.data?.items ?? []).forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1))
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c)
  }, [snapCats.data])

  const apply = (m: Mode, g = gender, b = board, c: string | null = cat) => {
    setMode(m); setGender(g); setBoard(b)
    if (m === 'overall') setScope('overall')
    else if (m === 'board') setScope(boardScope(g, b))
    else if (c) setScope(boardScope(g, b, c))
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <Segmented value={mode} onChange={(m) => apply(m)} options={[{ value: 'overall', label: '总榜' }, { value: 'board', label: '按榜单' }, { value: 'category', label: '按题材' }]} />
        {mode !== 'overall' && (
          <>
            <Segmented value={gender} onChange={(g) => apply(mode, g, board, null)} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
            <Segmented value={board} onChange={(b) => apply(mode, gender, b, null)} options={[{ value: 'read', label: '阅读榜' }, { value: 'new', label: '新书榜' }]} />
          </>
        )}
        {mode === 'category' && (
          <div className="w-full sm:w-[200px]">
            <Select value={cat} onChange={(v) => v && apply('category', gender, board, v)}
              placeholder={snapCats.isLoading ? '读取题材…' : cats.length ? '选择题材' : '先刷新榜单'} options={cats.map((c) => ({ value: c, label: c }))} />
          </div>
        )}
      </div>

      {mode === 'category' && !cat ? (
        <EmptyState compact kind="radar" title="选一个题材" desc="按题材生成的风向标只看这个题材在所选榜单上的书，更细、更好下手。" />
      ) : (
        <TrendBriefCard key={scope} scope={mode === 'overall' ? 'overall' : scope} collapsible={false} />
      )}
    </div>
  )
}
