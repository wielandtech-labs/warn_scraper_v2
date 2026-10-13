/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "selector",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      /* The WARN Index palette. `slate` and `sky` are REMAPPED rather than
         renamed: ~850 class usages across the app pick up the identity
         without churn. Read `slate-*` as "ink/paper neutrals" (warm, not
         blue-gray) and `sky-*` as "the interactive accent". Hex values mirror
         src/lib/themeColors.ts, which the charts read from JS. */
      colors: {
        slate: {
          50: "#f9f9f7", // page plane
          100: "#f0efec",
          200: "#e1e0d9", // hairlines
          300: "#c3c2b7",
          400: "#a3a199",
          500: "#6e6c66", // secondary text (5.3:1 on white)
          600: "#52514e",
          700: "#3d3c39",
          800: "#2c2c2a",
          900: "#1a1a19", // dark card / chart surface
          950: "#0d0d0d", // dark page plane
        },
        sky: {
          50: "#eef5fd",
          100: "#cde2fb",
          200: "#9ec5f4",
          300: "#6da7ec",
          400: "#3987e5",
          500: "#2a78d6",
          600: "#256abf",
          700: "#1c5cab",
          800: "#104281",
          900: "#0d366b",
          950: "#0a2547",
        },
        /* Brand red — identity only (mark, hero, highlight rules). Not for
           status or data: red in a chart means "layoffs". */
        brand: {
          DEFAULT: "#DA2F25",
          soft: "#fbe9e7",
          dark: "#ef5a50",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        /* One self-hosted webfont (latin subset ~37 KB, font-display: swap)
           for headings and hero figures; body copy stays on the system stack. */
        display: ['"Fraunces Variable"', "Georgia", "Cambria", "serif"],
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "none" },
        },
        pulse_ring: {
          "0%": { transform: "scale(0.6)", opacity: "0.7" },
          "100%": { transform: "scale(2.4)", opacity: "0" },
        },
      },
      animation: {
        "fade-up": "fade-up 400ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "pulse-ring": "pulse_ring 2.4s cubic-bezier(0.2, 0.7, 0.2, 1) infinite",
      },
    },
  },
  plugins: [],
};
