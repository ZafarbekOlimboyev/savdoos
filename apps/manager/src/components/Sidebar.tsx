import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ArrowUUpLeft,
  Buildings,
  CalendarX,
  CashRegister,
  ChartBar,
  ClipboardText,
  ClockCountdown,
  Gear,
  IdentificationBadge,
  ListChecks,
  Package,
  SealQuestion,
  Stack,
  Trash,
  ShoppingBag,
  Scales,
  SignOut,
  SquaresFour,
  Storefront,
  TrendUp,
  Users,
} from "@phosphor-icons/react";
import { useAuth } from "@/store/auth";
import { useOnline } from "@/lib/sync";
import { UpdateItem } from "@/components/UpdateItem";
import { useT } from "@/lib/i18n";
import { useAvailability } from "@/components/lotui";

type Item = { key: string; label: string; Icon: typeof SquaresFour; to: string; group: string };

const ITEMS: Item[] = [
  { key: "dashboard", label: "Dashboard", Icon: SquaresFour, to: "/", group: "ASOSIY" },
  { key: "sotuvlar", label: "Sotuvlar", Icon: TrendUp, to: "/sotuvlar", group: "SAVDO" },
  { key: "qaytarishlar", label: "Qaytarishlar", Icon: ArrowUUpLeft, to: "/qaytarishlar", group: "SAVDO" },
  { key: "mijozlar", label: "Mijozlar", Icon: Users, to: "/mijozlar", group: "SAVDO" },
  { key: "mahsulotlar", label: "Mahsulotlar / Ombor", Icon: Package, to: "/mahsulotlar", group: "OMBOR" },
  { key: "xaridlar", label: "Xaridlar", Icon: ShoppingBag, to: "/xaridlar", group: "OMBOR" },
  // Phase 4B — partiya ekranlari. Kuzatuv YOQILMAGAN do'konda ular MENYUDA ham
  // ko'rinmaydi: yarim ishlaydigan bo'lim "ish jarayoni" bo'lib ko'rinmasin.
  { key: "partiyalar", label: "Partiyalar", Icon: Stack, to: "/partiyalar", group: "OMBOR" },
  { key: "muddat", label: "Yaroqlilik muddati", Icon: CalendarX, to: "/muddat", group: "OMBOR" },
  { key: "inventarizatsiya", label: "Inventarizatsiya", Icon: ListChecks, to: "/inventarizatsiya", group: "OMBOR" },
  { key: "hisobdan", label: "Hisobdan chiqarish", Icon: Trash, to: "/hisobdan-chiqarish", group: "OMBOR" },
  { key: "qoldiq", label: "Aniqlanmagan qoldiq", Icon: SealQuestion, to: "/aniqlanmagan-qoldiq", group: "OMBOR" },
  { key: "hisobotlar", label: "Hisobotlar", Icon: ChartBar, to: "/hisobotlar", group: "BOSHQARUV" },
  { key: "xodimlar", label: "Xodimlar", Icon: IdentificationBadge, to: "/xodimlar", group: "BOSHQARUV" },
  { key: "filiallar", label: "Filiallar", Icon: Buildings, to: "/filiallar", group: "BOSHQARUV" },
  { key: "kassalar", label: "Kassalar", Icon: CashRegister, to: "/kassalar", group: "BOSHQARUV" },
  { key: "audit", label: "Audit jurnali", Icon: ClipboardText, to: "/audit", group: "BOSHQARUV" },
  { key: "smena", label: "Smena", Icon: ClockCountdown, to: "/smena", group: "BOSHQARUV" },
  { key: "tarozilar", label: "Tarozilar", Icon: Scales, to: "/tarozilar", group: "USKUNALAR" },
  { key: "sozlamalar", label: "Sozlamalar", Icon: Gear, to: "/sozlamalar", group: "TIZIM" },
];

const GROUPS = ["ASOSIY", "SAVDO", "OMBOR", "BOSHQARUV", "USKUNALAR", "TIZIM"];

// Har bo'lim uchun kerakli ruxsat — yo'q bo'lsa menyuda ko'rinmaydi (403 o'rniga).
// Dashboard har doim ochiq (kirish nuqtasi).
const ITEM_PERM: Record<string, string> = {
  sotuvlar: "sotuvlar.view", qaytarishlar: "qaytarishlar.view", mijozlar: "mijozlar.view",
  mahsulotlar: "mahsulotlar.view", xaridlar: "xaridlar.view",
  partiyalar: "ombor.view", muddat: "ombor.view", inventarizatsiya: "ombor.view",
  hisobdan: "ombor.edit", qoldiq: "ombor.view",
  hisobotlar: "hisobot.view", xodimlar: "xodimlar.view", filiallar: "hisobot.view",
  kassalar: "sozlamalar.view",
  audit: "hisobot.view", smena: "hisobot.view",
  tarozilar: "sozlamalar.view", sozlamalar: "sozlamalar.view",
};

