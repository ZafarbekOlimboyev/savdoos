import { Moon, Sun } from "@phosphor-icons/react";
import { useTheme } from "@/store/theme";
import { useT } from "@/lib/i18n";

// Dizayn: sidebar'dagi kun/tun almashtirgich (ikonka + yorliq + switch trek/knob).
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const t = useT();
  return (
    <button
      onClick={toggle}
      title={t("theme.title")}
      style={{
        display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "9px 12px",
        border: "1px solid var(--border)", borderRadius: 11, background: "var(--surface)",
        color: "var(--text3)", cursor: "pointer", font: "inherit", marginBottom: 8,
      }}
    >
      {dark ? <Moon size={18} weight="fill" color="var(--accent-strong)" /> : <Sun size={18} weight="fill" color="var(--accent-strong)" />}
      <span style={{ flex: 1, textAlign: "left", fontSize: 13, fontWeight: 600 }}>
        {dark ? t("theme.night") : t("theme.day")}
      </span>
      <span style={{ position: "relative", width: 38, height: 22, borderRadius: 11, flex: "none", background: dark ? "#6d5dd3" : "var(--border-input)", transition: "background 0.15s" }}>
        <span style={{ position: "absolute", top: 2, left: dark ? 18 : 2, width: 18, height: 18, borderRadius: "50%", background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.25)", transition: "left 0.15s" }} />
      </span>
    </button>
  );
}
