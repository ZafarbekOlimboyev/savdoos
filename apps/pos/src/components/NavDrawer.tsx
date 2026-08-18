import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ArrowUUpLeft,
  ChartLineUp,
  ClockCountdown,
  ShoppingCartSimple,
  SignOut,
  Storefront,
  Users,
  X,
} from "@phosphor-icons/react";
import { useAuth } from "@/store/auth";
import { useNav } from "@/store/nav";
import { readPrefs } from "@/lib/prefs";
import { ThemeToggle } from "@/components/ThemeToggle";

// Dizayn: "POS Kassa.dc.html" — yashirin drawer sidebar (hamburger orqali ochiladi).
const ITEMS = [
  { key: "kassa", label: "Kassa", to: "/", Icon: ShoppingCartSimple },
  { key: "sotuvlarim", label: "Sotuvlarim", to: "/sotuvlarim", Icon: ChartLineUp },
  { key: "qaytarishlar", label: "Qaytarishlar", to: "/qaytarishlar", Icon: ArrowUUpLeft },
  { key: "mijozlar", label: "Mijozlar", to: "/mijozlar", Icon: Users },
  { key: "smena", label: "Smena", to: "/smena", Icon: ClockCountdown },
];

export function NavDrawer() {
  const { open, closeNav } = useNav();
  const { pathname } = useLocation();
  const { employee, logout } = useAuth();

  // Route almashsa yoki Escape bosilsa — drawer yopiladi
  useEffect(() => { closeNav(); }, [pathname, closeNav]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeNav(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeNav]);

  if (!open) return null;

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
    <div onClick={closeNav} style={{ position: "fixed", inset: 0, zIndex: 30, background: "rgba(8,10,18,0.45)" }}>
      <aside
        onClick={(e) => e.stopPropagation()}
        style={{ position: "absolute", left: 0, top: 0, width: 250, height: "100%", background: "var(--card)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", padding: "20px 14px", boxShadow: "0 20px 50px rgba(0,0,0,0.35)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 4px 22px" }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: "#6d5dd3", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}>
            <Storefront size={18} weight="fill" />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em", lineHeight: 1 }}>SavdoOS</div>
            <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.08em", marginTop: 3 }}>SODDA · TEZ · OSON</div>
          </div>
          <button onClick={closeNav} style={{ width: 30, height: 30, border: "none", background: "var(--surface)", borderRadius: 8, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <X size={15} />
          </button>
        </div>

        <div style={{ fontSize: 10, color: "var(--faint)", letterSpacing: "0.1em", textTransform: "uppercase", padding: "0 11px 8px" }}>Kassa</div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
          {items.map(({ key, label, to, Icon }) => {
            const on = to === "/" ? pathname === "/" : pathname.startsWith(to);
            return (
              <Link
                key={key}
                to={to}
                onClick={closeNav}
                style={{ display: "flex", alignItems: "center", gap: 11, padding: "10px 11px", borderRadius: 9, background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent-strong)" : "var(--text3)", fontSize: 14, textDecoration: "none", fontWeight: on ? 600 : 500 }}
              >
                <Icon size={19} weight={on ? "fill" : "regular"} />
                {label}
              </Link>
            );
          })}
        </nav>

        <ThemeToggle />

        <button onClick={logout} style={{ display: "flex", alignItems: "center", gap: 10, padding: 10, borderRadius: 10, background: "var(--surface)", border: "none", cursor: "pointer", textAlign: "left", font: "inherit" }}>
          <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#6d5dd3", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600 }}>{initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>{shortName}</div>
            <div style={{ fontSize: 10.5, color: "var(--muted)" }}>{employee?.role_name} · Chiqish</div>
          </div>
          <SignOut size={16} color="var(--faint)" />
        </button>
      </aside>
    </div>
  );
}
