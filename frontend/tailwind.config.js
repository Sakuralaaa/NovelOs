/** @type {import('tailwindcss').Config} */
const c = (v) => `hsl(var(--${v}) / <alpha-value>)`
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1.5rem' },
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Noto Sans CJK SC"', '"Source Han Sans SC"', 'sans-serif'],
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
      borderRadius: { lg: '10px', md: '8px', sm: '6px', xl: '14px', '2xl': '18px' },
      boxShadow: {
        xs: '0 1px 2px 0 rgb(16 16 24 / 0.04)',
        card: '0 1px 2px rgb(16 16 24 / 0.035)',
        lift: '0 1px 2px rgb(16 16 24 / 0.04), 0 10px 28px -10px rgb(16 16 24 / 0.14)',
        pop: '0 12px 40px -8px rgb(15 23 42 / 0.22), 0 2px 6px rgb(15 23 42 / 0.06)',
        glow: '0 0 0 4px hsl(var(--primary) / 0.12)',
      },
      keyframes: {
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        'fade-in': { from: { opacity: 0 }, to: { opacity: 1 } },
        'slide-in-right': { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
        'zoom-in': { from: { opacity: 0, transform: 'scale(.97) translateY(4px)' }, to: { opacity: 1, transform: 'scale(1) translateY(0)' } },
        'flash': { '0%,100%': { backgroundColor: 'hsl(var(--warning) / 0.35)' }, '50%': { backgroundColor: 'hsl(var(--warning) / 0.6)' } },
        shake: { '0%,100%': { transform: 'translateX(0)' }, '20%,60%': { transform: 'translateX(-6px)' }, '40%,80%': { transform: 'translateX(6px)' } },
        stripes: { from: { backgroundPosition: '0 0' }, to: { backgroundPosition: '24px 0' } },
      },
      animation: {
        shimmer: 'shimmer 1.6s infinite',
        'fade-in': 'fade-in .18s ease-out',
        'slide-in-right': 'slide-in-right .26s cubic-bezier(.2,.8,.2,1)',
        'zoom-in': 'zoom-in .18s cubic-bezier(.2,.8,.2,1)',
        flash: 'flash 1.2s ease-in-out 2',
        stripes: 'stripes 1s linear infinite',
        shake: 'shake .4s ease-in-out',
      },
    },
  },
  plugins: [],
}
