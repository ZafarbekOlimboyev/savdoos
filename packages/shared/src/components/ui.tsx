import { useEffect, useRef, useState, type ReactNode } from "react";
import { get } from "@/lib/api";
import { useT } from "@/lib/i18n";

// onBack berilsa — CHAP tomonda "← Orqaga" tugmasi (barcha ichki sahifalarда bir xil joyda).
export function Topbar({ title, sub, right, onBack }: { title: string; sub?: string; right?: ReactNode; onBack?: () => void }) {
  const t = useT();
  return (
    <div className="topbar">
      <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
        {onBack && (
          <button className="btn btn-ghost" onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 7, height: 42, flex: "none" }}>
            ← {t("prod.back")}
          </button>
        )}
        <div style={{ minWidth: 0 }}>
          <div className="h1" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
          {sub && <div className="sub">{sub}</div>}
        </div>
      </div>
      {right}
    </div>
  );
}

export function Stat({ label, value, color, note }: { label: string; value: ReactNode; color?: string; note?: string }) {
  return (
    <div className="card">
      <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>{label}</div>
      <div className="tabular" style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 10, color: color || "var(--ink)" }}>{value}</div>
      {note && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{note}</div>}
    </div>
  );
}

export function useGet<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  // Race himoyasi: faqat eng so'nggi so'rov natijasi qabul qilinadi
  const seq = useRef(0);
  function run(resetData: boolean) {
    const my = ++seq.current;
    if (resetData) setData(null);
    setLoading(true);
    get<T>(path)
      .then((d) => { if (my === seq.current) { setData(d); setErr(""); } })
      .catch((e) => { if (my === seq.current) setErr(e.message); })
      .finally(() => { if (my === seq.current) setLoading(false); });
  }
  const reload = () => run(false);
  useEffect(() => { run(true); /* eslint-disable-next-line */ }, [path]);
  return { data, err, loading, reload };
}

export const inputStyle: React.CSSProperties = {
  height: 44, padding: "0 14px", border: "1.5px solid var(--border-input)", borderRadius: 11,
  font: "inherit", fontSize: 14, outline: "none", width: "100%", boxSizing: "border-box",
  background: "var(--card)", color: "var(--text)",
};

export function Modal({ children, onClose, width = 440 }: { children: ReactNode; onClose: () => void; width?: number }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 30 }}>
      <div onClick={(e) => e.stopPropagation()} className="modal-scroll" style={{ width, maxHeight: "86vh", overflow: "auto", background: "var(--card)", borderRadius: 20, padding: 24 }}>
        {children}
      </div>
    </div>
  );
}

export const th: React.CSSProperties = { padding: "13px 16px", fontWeight: 600, textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)" };
export const td: React.CSSProperties = { padding: "13px 16px", fontSize: 13.5, borderTop: "1px solid var(--border-soft)" };
