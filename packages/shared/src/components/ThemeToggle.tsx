import { useState } from "react";
import { Palette } from "@phosphor-icons/react";
import { THEMES, useTheme } from "@/store/theme";
import { useT } from "@/lib/i18n";

// Sidebar'dagi mavzu tanlagich: tugma joriy mavzu nomini ko'rsatadi,
// bosilganda 9 ta mavzu namunasi bilan oyna ochiladi (mobil bilan bir xil to'plam).
export function ThemeToggle() {
  const { theme, set } = useTheme();
  const [open, setOpen] = useState(false);
  const t = useT();

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={t("theme.title")}
        style={{
          display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "9px 12px",
          border: "1px solid var(--border)", borderRadius: 11, background: "var(--surface)",
          color: "var(--text3)", cursor: "pointer", font: "inherit", marginBottom: 8,
        }}
      >
        <Palette size={18} weight="fill" color="var(--accent-strong)" />
        <span style={{ flex: 1, textAlign: "left", fontSize: 13, fontWeight: 600 }}>{t(`theme.${theme}`)}</span>
        <span style={{ width: 16, height: 16, borderRadius: 6, flex: "none", background: "var(--accent)", border: "1px solid var(--border-input)" }} />
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{ position: "fixed", inset: 0, zIndex: 400, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 18, padding: 22, width: 430, maxWidth: "92vw" }}>
            <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 16, color: "var(--text)" }}>{t("theme.pick")}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {THEMES.map((th) => {
                const on = theme === th.id;
                return (
                  <button key={th.id} onClick={() => { set(th.id); setOpen(false); }}
                    style={{ border: "none", background: "none", cursor: "pointer", padding: 0, font: "inherit" }}>
                    <div style={{
                      height: 64, borderRadius: 12, background: th.bg, position: "relative", overflow: "hidden",
                      border: on ? `2.5px solid ${th.accent}` : "1px solid var(--border-input)",
                    }}>
                      <div style={{ position: "absolute", left: 10, top: 12, width: 42, height: 8, borderRadius: 4, background: th.accent }} />
                      <div style={{ position: "absolute", left: 10, top: 27, width: 62, height: 7, borderRadius: 3, background: th.card, border: "1px solid rgba(128,128,150,0.25)" }} />
                      <div style={{ position: "absolute", left: 10, top: 40, width: 34, height: 7, borderRadius: 3, background: th.card, border: "1px solid rgba(128,128,150,0.25)" }} />
                      {on && (
                        <div style={{ position: "absolute", right: 6, top: 6, width: 16, height: 16, borderRadius: "50%", background: th.accent, color: "#fff", fontSize: 11, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>✓</div>
                      )}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 12, fontWeight: on ? 800 : 600, color: on ? "var(--accent-strong)" : "var(--text2)", textAlign: "center" }}>
                      {t(`theme.${th.id}`)}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
