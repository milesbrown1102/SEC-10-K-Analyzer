/** @type {import('tailwindcss').Config} */
// Colors are CSS variables (src/index.css) so charts and UI share one source.
// Channel form ("--x-c: r g b") lets Tailwind apply opacity: bg-raised/60.
const c = (name) => `rgb(var(--${name}-c) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: c("page"),
        surface: c("surface"),
        raised: c("raised"),
        line: "var(--line)",
        ink: { DEFAULT: c("ink"), 2: c("ink-2"), 3: c("ink-3") },
        accent: { DEFAULT: c("accent"), soft: "var(--accent-soft)" },
        good: c("good"),
        bad: c("bad"),
        warn: c("warn"),
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
