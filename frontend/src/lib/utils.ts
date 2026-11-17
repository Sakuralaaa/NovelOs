import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { BookStatus, CardType } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 中文网文常用字数：中文字符 + 英文单词 + 数字串 */
export function countWords(text: string) {
  if (!text) return 0
  const cjk = text.match(/[\u3400-\u9fff\uf900-\ufaff]/g)?.length ?? 0
  const latin = text.replace(/[\u3400-\u9fff\uf900-\ufaff]/g, ' ').match(/[A-Za-z0-9]+/g)?.length ?? 0
  return cjk + latin
}

export function fmtNum(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  if (n >= 1e8) return `${(n / 1e8).toFixed(n >= 1e9 ? 0 : 1)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(n >= 1e6 ? 0 : 1)}万`
  return n.toLocaleString('zh-CN')
}

export function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 45) return '刚刚'
  if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)} 天前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export function fmtDateTime(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export const STAGES: { key: BookStatus; label: string; desc: string }[] = [
  { key: 'idea', label: '选题', desc: '确定题材与卖点' },
  { key: 'bible', label: '设定', desc: '世界观、人物、势力' },
  { key: 'outline', label: '大纲', desc: '总纲 → 卷 → 章细纲' },
  { key: 'writing', label: '正文', desc: '逐章写作与审稿' },
  { key: 'packaging', label: '包装', desc: '书名、简介、封面' },
  { key: 'done', label: '发布', desc: '导出发布包，人工上架' },
]
export const stageIndex = (s: BookStatus) => Math.max(0, STAGES.findIndex((x) => x.key === s))

export const CARD_TYPES: { key: CardType; label: string; hint: string }[] = [
  { key: 'world', label: '世界观', hint: '时代背景、地理、规则' },
  { key: 'cheat', label: '金手指', hint: '系统、外挂、独门天赋' },
  { key: 'power', label: '力量体系', hint: '境界、功法、等级' },
  { key: 'faction', label: '势力', hint: '宗门、家族、组织' },
  { key: 'character', label: '人物', hint: '主角、配角、反派' },
  { key: 'item', label: '物品', hint: '法宝、道具、信物' },
  { key: 'location', label: '地点', hint: '城市、秘境、场景' },
]
export const cardTypeLabel = (t: CardType) => CARD_TYPES.find((x) => x.key === t)?.label ?? t

export const JOB_KIND_LABEL: Record<string, string> = {
  book_adopt: '接管旧书', generation_followup: '追问', book_batch: '批量处理', chapter_titles: '起章名', sparks: '脑洞抽卡',
  reader_comments: '神评', spark_draw: '抽卡', spark_proposal: '立项书', fanfic_oc: '原创主角',
  wanben_plan: '完本规划',
  wanben_batch: '完本连写',
  wanben_iterate: '章节迭代',
  book_check: '整书体检',
  adaptability: '短剧可改编度',
  homogeneity: '同质化自查',
  agent_run: 'Agent 处理中',
  fanfic_source: '提炼原著设定',
  fanfic_ooc: 'OOC 检查',
  fanfic_supplement: '联网补充原著',
  radar_refresh: '刷新热点榜单',
  radar_teardown: '拆解榜单书',
  radar_deep: '深度拆解',
  radar_reskin: '生成换皮选题',
  radar_book_ai: 'AI 书名/封面词/简介',
  aigc_detect: 'AI 率检测',
  chapter_aigc: 'AI 率检测',
  polish_voice: '语感重塑',
  chapter_polish_voice: '语感重塑',
  chapter_commit: '提交入账',
  'radar.refresh': '刷新热点榜单',
  ideas_generate: '生成选题',
  idea_revise: '修改选题',
  idea_field: 'AI 改写',
  idea_rescore: '重新打分',
  'ideas.generate': '生成选题',
  bible_generate: '生成设定',
  'bible.generate': '生成设定',
  outline_generate: '生成大纲',
  'outline.generate': '生成大纲',
  outline_expand: '滚动展开大纲',
  'outline.expand': '滚动展开大纲',
  write_next: '写下一章',
  'chapters.write_next': '写下一章',
  write_batch: '批量写章',
  'chapters.write_batch': '批量写章',
  review: '审稿',
  'chapter.review': '审稿',
  humanize: '人味修整',
  'chapter.humanize': '人味修整',
  package_generate: '生成包装',
  'package.generate': '生成包装',
  covers_generate: '生成封面',
  'covers.generate': '生成封面',
  thicken: '描写增厚',
  chapter_write_next: '写下一章',
  chapter_write_batch: '批量写章',
  chapter_review: '审稿',
  chapter_humanize: '人味修整',
  chapter_thicken: '描写增厚',
  'chapter.thicken': '描写增厚',
  style_extract: '提炼文风',
  'style.extract': '提炼文风',
  book_revise: 'AI 改作品信息',
  book_sync: '同步到设定/大纲',
  bible_propose: 'AI 改设定库',
  card_suggest: 'AI 改设定',
  outline_node: 'AI 重写大纲',
  chapter_rewrite: '按要求改写',
  foreshadow_plan: 'AI 规划伏笔',
  cover_prompt: '改封面提示词',
  radar_report: '生成风向标日报',
  idea_seed: '灵感立项',
  idea_from_seed: '灵感立项',
  idea_organize: '一键整理选题',
  idea_fusion: '多本熔炉',
  book_test: '书测',
  // v0.9.3
  field_ai: '字段 AI',
  character_soul: '灵魂五维',
  teardown_project: '拆书',
}
export const jobLabel = (kind: string) => JOB_KIND_LABEL[kind] ?? kind

/** v0.9：平台风格档 */
export const PLATFORM_STYLES: { value: 'fanqie' | 'qidian' | 'generic' | 'duanju'; label: string; desc: string }[] = [
  { value: 'fanqie', label: '番茄', desc: '短段、对白推进、章尾卡点；超过 70 字的段落会提示拆分' },
  { value: 'qidian', label: '起点', desc: '世界细节可信、配角有智商、伏笔前后呼应，长线博弈可以慢慢铺' },
  { value: 'generic', label: '通用', desc: '不加平台专属写作要求，人味检查沿用通用阈值' },
  { value: 'duanju', label: '短剧分镜', desc: '在番茄档基础上：开场直接切冲突、多对白少独白、景物一句带过、章末卡在揭露前一刻，方便改编竖屏短剧' },
]
export const platformLabel = (v?: string | null) => PLATFORM_STYLES.find((x) => x.value === (v || 'fanqie'))?.label ?? v ?? '番茄'

export const GENRES_MALE = ['都市高武', '玄幻脑洞', '东方仙侠', '历史脑洞', '末世求生', '都市修真', '游戏体育', '科幻悬疑', '战神赘婿', '传统玄幻']
export const GENRES_FEMALE = ['豪门总裁', '古言宅斗', '年代重生', '宫斗宅斗', '现言甜宠', '快穿系统', '玄幻言情', '悬疑恋爱', '种田经商', '团宠萌宝']

export function scoreTone(v: number) {
  if (v >= 80) return 'text-success'
  if (v >= 60) return 'text-primary'
  if (v >= 40) return 'text-warning'
  return 'text-danger'
}

export function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

/** 复制文本：非 HTTPS（局域网访问）时 navigator.clipboard 不可用，退回 execCommand */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true }
  } catch { /* fall through */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'; ta.style.top = '-1000px'; ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select(); ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch { return false }
}