// Partiya bo'limlari — kuzatuv YOQILGANDA ko'rinadi (server aytadi).
const LOT_KEYS = new Set(["partiyalar", "muddat", "inventarizatsiya", "hisobdan", "qoldiq"]);

export function Sidebar() {
  const { pathname } = useLocation();
  const { employee, logout } = useAuth();
  const online = useOnline();
  const t = useT();
  const av = useAvailability();
  // ⚠️  QARORNI SERVER BERADI. Ilgari bu yerda `tracked_products > 0` hisoblanardi —
  //     u «huquqi bor, lekin hali yoqmagan» do'konni ham, o'chirilgan mahsulot
  //     ortidagi OCHIQ QARZNI ham yashirardi (pul ekrandan g'oyib bo'lardi).
  const lotsOn = !!av.data && av.data.section_visible;
  // ⚠️  NAVIGATSIYADA QAYTA TEKSHIRILADI (TTL doirasida). Yon panel bir marta
  //     ulanadi: birinchi mahsulotga kuzatuv yoqilganda menyu ilova QAYTA ISHGA
  //     TUSHMAGUNCHA paydo bo'lmasdi.
  useEffect(() => { av.revalidate(); }, [pathname]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Storefront size={18} weight="fill" /></div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.02em", lineHeight: 1 }}>
            SavdoOS <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 700 }}>Manager</span>
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.08em", marginTop: 3 }}>{t("brand.manager")}</div>
        </div>
      </div>

      <nav className="nav">
        {GROUPS.map((g) => {
          const perms = employee?.permissions || [];
          const can = (key: string) => {
            const need = ITEM_PERM[key];
            return !need || perms.includes(need);
          };
          const items = ITEMS.filter((i) => i.group === g && can(i.key)
            && (!LOT_KEYS.has(i.key) || lotsOn));
          if (!items.length) return null;
          return (
            <div key={g}>
              <div className="nav-group">{t("group." + g)}</div>
              {items.map(({ key, label, Icon, to }) => {
                const on = to === "/" ? pathname === "/" : pathname.startsWith(to);
                return (
                  // ⚠️  `aria-label` DOIM beriladi: tor ekranda yozuv CSS bilan
                  //     yashiriladi va ekran o'quvchi uchun havola NOMSIZ qolardi
                  //     (faqat manzil o'qilardi).
                  <Link key={key} to={to} title={t("nav." + key)} aria-label={t("nav." + key)}
                        aria-current={on ? "page" : undefined}
                        className={"nav-item" + (on ? " on" : "")}>
                    <Icon size={18} weight={on ? "fill" : "regular"} />
                    <span className="side-label">{t("nav." + key)}</span>
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <UpdateItem />

      {/* ⚠️  TOR EKRANDA MATN YASHIRINADI — holat FAQAT RANGGA qolmasin:
          `title` va ekran o'quvchi uchun `.sr-only` matn har doim turadi. */}
      <div title={online ? t("common.online") : t("common.offline")}
           style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 11px", borderRadius: 9, marginBottom: 6, background: online ? "var(--ok-soft)" : "var(--warn-soft)", color: online ? "var(--ok)" : "var(--warn)", fontSize: 11.5, fontWeight: 600 }}>
        <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "var(--ok)" : "var(--warn)" }} />
        <span className="side-label">{online ? t("common.online") : t("common.offline")}</span>
        <span className="sr-only">{online ? t("common.online") : t("common.offline")}</span>
      </div>

      <button onClick={logout} title={t("common.logout")} aria-label={t("common.logout")}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: 10, borderRadius: 11, background: "var(--surface)", border: "none", cursor: "pointer", textAlign: "left", font: "inherit" }}>
        <div style={{ width: 30, height: 30, borderRadius: "50%", background: "#6d5dd3", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600 }}>
          {(employee?.full_name || "?").charAt(0)}
        </div>
        <div className="side-label" style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.1 }}>{employee?.full_name}</div>
          <div style={{ fontSize: 10.5, color: "var(--muted)" }}>{employee?.role_name} · {t("common.logout")}</div>
        </div>
        <SignOut size={16} color="var(--faint)" className="side-label" />
      </button>
    </aside>
  );
}
