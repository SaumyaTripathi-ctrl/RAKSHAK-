import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

// Brand: green #2E7D32, saffron #E87A1E, navy #1F4E79. Semantic colours come from CSS variables (light/dark).
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        safe: "hsl(var(--safe))",
        warn: "hsl(var(--warn))",
        crit: "hsl(var(--crit))",
        brand: { green: "#2E7D32", saffron: "#E87A1E", navy: "#1F4E79" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      keyframes: {
        "pulse-ring": { "0%": { transform: "scale(0.9)", opacity: "0.8" }, "100%": { transform: "scale(2.2)", opacity: "0" } },
      },
      animation: { "pulse-ring": "pulse-ring 1.6s ease-out infinite" },
    },
  },
  plugins: [animate],
} satisfies Config;
