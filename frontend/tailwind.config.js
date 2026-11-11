/** @type {import('tailwindcss').Config} */
const c = (v) => `hsl(var(--${v}) / <alpha-value>)`
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1.5rem' },
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Noto Sans CJK SC"', '"Source Han Sans SC"', 'sans-serif'],
        serif: ['"Songti SC"', '"STSong"', '"Noto Serif CJK SC"', '"Source Han Serif SC"', 'serif'],
        mono: ['"SF Mono"', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        border: c('border'),
        input: c('input'),
        ring: c('ring'),
        background: c('background'),
        foreground: c('foreground'),
        surface: c('surface'),
        subtle: c('subtle'),
        primary: { DEFAULT: c('primary'), foreground: c('primary-foreground'), soft: c('primary-soft') },
        muted: { DEFAULT: c('muted'), foreground: c('muted-foreground') },
        accent: { DEFAULT: c('accent'), foreground: c('accent-foreground') },
        success: { DEFAULT: c('success'), soft: c('success-soft') },
        warning: { DEFAULT: c('warning'), soft: c('warning-soft') },
        danger: { DEFAULT: c('danger'), soft: c('danger-soft') },
        popover: { DEFAULT: c('popover'), foreground: c('foreground') },
      },
      borderRadius: { lg: '12px', md: '9px', sm: '6px', xl: '16px', '2xl': '20px' },
      boxShadow: {
        xs: '0 1px 2px 0 rgb(15 23 42 / 0.04)',
        card: '0 1px 2px rgb(15 23 42 / 0.04), 0 1px 1px rgb(15 23 42 / 0.02)',
        lift: '0 2px 4px rgb(15 23 42 / 0.04), 0 8px 24px -6px rgb(15 23 42 / 0.10)',
        pop: '0 12px 40px -8px rgb(15 23 42 / 0.22), 0 2px 6px rgb(15 23 42 / 0.06)',
        glow: '0 0 0 4px hsl(var(--primary) / 0.12)',
      },
      keyframes: {
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        'fade-in': { from: { opacity: 0 }, to: { opacity: 1 } },
        'slide-in-right': { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
        'zoom-in': { from: { opacity: 0, transform: 'scale(.97) translateY(4px)' }, to: { opacity: 1, transform: 'scale(1) translateY(0)' } },
        'flash': { '0%,100%': { backgroundColor: 'hsl(var(--warning) / 0.35)' }, '50%': { backgroundColor: 'hsl(var(--warning) / 0.6)' } },
        stripes: { from: { backgroundPosition: '0 0' }, to: { backgroundPosition: '24px 0' } },
      },
      animation: {
        shimmer: 'shimmer 1.6s infinite',
        'fade-in': 'fade-in .18s ease-out',
        'slide-in-right': 'slide-in-right .26s cubic-bezier(.2,.8,.2,1)',
        'zoom-in': 'zoom-in .18s cubic-bezier(.2,.8,.2,1)',
        flash: 'flash 1.2s ease-in-out 2',
        stripes: 'stripes 1s linear infinite',
      },
    },
  },
  plugins: [],
}
