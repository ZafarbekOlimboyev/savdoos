import { ArrowsClockwise, CloudArrowDown } from "@phosphor-icons/react";
import { useUpdate } from "@/store/update";
import { useT } from "@/lib/i18n";

// Telegram uslubidagi yangilanish tugmasi — sidebar PASTIDA doimiy turadi.
// Yuklab olinayotganda: progress qatori. Tayyor bo'lgach: accent "Yangilanish" tugmasi,
// bosilsa ilova ichidan yangilanadi (qayta ishga tushadi).
export function UpdateItem() {
  const { state, version, percent, download, install } = useUpdate();
  const t = useT();

  if (state === "idle") return null;

  if (state === "downloading") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", borderRadius: 11, background: "var(--surface)", marginBottom: 8 }}>
        <CloudArrowDown size={17} color="var(--accent-strong)" weight="fill" style={{ flex: "none" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text3)" }}>{t("update.downloading")}</div>
          <div style={{ height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden", marginTop: 4 }}>
            <div style={{ height: "100%", width: `${percent || 0}%`, background: "var(--accent)", borderRadius: 2, transition: "width 0.3s" }} />
          </div>
        </div>
        <span className="tabular" style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", flex: "none" }}>{percent || 0}%</span>
      </div>
    );
  }

  // "available" — yangilanish bor, hali yuklanmagan (bosilsa yuklab oladi)
  // "ready" — yuklab olindi (bosilsa o'rnatadi va qayta ishga tushadi)
  const isReady = state === "ready";
  return (
    <button
      onClick={isReady ? install : download}
      title={t("update.tooltip", { version: version || "" })}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center", gap: 9,
        width: "100%", padding: "11px 12px", border: "none", borderRadius: 11,
        background: "var(--accent)", color: "#fff", cursor: "pointer", font: "inherit",
        fontSize: 13.5, fontWeight: 700, marginBottom: 8,
        boxShadow: "0 6px 18px rgba(109,93,211,0.35)",
      }}
    >
      {isReady ? <ArrowsClockwise size={17} weight="bold" /> : <CloudArrowDown size={17} weight="fill" />}
      {isReady ? t("update.install") : t("update.ready")}{version ? ` · ${version}` : ""}
    </button>
  );
}
