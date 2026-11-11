import { countWords } from './utils'

export interface Para { index: number; start: number; end: number; text: string; kind: 'bare-dialogue' | 'dialogue' | 'summary' | 'normal' }

const SUMMARY_MARKERS = /(于是|随后|接下来的|接下来|这段时间|这些天|几天后|几天里|此后|之后的|总之|一切都|渐渐地|渐渐|很快|日子一天天|转眼|整整|就这样|与此同时|总的来说|事实上)/
const QUOTE_RE = /[“「『"][^”」』"]*[”」』"]/g

/** 段落切分（保留原文偏移，便于高亮） */
export function splitParas(text: string): Para[] {
  const out: Para[] = []
  let pos = 0
  const lines = text.split('\n')
  lines.forEach((line) => {
    const lead = line.length - line.trimStart().length
    const t = line.trim()
    if (t) {
      out.push({ index: out.length, start: pos + lead, end: pos + lead + t.length, text: t, kind: classify(t) })
    }
    pos += line.length + 1
  })
  return out
}

function classify(t: string): Para['kind'] {
  const quotes = t.match(QUOTE_RE)
  if (quotes && quotes.length) {
    const rest = t.replace(QUOTE_RE, '').replace(/[\s，。！？、：；…—,.!?:;]/g, '')
    // 引号之外只剩“他说/她问道”之类（≤3 字）即视为裸对白
    return countWords(rest) <= 3 ? 'bare-dialogue' : 'dialogue'
  }
  if (countWords(t) >= 28 && SUMMARY_MARKERS.test(t)) return 'summary'
  return 'normal'
}

export function sentenceLengths(text: string) {
  return text
    .replace(/[“”「」『』"]/g, '')
    .split(/[。！？!?…；;\n]+/)
    .map((s) => countWords(s))
    .filter((n) => n > 0)
}

export function analyzeText(text: string) {
  const paras = splitParas(text)
  const lens = sentenceLengths(text)
  const total = countWords(text) || 1
  const dlgParas = paras.filter((p) => p.kind === 'bare-dialogue' || p.kind === 'dialogue')
  const quoted = (text.match(QUOTE_RE) || []).reduce((n, q) => n + countWords(q), 0)
  const summaryWords = paras.filter((p) => p.kind === 'summary').reduce((n, p) => n + countWords(p.text), 0)
  return {
    paras,
    avg_sentence_len: lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : 0,
    short_sentence_ratio: lens.length ? lens.filter((n) => n <= 8).length / lens.length : 0,
    bare_dialogue_ratio: dlgParas.length ? paras.filter((p) => p.kind === 'bare-dialogue').length / dlgParas.length : 0,
    summary_ratio: summaryWords / total,
    dialogue_ratio: quoted / total,
    sentence_hist: histogram(lens),
  }
}

export function histogram(lens: number[]) {
  const buckets = [
    { label: '1-8', min: 1, max: 8 },
    { label: '9-15', min: 9, max: 15 },
    { label: '16-25', min: 16, max: 25 },
    { label: '26-40', min: 26, max: 40 },
    { label: '40+', min: 41, max: Infinity },
  ]
  const n = lens.length || 1
  return buckets.map((b) => ({ bucket: b.label, ratio: lens.filter((l) => l >= b.min && l <= b.max).length / n }))
}

/** 段落级 diff（LCS），用于“描写增厚”前后对比 */
export type DiffRow =
  | { type: 'same'; text: string }
  | { type: 'changed'; before: string; after: string }
  | { type: 'added'; after: string }
  | { type: 'removed'; before: string }

export function diffParas(a: string, b: string): DiffRow[] {
  const A = a.split('\n').map((s) => s.trim()).filter(Boolean)
  const B = b.split('\n').map((s) => s.trim()).filter(Boolean)
  const n = A.length, m = B.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const raw: DiffRow[] = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (A[i] === B[j]) { raw.push({ type: 'same', text: A[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { raw.push({ type: 'removed', before: A[i] }); i++ }
    else { raw.push({ type: 'added', after: B[j] }); j++ }
  }
  while (i < n) raw.push({ type: 'removed', before: A[i++] })
  while (j < m) raw.push({ type: 'added', after: B[j++] })
  // 将相邻的 removed 段与 added 段按顺序配对为 changed（逐段改写最常见）
  const out: DiffRow[] = []
  let k = 0
  while (k < raw.length) {
    if (raw[k].type !== 'removed' && raw[k].type !== 'added') { out.push(raw[k++]); continue }
    const rem: string[] = [], add: string[] = []
    while (k < raw.length && (raw[k].type === 'removed' || raw[k].type === 'added')) {
      const r = raw[k++] as any
      if (r.type === 'removed') rem.push(r.before)
      else add.push(r.after)
    }
    const pair = Math.min(rem.length, add.length)
    for (let x = 0; x < pair; x++) out.push({ type: 'changed', before: rem[x], after: add[x] })
    rem.slice(pair).forEach((t) => out.push({ type: 'removed', before: t }))
    add.slice(pair).forEach((t) => out.push({ type: 'added', after: t }))
  }
  return out
}
