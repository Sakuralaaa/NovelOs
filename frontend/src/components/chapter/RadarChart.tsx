/** 极简 SVG 雷达图（5 维审稿分） */
export function RadarChart({ data, size = 220 }: { data: { label: string; value: number }[]; size?: number }) {
  const c = size / 2, R = size / 2 - 34, n = data.length
  const pt = (i: number, r: number) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2
    return [c + Math.cos(a) * r, c + Math.sin(a) * r] as const
  }
  const poly = data.map((d, i) => pt(i, (Math.max(0, Math.min(100, d.value)) / 100) * R).join(',')).join(' ')
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mx-auto block">
      {[0.25, 0.5, 0.75, 1].map((k) => (
        <polygon key={k} points={data.map((_, i) => pt(i, R * k).join(',')).join(' ')} fill={k === 1 ? 'hsl(var(--subtle))' : 'none'} stroke="hsl(var(--border))" strokeWidth={1} />
      ))}
      {data.map((_, i) => { const [x, y] = pt(i, R); return <line key={i} x1={c} y1={c} x2={x} y2={y} stroke="hsl(var(--border))" /> })}
      <polygon points={poly} fill="hsl(var(--primary) / 0.18)" stroke="hsl(var(--primary))" strokeWidth={2} strokeLinejoin="round" style={{ transition: 'all .6s' }} />
      {data.map((d, i) => { const [x, y] = pt(i, (d.value / 100) * R); return <circle key={i} cx={x} cy={y} r={3} fill="hsl(var(--primary))" /> })}
      {data.map((d, i) => {
        const [x, y] = pt(i, R + 18)
        return (
          <g key={d.label}>
            <text x={x} y={y - 2} textAnchor="middle" fontSize={11.5} fill="hsl(var(--muted-foreground))">{d.label}</text>
            <text x={x} y={y + 12} textAnchor="middle" fontSize={11.5} fontWeight={600} fill="hsl(var(--foreground))">{Math.round(d.value)}</text>
          </g>
        )
      })}
    </svg>
  )
}

/** 半圆仪表（数值越低越好时 invert） */
export function Gauge({ value, label, invert, size = 150 }: { value: number; label: string; invert?: boolean; size?: number }) {
  const v = Math.max(0, Math.min(100, value))
  const r = size / 2 - 12, cx = size / 2, cy = size / 2
  const len = Math.PI * r
  const good = invert ? v <= 30 : v >= 70, mid = invert ? v <= 60 : v >= 40
  const color = good ? 'hsl(var(--success))' : mid ? 'hsl(var(--warning))' : 'hsl(var(--danger))'
  return (
    <div className="relative mx-auto" style={{ width: size, height: size / 2 + 14 }}>
      <svg width={size} height={size / 2 + 6}>
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="hsl(var(--muted))" strokeWidth={10} strokeLinecap="round" />
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - v / 100)} style={{ transition: 'stroke-dashoffset .8s cubic-bezier(.2,.8,.2,1)' }} />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center leading-none">
        <div className="num text-[26px] font-semibold" style={{ color }}>{Math.round(v)}</div>
        <div className="mt-1 text-[11.5px] text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}
