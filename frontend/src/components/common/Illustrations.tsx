/** 自绘空状态插画：渐变 + 线条，跟随主题色 */
type K = 'book' | 'radar' | 'idea' | 'cards' | 'outline' | 'chapter' | 'foreshadow' | 'package' | 'style' | 'channel' | 'error'

export function Illustration({ kind, size = 132 }: { kind: K; size?: number }) {
  const id = `g-${kind}`
  return (
    <svg width={size} height={size * 0.78} viewBox="0 0 160 124" fill="none" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="hsl(var(--primary))" stopOpacity="0.22" />
          <stop offset="1" stopColor="hsl(var(--warning))" stopOpacity="0.10" />
        </linearGradient>
        <linearGradient id={`${id}-s`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="hsl(var(--primary))" />
          <stop offset="1" stopColor="hsl(var(--primary) / 0.75)" />
        </linearGradient>
      </defs>
      <ellipse cx="80" cy="112" rx="56" ry="6" fill="hsl(var(--foreground))" opacity="0.05" />
      <circle cx="80" cy="58" r="50" fill={`url(#${id})`} />
      {art(kind, `url(#${id}-s)`)}
    </svg>
  )
}

function art(kind: K, s: string) {
  const paper = 'hsl(var(--surface))'
  const line = 'hsl(var(--foreground) / 0.14)'
  switch (kind) {
    case 'radar':
      return (
        <g>
          <circle cx="80" cy="58" r="34" stroke={line} strokeWidth="1.5" fill={paper} />
          <circle cx="80" cy="58" r="22" stroke={line} strokeWidth="1.5" />
          <circle cx="80" cy="58" r="10" stroke={line} strokeWidth="1.5" />
          <path d="M80 58 L108 38 A34 34 0 0 1 114 58 Z" fill={s} opacity="0.35" />
          <path d="M80 58 L108 38" stroke={s} strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="98" cy="49" r="3.5" fill={s} /><circle cx="66" cy="44" r="2.5" fill={s} opacity=".6" /><circle cx="72" cy="74" r="2.5" fill={s} opacity=".6" />
        </g>
      )
    case 'idea':
      return (
        <g>
          <path d="M80 22c-15 0-26 11-26 25 0 9 5 16 11 21v9h30v-9c6-5 11-12 11-21 0-14-11-25-26-25Z" fill={paper} stroke={s} strokeWidth="2.5" />
          <rect x="66" y="82" width="28" height="6" rx="3" fill={s} opacity=".5" /><rect x="70" y="91" width="20" height="5" rx="2.5" fill={s} opacity=".35" />
          <path d="M74 56l6-10 6 10" stroke={s} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M44 30l-6-4M116 30l6-4M40 52h-7M120 52h7" stroke={s} strokeWidth="2.5" strokeLinecap="round" opacity=".5" />
        </g>
      )
    case 'cards':
      return (
        <g>
          <rect x="44" y="30" width="44" height="58" rx="6" fill={paper} stroke={line} strokeWidth="1.5" transform="rotate(-10 66 59)" />
          <rect x="72" y="26" width="44" height="58" rx="6" fill={paper} stroke={s} strokeWidth="2" transform="rotate(8 94 55)" />
          <circle cx="93" cy="46" r="7" fill={s} opacity=".45" transform="rotate(8 94 55)" />
          <path d="M82 62h24M82 70h18" stroke={line} strokeWidth="3" strokeLinecap="round" transform="rotate(8 94 55)" />
        </g>
      )
    case 'outline':
      return (
        <g>
          <rect x="48" y="24" width="64" height="72" rx="7" fill={paper} stroke={line} strokeWidth="1.5" />
          <circle cx="60" cy="38" r="3.5" fill={s} /><path d="M68 38h32" stroke={s} strokeWidth="3" strokeLinecap="round" />
          <circle cx="68" cy="52" r="3" fill={s} opacity=".6" /><path d="M75 52h24" stroke={line} strokeWidth="3" strokeLinecap="round" />
          <circle cx="68" cy="64" r="3" fill={s} opacity=".6" /><path d="M75 64h20" stroke={line} strokeWidth="3" strokeLinecap="round" />
          <circle cx="60" cy="78" r="3.5" fill={s} /><path d="M68 78h28" stroke={s} strokeWidth="3" strokeLinecap="round" opacity=".7" />
        </g>
      )
    case 'chapter':
    case 'style':
      return (
        <g>
          <rect x="50" y="22" width="60" height="76" rx="7" fill={paper} stroke={line} strokeWidth="1.5" />
          <path d="M60 38h40M60 48h40M60 58h32M60 68h38M60 78h24" stroke={line} strokeWidth="3" strokeLinecap="round" />
          <path d="M104 74l14-26 6 3-14 26-8 4z" fill={s} />
        </g>
      )
    case 'foreshadow':
      return (
        <g>
          <path d="M40 84c18-30 34 6 50-20s22-28 30-30" stroke={s} strokeWidth="2.5" strokeLinecap="round" strokeDasharray="4 6" />
          <circle cx="40" cy="84" r="6" fill={paper} stroke={s} strokeWidth="2.5" />
          <circle cx="90" cy="64" r="5" fill={s} opacity=".55" />
          <path d="M120 26l3 7 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z" fill={s} />
        </g>
      )
    case 'package':
      return (
        <g>
          <rect x="56" y="20" width="48" height="70" rx="5" fill={s} opacity=".85" />
          <rect x="56" y="20" width="48" height="70" rx="5" fill="url(#none)" stroke={paper} strokeOpacity=".5" />
          <path d="M64 70h32M64 78h22" stroke={paper} strokeWidth="3" strokeLinecap="round" opacity=".85" />
          <circle cx="80" cy="44" r="11" fill={paper} opacity=".35" />
          <rect x="92" y="62" width="30" height="30" rx="6" fill={paper} stroke={line} strokeWidth="1.5" />
          <path d="M100 77l5 5 9-10" stroke={s} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )
    case 'channel':
      return (
        <g>
          <rect x="42" y="36" width="44" height="44" rx="10" fill={paper} stroke={line} strokeWidth="1.5" />
          <rect x="76" y="44" width="44" height="44" rx="10" fill={paper} stroke={s} strokeWidth="2" />
          <path d="M90 66h16M98 58v16" stroke={s} strokeWidth="3" strokeLinecap="round" />
          <circle cx="58" cy="52" r="4" fill={s} opacity=".55" /><path d="M54 64h12" stroke={line} strokeWidth="3" strokeLinecap="round" />
        </g>
      )
    case 'error':
      return (
        <g>
          <path d="M80 26 116 88H44Z" fill={paper} stroke="hsl(var(--warning))" strokeWidth="2.5" strokeLinejoin="round" />
          <path d="M80 50v16" stroke="hsl(var(--warning))" strokeWidth="4" strokeLinecap="round" /><circle cx="80" cy="76" r="2.8" fill="hsl(var(--warning))" />
        </g>
      )
    default:
      return (
        <g>
          <path d="M48 30h28c4 0 4 2 4 6v58c0-4-2-6-6-6H48Z" fill={paper} stroke={line} strokeWidth="1.5" />
          <path d="M112 30H84c-4 0-4 2-4 6v58c0-4 2-6 6-6h26Z" fill={paper} stroke={s} strokeWidth="2" />
          <path d="M56 44h16M56 54h16M56 64h12M88 44h16M88 54h16M88 64h10" stroke={line} strokeWidth="2.5" strokeLinecap="round" />
        </g>
      )
  }
}
