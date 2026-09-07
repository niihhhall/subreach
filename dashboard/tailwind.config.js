/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#FFFFF5',
          card: '#FFFFFF',
          sidebar: '#FFFFFF',
          elevated: '#FDFBF2',
        },
        brand: {
          50: '#EEF4FE',
          100: '#DCE8FD',
          200: '#B9D1FB',
          300: '#8AB3F8',
          400: '#5A93F0',
          500: '#2E74E0',
          600: '#0B5ACF',
          700: '#0949A6',
          800: '#083C88',
          900: '#07326E',
          DEFAULT: '#0B5ACF',
          dark: '#0949A6',
          muted: 'rgba(11,90,207,0.08)',
        },
        ink: {
          DEFAULT: '#101828',
          soft: '#344054',
          muted: '#667085',
          faint: '#98A2B3',
        },
        accent: {
          DEFAULT: '#0B5ACF',
          dark: '#0949A6',
          muted: 'rgba(11,90,207,0.08)',
        },
        border: {
          DEFAULT: 'rgba(16,24,40,0.08)',
          hover: 'rgba(11,90,207,0.35)',
        }
      },

      fontFamily: {
        sans: ['Poppins', 'Inter', 'sans-serif'],
        display: ['Cabinet Grotesk', 'Poppins', 'sans-serif'],
        mono: ['DM Mono', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)',
        lift: '0 12px 32px -8px rgba(11,90,207,0.18), 0 4px 12px rgba(16,24,40,0.06)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-up': 'fadeUp 0.5s ease both',
        'fade-right': 'fadeRight 0.4s ease both',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeRight: {
          '0%': { opacity: '0', transform: 'translateX(-6px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
}
