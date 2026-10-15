/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "#121419",
        panel: "#1D2027",
        panel2: "#262A33",
        line: "#383E49",
        primary: { DEFAULT: "#508CFF", hover: "#6A9DFF", muted: "#508CFF26" },
        fg: { DEFAULT: "#F5F6F9", muted: "#A3ABB9", faint: "#6B7382" },
        clip: { video: "#3D5A8C", audio: "#3F6E55", caption: "#6A5794", text: "#8C6A3D" },
        danger: "#F06A6A",
        success: "#4CC38A",
        warn: "#E8B65A",
      },
      fontFamily: { sans: ['"Inter Variable"', "system-ui", "sans-serif"] },
      fontSize: { "2xs": ["10px", "14px"], xs: ["11px", "16px"], sm: ["12px", "18px"], base: ["13px", "20px"] },
      borderRadius: { DEFAULT: "6px" },
    },
  },
  plugins: [],
};
