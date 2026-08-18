import { Link, useLocation } from "react-router-dom";
import {
  ArrowUUpLeft,
  ChartLineUp,
  ClockCountdown,
  ShoppingCartSimple,
  SignOut,
  Storefront,
  Users,
} from "@phosphor-icons/react";
import { useAuth } from "@/store/auth";
import { useOnline, usePendingCount } from "@/lib/sync";
import { readPrefs } from "@/lib/prefs";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UpdateItem } from "@/components/UpdateItem";

// Dizayn: "Sotuvlarim.dc.html" / "Smena.dc.html" — doimiy sidebar (232px).
const ITEMS = [
  { key: "kassa", label: "Kassa", to: "/", Icon: ShoppingCartSimple },
  { key: "sotuvlarim", label: "Sotuvlarim", to: "/sotuvlarim", Icon: ChartLineUp },
  { key: "qaytarishlar", label: "Qaytarishlar", to: "/qaytarishlar", Icon: ArrowUUpLeft },
  { key: "mijozlar", label: "Mijozlar", to: "/mijozlar", Icon: Users },
  { key: "smena", label: "Smena", to: "/smena", Icon: ClockCountdown },
];

export function Sidebar() {
  const { pathname } = useLocation();
  const { employee, logout } = useAuth();
  const online = useOnline();
  const pending = usePendingCount();

  // Dizayn: Qaytarishlar — returns yoqiq bo'lsa, Mijozlar — qarz yoqiq bo'lsa
  const prefs = readPrefs();
  const items = ITEMS.filter(
    (i) => (i.key !== "qaytarishlar" || prefs.returns) && (i.key !== "mijozlar" || prefs.qarz)
  );

  const initials = (employee?.full_name || "?")
    .split(" ")
    .map((w) => w.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const shortName = (() => {
    const parts = (employee?.full_name || "").split(" ");
    return parts.length > 1 ? `${parts[0]} ${parts[1].charAt(0)}.` : parts[0] || "";
  })();

  return (
    <aside style={{ width: 232, flex: "none", background: "var(--card)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", padding: "20px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px 22px" }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: "#6d5dd3", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}>
          <Storefront size={18} weight="fill" />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em", lineHeight: 1 }}>SavdoOS</div>
          <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.08em", marginTop: 3 }}>SODDA · TEZ · OSON</div>
        </div>
      </div>

      <div style={{ fontSize: 10, color: "var(--faint)", letterSpacing: "0.1em", textTransform: "uppercase", padding: "0 11px 8px" }}>Kassa</div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
        {items.map(({ key, label, to, Icon }) => {
          const on = to === "/" ? pathname === "/" : pathname.startsWith(to);
          return (
            <Link
              key={key}
              to={to}
              style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 11px", borderRadius: 9, background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent-strong)" : "var(--text3)", fontSize: 14, textDecoration: "none", fontWeight: on ? 600 : 500 }}
            >
              <Icon size={19} weight={on ? "fill" : "regular"} />
              {label}
            </Link>
          );
        })}
      </nav>

      <UpdateItem />
      <ThemeToggle />

      <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 11px", borderRadius: 9, marginBottom: 6, background: online ? "var(--ok-soft)" : "var(--warn-soft)", color: online ? "var(--ok)" : "var(--warn)", fontSize: 11.5, fontWeight: 600 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "var(--ok)" : "var(--warn)" }} />
        {online ? "Onlayn" : "Oflayn rejim"}{pending > 0 ? ` · ${pending} navbatda` : ""}
      </div>

      <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 10, padding: 10, borderRadius: 10, background: "var(--surface)", border: "none", cursor: "pointer", textAlign: "left", font: "inherit" }}>
        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#6d5dd3", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600 }}>{initials}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>{shortName}</div>
          <div style={{ fontSize: 10.5, color: "var(--muted)" }}>{employee?.role_name} · Chiqish</div>
        </div>
        <SignOut size={16} color="var(--faint)" />
      </button>
    </aside>
  );
}
