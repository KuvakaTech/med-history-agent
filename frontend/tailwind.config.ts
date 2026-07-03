import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Primary brand color — update DEFAULT here to retheme the entire app.
        // Tailwind auto-generates bg-brand, text-brand, border-brand, ring-brand, etc.
        brand: {
          DEFAULT: "#33049f",
          dark: "#28037d",    // hover / pressed states
          light: "#f0eaff",   // very light tint for backgrounds
          muted: "#ede9fe",   // subtle accent backgrounds
        },
      },
      fontFamily: {
        sans: ["var(--font-jakarta)", "system-ui", "sans-serif"],
        display: ["Noto Serif JP", "Noto Serif JP Fallback", "Georgia", "serif"],
      },
      animation: {
        "pulse-ring": "pulse-ring 1.2s ease-in-out infinite",
        "spin-slow": "spin 0.7s linear infinite",
      },
      keyframes: {
        "pulse-ring": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(239,68,68,0.3)" },
          "50%": { boxShadow: "0 0 0 6px rgba(239,68,68,0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
