import { Link, useLocation } from "react-router-dom";
import { useAuth } from "@/store/auth";
import { useOnline } from "@/lib/sync";

type Item = { key: string; label: string; icon: string; to: string; group: string };

const ITEMS: Item[] = [
  { key: "dashboard", label: "Dashboard", icon: "📊", to: "/", group: "ASOSIY" },
  { key: "sotuvlar", label: "Sotuvlar", icon: "📈", to: "/sotuvlar", group: "SAVDO" },
  { key: "qaytarishlar", label: "Qaytarishlar", icon: "↩️", to: "/qaytarishlar", group: "SAVDO" },
  { key: "mijozlar", label: "Mijozlar", icon: "👥", to: "/mijozlar", group: "SAVDO" },
  { key: "mahsulotlar", label: "Mahsulotlar / Ombor", icon: "📦", to: "/mahsulotlar", group: "OMBOR" },
  { key: "xaridlar", label: "Xaridlar", icon: "🛍️", to: "/xaridlar", group: "OMBOR" },
  { key: "hisobotlar", label: "Hisobotlar", icon: "📉", to: "/hisobotlar", group: "BOSHQARUV" },
  { key: "xodimlar", label: "Xodimlar", icon: "🪪", to: "/xodimlar", group: "BOSHQARUV" },
  { key: "audit", label: "Audit jurnali", icon: "🧾", to: "/audit", group: "BOSHQARUV" },
  { key: "smena", label: "Smena", icon: "⏱️", to: "/smena", group: "BOSHQARUV" },
  { key: "sozlamalar", label: "Sozlamalar", icon: "⚙️", to: "/sozlamalar", group: "TIZIM" },
];

const GROUPS = ["ASOSIY", "SAVDO", "OMBOR", "BOSHQARUV", "TIZIM"];

export function Sidebar() {
  const { pathname } = useLocation();
  const { employee, logout } = useAuth();
  const online = useOnline();

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">S</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em", lineHeight: 1 }}>
            SavdoOS <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 700 }}>Manager</span>
          </div>
          <div style={{ fontSize: 10, color: "#9aa0b4", letterSpacing: "0.08em", marginTop: 3 }}>BOSHQARUV</div>
        </div>
      </div>

      <nav className="nav">
        {GROUPS.map((g) => {
          const items = ITEMS.filter((i) => i.group === g);
          return (
            <div key={g}>
              <div className="nav-group">{g}</div>
              {items.map((i) => {
                const on = i.to === "/" ? pathname === "/" : pathname.startsWith(i.to);
                return (
                  <Link key={i.key} to={i.to} className={"nav-item" + (on ? " on" : "")}>
                    <span style={{ fontSize: 16 }}>{i.icon}</span>
                    {i.label}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 11px", borderRadius: 9, marginBottom: 6, background: online ? "#e9f7ef" : "#fef3e2", color: online ? "#12915a" : "#b8730c", fontSize: 11.5, fontWeight: 600 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "#17b26a" : "#e08a12" }} />
        {online ? "Onlayn" : "Oflayn"}
      </div>

      <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 10, padding: 10, borderRadius: 11, background: "#f5f6fa", border: "none", cursor: "pointer", textAlign: "left" }}>
        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--accent)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600 }}>
          {(employee?.full_name || "?").charAt(0)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>{employee?.full_name}</div>
          <div style={{ fontSize: 10.5, color: "#9aa0b4" }}>{employee?.role_name} · Chiqish</div>
        </div>
      </button>
    </aside>
  );
}
