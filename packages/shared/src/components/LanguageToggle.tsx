import { Translate } from "@phosphor-icons/react";
import { useLang, LANGS } from "@/store/lang";

// Sidebar'dagi til almashtirgich: RU / KY / UZ segmentli tugma.
export function LanguageToggle() {
  const { lang, set } = useLang();
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "7px 10px",
        border: "1px solid var(--border)", borderRadius: 11, background: "var(--surface)", marginBottom: 8,
      }}
    >
      <Translate size={17} weight="fill" color="var(--accent-strong)" style={{ flex: "none" }} />
      <div style={{ display: "flex", gap: 4, flex: 1 }}>
        {LANGS.map((l) => {
          const on = lang === l.code;
          return (
            <button
              key={l.code}
              onClick={() => set(l.code)}
              title={l.native}
              style={{
                flex: 1, height: 26, borderRadius: 8, border: "none", cursor: "pointer", font: "inherit",
                fontSize: 11.5, fontWeight: 700, letterSpacing: "0.02em",
                background: on ? "#6d5dd3" : "transparent", color: on ? "#fff" : "var(--text3)",
              }}
            >
              {l.code.toUpperCase()}
            </button>
          );
        })}
      </div>
    </div>
  );
}
