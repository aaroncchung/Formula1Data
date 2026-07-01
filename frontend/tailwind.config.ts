import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        carbon: "#06080d",
        graphite: "#111722",
        panel: "#171d28",
        line: "#283246",
        redline: "#f33d3d",
        aqua: "#2de0c8",
        amber: "#f5b83d"
      },
      boxShadow: {
        panel: "0 16px 50px rgba(0, 0, 0, 0.35)"
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;

