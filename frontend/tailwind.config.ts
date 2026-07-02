import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: {
          DEFAULT: 'var(--surface)',
          2: 'var(--surface-2)',
          3: 'var(--surface-3)',
        },
        line: {
          DEFAULT: 'var(--line)',
          strong: 'var(--line-strong)',
        },
        ink: {
          DEFAULT: 'var(--ink)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
          4: 'var(--ink-4)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          bg: 'var(--accent-bg)',
          line: 'var(--accent-line)',
        },
        ok: { DEFAULT: 'var(--ok)', bg: 'var(--ok-bg)' },
        warn: { DEFAULT: 'var(--warn)', bg: 'var(--warn-bg)' },
        err: { DEFAULT: 'var(--err)', bg: 'var(--err-bg)' },
        info: { DEFAULT: 'var(--info)', bg: 'var(--info-bg)' },
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '10': ['10px', { lineHeight: '1.4' }],
        '11': ['11px', { lineHeight: '1.4' }],
        '12': ['12px', { lineHeight: '1.45' }],
        '13': ['13px', { lineHeight: '1.45' }],
        '14': ['14px', { lineHeight: '1.4' }],
        '16': ['16px', { lineHeight: '1.3' }],
        '18': ['18px', { lineHeight: '1.3' }],
      },
      borderRadius: {
        sm: '2px',
        DEFAULT: '3px',
        md: '3px',
      },
      height: {
        appbar: '44px',
        navbar: '36px',
        statusbar: '24px',
        btn: '26px',
        'btn-sm': '22px',
        'btn-lg': '32px',
        input: '28px',
      },
      width: {
        sidebar: '200px',
      },
      letterSpacing: {
        label: '0.06em',
        tight2: '-0.01em',
        tight3: '-0.015em',
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

export default config
