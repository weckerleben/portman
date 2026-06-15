/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Control-room palette. Tokens also live in src/styles/tokens.css.
        ink: {
          900: "#0a0c10",
          800: "#0f131a",
          700: "#161b24",
          600: "#1e2530",
          500: "#2a323f",
        },
        haze: {
          400: "#8b97a8",
          300: "#aab4c2",
          200: "#cdd4de",
        },
        signal: {
          managed: "#34d399", // emerald — owned by portman
          reserved: "#fbbf24", // amber — held, not yet active
          rogue: "#f87171", // red — bound outside portman (unauthorized)
          idle: "#64748b", // slate — free / inactive
        },
        accent: {
          DEFAULT: "#5eead4",
          deep: "#0d9488",
        },
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["'Inter'", "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 12px 40px -12px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(94,234,212,0.25), 0 0 24px -6px rgba(94,234,212,0.35)",
      },
    },
  },
  plugins: [],
};
