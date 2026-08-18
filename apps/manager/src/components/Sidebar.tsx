import { Link, useLocation } from "react-router-dom";
import {
  ArrowUUpLeft,
  ChartBar,
  ClipboardText,
  ClockCountdown,
  Gear,
  IdentificationBadge,
  Package,
  ShoppingBag,
  SignOut,
  SquaresFour,
  Storefront,
  TrendUp,
  Users,
} from "@phosphor-icons/react";
import { useAuth } from "@/store/auth";
import { useOnline } from "@/lib/sync";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UpdateItem } from "@/components/UpdateItem";

type Item = { key: string; label: string; Icon: typeof SquaresFour; to: string; group: string };

const ITEMS: Item[] = [
  { key: "dashboard", label: "Dashboard", Icon: SquaresFour, to: "/", group: "ASOSIY" },
  { key: "sotuvlar", label: "Sotuvlar", Icon: TrendUp, to: "/sotuvlar", group: "SAVDO" },
  { key: "qaytarishlar", label: "Qaytarishlar", Icon: ArrowUUpLeft, to: "/qaytarishlar", group: "SAVDO" },
  { key: "mijozlar", label: "Mijozlar", Icon: Users, to: "/mijozlar", group: "SAVDO" },
  { key: "mahsulotlar", label: "Mahsulotlar / Ombor", Icon: Package, to: "/mahsulotlar", group: "OMBOR" },
  { key: "xaridlar", label: "Xaridlar", Icon: ShoppingBag, to: "/xaridlar", group: "OMBOR" },
  { key: "hisobotlar", label: "Hisobotlar", Icon: ChartBar, to: "/hisobotlar", group: "BOSHQARUV" },
  { key: "xodimlar", label: "Xodimlar", Icon: IdentificationBadge, to: "/xodimlar", group: "BOSHQARUV" },
  { key: "audit", label: "Audit jurnali", Icon: ClipboardText, to: "/audit", group: "BOSHQARUV" },
  { key: "smena", label: "Smena", Icon: ClockCountdown, to: "/smena", group: "BOSHQARUV" },
  { key: "sozlamalar", label: "Sozlamalar", Icon: Gear, to: "/sozlamalar", group: "TIZIM" },
];

const GROUPS = ["ASOSIY", "SAVDO", "OMBOR", "BOSHQARUV", "TIZIM"];

export function Sidebar() {
  const { pathname } = useLocation();
  const { employee, logout } = useAuth();
  const online = useOnline();

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Storefront size={18} weight="fill" /></div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em", lineHeight: 1 }}>
            SavdoOS <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 700 }}>Manager</span>
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.08em", marginTop: 3 }}>BOSHQARUV</div>
        </div>
      </div>

      <nav className="nav">
        {GROUPS.map((g) => {
          const items = ITEMS.filter((i) => i.group === g);
          return (
            <div key={g}>
              <div className="nav-group">{g}</div>
              {items.map(({ key, label, Icon, to }) => {
                const on = to === "/" ? pathname === "/" : pathname.startsWith(to);
                return (
                  <Link key={key} to={to} className={"nav-item" + (on ? " on" : "")}>
                    <Icon size={18} weight={on ? "fill" : "regular"} />
                    {label}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <UpdateItem />
      <ThemeToggle />

      <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 11px", borderRadius: 9, marginBottom: 6, background: online ? "var(--ok-soft)" : "var(--warn-soft)", color: online ? "var(--ok)" : "var(--warn)", fontSize: 11.5, fontWeight: 600 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "var(--ok)" : "var(--warn)" }} />
        {online ? "Onlayn" : "Oflayn"}
      </div>

      <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 10, padding: 10, borderRadius: 11, background: "var(--surface)", border: "none", cursor: "pointer", textAlign: "left", font: "inherit" }}>
        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#6d5dd3", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600 }}>
          {(employee?.full_name || "?").charAt(0)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>{employee?.full_name}</div>
          <div style={{ fontSize: 10.5, color: "var(--muted)" }}>{employee?.role_name} · Chiqish</div>
        </div>
        <SignOut size={16} color="var(--faint)" />
      </button>
    </aside>
  );
}
