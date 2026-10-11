import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
  Barcode,
  Check,
  CheckCircle,
  CreditCard,
  DeviceMobile,
  List,
  MagnifyingGlass,
  Minus,
  Money,
  Notebook,
  Package,
  Plus,
  Printer,
  QrCode,
  ShoppingCart,
  Trash,
  Tray,
  User,
  UserPlus,
  Warning,
  X,
} from "@phosphor-icons/react";
import { get, post } from "@/lib/api";
import { companyCurrency, fmt } from "@/lib/format";
import { currentTillId, useShift } from "@/store/shift";
import { useCart } from "@/store/cart";
import { useAuth } from "@/store/auth";
import { useNav } from "@/store/nav";
import { useUpdate } from "@/store/update";
import { CACHE, cacheGet } from "@/lib/offline";
import { readPrefs } from "@/lib/prefs";
import { parseScaleBarcode, pluMatches } from "@/lib/scaleBarcode";
import { createWedge, isEditableTarget } from "@/lib/scanWedge";
import { useT } from "@/lib/i18n";
import { Modal } from "@/components/ui";
import { PrintStatus, useAutoPrint, usePrintDoc, type PrintTarget } from "@/components/PrintStatus";
import { cachedReceiptProfile } from "@/lib/printing";
import { BUILTIN_TEMPLATE, decRound, provisionalSaleReceipt, type ReceiptDTO } from "@/receipt";
import { clearFailed, failedSales, offlineSaleAllowed, offlineSaleReason, refreshCatalog, submitSale, useOnline, usePendingCount, useFailedCount } from "@/lib/sync";

interface Product { id: string; article_code: string; name: string; category_id: string | null; base_sell_price: number; stock: number; barcodes?: string[]; plu_code?: string | null; is_weighted?: boolean; sold_qty?: number; unit_code?: string; is_active?: boolean; }

// ── Chek (Phase 5F) ──────────────────────────────────────────────────────
// Serverga yuborilgan sotuv payload'i (chek uchun kerakli maydonlari).
interface SalePayload {
  items: { product_id: string; qty: number; unit_price: number }[];
  payment_method: string;
  payments?: { method: string; amount: number }[];
  given_amount: number | null;
  expected_total: number;
  client_uuid: string;
}

// Sotuv surati: AYNAN yuborilgan payload + savat nomlari (payload'da nom yo'q). Faqat oddiy
// ma'lumot — chek shu suratdan CHOP ETISH paytida quriladi (sotuv yo'lida chek kodi ishlamaydi).
// Oflayn — vaqtinchalik chek; onlayn — faqat ESKI server (chek marshruti yo'q) uchun zaxira.
interface SaleSnap {
  payload: SalePayload;
  lines: { name: string; weighted: boolean; unit: string | null }[]; // payload.items bilan bir xil tartib
  cashier: string | null;
  storeName: string;
  branchName: string | null;
  sold_at: string;
  /**
   * Sotuv paytidagi DO'KON valyutasi — TRANZAKSIYA SURATI.
   *
   * Chop etish paytida qayta o'qilmaydi: aks holda do'kon valyutasi oralig'ida
   * o'zgarsa, allaqachon sotilgan chek YANGI birlikda chiqardi. `null` — eski
   * server `employee.company_currency` ni bermagan (yorliq eski tilga-asoslangan
   * zaxiraga tushadi).
   */
  currency: string | null;
}

// Muvaffaqiyat ekrani. Chek endi summalarni bu yerdan OLMAYDI: onlayn — server DTO (`id` bo'yicha),
// oflayn — `snap` suratidan vaqtinchalik chek ("OFLAYN — VAQTINCHALIK" banneri bilan).
interface Paid {
  receipt_no: string;
  offline: boolean;
  uid?: string;
  id: string | null;
  client_uuid: string;
  snap: SaleSnap | null;
}

function localStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Chek profili yo'q (eski server yoki hali keshlanmagan) — 5F'dan oldingi chek kabi manzil/telefon va
// sarlavha/izoh keshdagi umumiy sozlamalardan (`GET /settings`: store_info, receipt).
function legacyShop(): { address: string | null; phone: string | null; header: string | null; footer: string | null } {
  const s = cacheGet<{ store_info?: Record<string, unknown>; receipt?: Record<string, unknown> }>(CACHE.settings, {});
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);
  return {
    address: str(s?.store_info?.address), phone: str(s?.store_info?.phone),
    header: str(s?.receipt?.header), footer: str(s?.receipt?.footer),
  };
}

/**
 * Oflayn VAQTINCHALIK chek — faqat yuborilgan payload qiymatlaridan (qty, unit_price, split summalar,
 * expected_total), hech narsa qayta hisoblanmaydi/to'qilmaydi. Bitta usul = [{usul, jami}] (server ham
 * shunday yozadi); naqd berildi/qaytim — server qoidasi: berildi = given_amount yoki jami.
 * Do'kon/shablon — keshdagi chek profili (bo'lmasa POS sozlamasidagi nom + umumiy sozlamalar).
 */
function offlineReceipt(s: SaleSnap): ReceiptDTO {
  const prof = cachedReceiptProfile();
  const legacy = prof ? null : legacyShop();
  const p = s.payload;
  const total = String(p.expected_total);
  const payments = p.payments && p.payments.length
    ? p.payments.map((x) => ({ method: x.method, amount: String(x.amount) }))
    : [{ method: p.payment_method, amount: total }];
  const cash = payments.length === 1 && payments[0].method === "cash";
  const given = cash ? (p.given_amount ?? p.expected_total) : null;
  return provisionalSaleReceipt({
    client_uuid: p.client_uuid,
    // Hujjat valyutasi SURATDAN (sotuv paytidagi), joriy do'kon sozlamasidan EMAS.
    currency: s.currency,
    lines: p.items.map((it, i) => ({
      name: s.lines[i]?.name ?? "",
      qty: String(it.qty),
      unit_price: String(it.unit_price),
      weighted: !!s.lines[i]?.weighted,
      unit: s.lines[i]?.unit ?? null,
    })),
    payments,
    given: given === null ? null : String(given),
    change: given === null ? null : String(Math.max(0, given - p.expected_total)),
    total,
    store: prof?.store ?? {
      name: s.storeName, branch_name: s.branchName, address: legacy?.address ?? null, phone: legacy?.phone ?? null, stir: null,
    },
    cashier: s.cashier,
    issued_at: s.sold_at,
    issued_at_local: localStamp(s.sold_at),
    template: prof?.effective ?? { ...BUILTIN_TEMPLATE, header: legacy?.header ?? null, footer: legacy?.footer ?? null },
  });
}

/**
 * ESKI server zaxirasi (5F'dan oldingi yoki unga qaytarilgan server — `/sales/{id}/receipt` YO'Q):
 * onlayn sotuvning o'z surati + serverning haqiqiy raqami/uid/id/vaqti. Sotuv serverda YOZILGAN —
 * `provisional: false` (oflayn banneri yo'q), chek 5F'dan oldingidek mahalliy ma'lumotdan chiqadi.
 * printing.ts uni FAQAT marshrut yo'q bo'lganda ishlatadi; marshrut bor bo'lsa chek doim server DTO'sidan.
 */
function legacyReceipt(paid: Paid, s: SaleSnap): ReceiptDTO {
  const d = offlineReceipt(s);
  return {
    ...d,
    provisional: false,
    doc: { ...d.doc, id: paid.id, number: paid.receipt_no, uid: paid.uid ?? null, is_offline: false, status: "completed" },
  };
}

function printTargetOf(paid: Paid): PrintTarget {
  const snap = paid.snap;
  return {
    doc_type: "SALE",
    doc_id: paid.id,
    client_uuid: paid.client_uuid,
    // Onlayn sotuvga vaqtinchalik DTO BERILMAYDI — chek faqat serverdan (haqiqiy raqam bilan).
    dto: paid.offline && snap ? () => offlineReceipt(snap) : undefined,
    // ...faqat eski server (chek marshruti yo'q) uchun zaxira — aks holda hech bir onlayn chek chiqmasdi.
    fallback: !paid.offline && paid.id && snap ? () => legacyReceipt(paid, snap) : undefined,
  };
}

/**
 * Qo'lda kiritilgan vazn → 0.001 kg, SERVER qoidasi bilan (satr o'nlik, ROUND_HALF_UP; server qty'ni
 * Numeric(14,3) da saqlaydi). Aks holda "0,3525" kassada 4 230, serverda 0.353 → 4 236: chek, kassa
 * va hisob bir-biridan farq qilardi. Float Math.round(kg*1000) ba'zan pastga ketadi (0,5005 → 0,500) — shu bois decRound.
 */
function kgOf(raw: string): number {
  const n = parseFloat((raw || "").replace(",", ".").replace(/[^0-9.]/g, "")) || 0;
  if (!Number.isFinite(n) || n <= 0) return 0;
  try {
    return Number(decRound(String(n), 3));
  } catch {
    return 0; // juda katta/yaroqsiz son — qo'shilmaydi
  }
}

// ── Kassir qidirib sotgan mahsulotlar — mahalliy hisob (grid'da ENG TEPADA turadi).
//    Undan keyin eng ko'p sotilganlar (sold_qty, serverdan), so'ng qolganlari. ──
const USAGE_KEY = "savdoos_pos_usage";
function readUsage(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(USAGE_KEY) || "{}"); } catch { return {}; }
}
function bumpUsage(id: string) {
  try {
    const u = readUsage();
    u[id] = Math.min((u[id] || 0) + 1, 99999);
    localStorage.setItem(USAGE_KEY, JSON.stringify(u));
  } catch { /* ignore */ }
}
interface Category { id: string; name: string }
interface CustomerRow { id: string; code: string; full_name: string; phone: string | null }

// A — brend binafsha (ikkala temada bir xil); AT/ASOFT — temaga bog'liq tokenlar
const A = "#6d5dd3", AT = "var(--accent-strong)", ASOFT = "var(--accent-soft)";
// Phase 7 (tasdiqlangan kassa maketi): ko'k — interaktiv urg'u, yashil — asosiy to'lov.
// ⚠️  FAQAT SHU EKRAN uchun mahalliy konstanta: global `--accent` O'ZGARTIRILMAYDI, aks holda
//     Manager va boshqa ekranlar ham rangini almashtirardi (doira: faqat kassa ekrani).
// ⚠️  Fon/sirt ranglari HAR DOIM `var(--...)` orqali — shunda tungi rejim buzilmaydi.
const B = "#2563eb", G = "#16a34a";

function posBars(uid: string) {
  const d = (uid || "").replace(/\D/g, "");
  const out: { w: string; bg: string }[] = [{ w: "2px", bg: "var(--text)" }, { w: "2px", bg: "transparent" }];
  for (let i = 0; i < d.length; i++) {
    const n = +d[i];
    out.push({ w: 1 + (n % 3) + "px", bg: "var(--text)" }, { w: 1 + ((n + i) % 3) + "px", bg: "transparent" }, { w: 1 + ((n * 3 + i) % 2) + "px", bg: "var(--text)" }, { w: "1px", bg: "transparent" });
  }
  out.push({ w: "2px", bg: "var(--text)" });
  return out;
}

// QA CART-04: dona mahsulot miqdorini QO'LDA kiritish — ±1 stepper yonida tahrirlanadigan maydon.
// Mahalliy `buf` bilan yozish tekis kechadi; blur/Enter'da absolyut miqdor saqlanadi (min 1, max 99999).
function CartQty({ id, qty }: { id: string; qty: number }) {
  const [buf, setBuf] = useState<string | null>(null);
  const setQty = useCart((s) => s.setQty);
  const delta = useCart((s) => s.delta);
  const commit = () => {
    if (buf !== null) {
      const n = parseInt(buf, 10);
      if (Number.isFinite(n) && n > 0) setQty(id, Math.min(n, 99999)); // 0/bo'sh — o'zgarishsiz qoldirib tiklaymiz
    }
    setBuf(null);
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 11, padding: 3 }}>
      <button onClick={() => delta(id, -1)} style={{ width: 38, height: 38, border: "none", background: "var(--surface)", cursor: "pointer", color: "var(--text3)", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Minus size={20} />
      </button>
      <input className="tabular" value={buf ?? String(qty)} inputMode="numeric"
        data-qty-for={id}
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => setBuf(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        style={{ width: 44, minWidth: 44, textAlign: "center", fontSize: 16, fontWeight: 700, border: "none", background: "transparent", color: "var(--text)", outline: "none", padding: 0, font: "inherit" }} />
      <button onClick={() => delta(id, 1)} style={{ width: 38, height: 38, border: "none", background: ASOFT, cursor: "pointer", color: AT, borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Plus size={20} />
      </button>
    </div>
  );
}

export function POSKassa() {
  const [products, setProducts] = useState<Product[]>([]);
  const [cats, setCats] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(false);
  const [showFailed, setShowFailed] = useState(false);   // rad etilgan cheklar ro'yxati
  // P9: rad etilgan cheklarni O'CHIRISH IKKI QADAMDA. Bu yozuvlar — PUL OLINGAN, lekin
  // serverda yozilmagan savdolar: yagona dalil. Ilgari bitta qizil tugma ro'yxatni
  // butunlay va SO'ROQSIZ o'chirardi (`clearFailed` -> localStorage.removeItem), ya'ni
  // yarashtirish uchun kerak bo'lgan ma'lumot qaytarib bo'lmas holda yo'qolardi.
  const [confirmClear, setConfirmClear] = useState(false);
  const [method, setMethod] = useState("cash");
  const [given, setGiven] = useState("");
  const [splitAmts, setSplitAmts] = useState<Record<string, string>>({}); // aralash to'lov summalari
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [custQuery, setCustQuery] = useState("");
  const [creditMode, setCreditMode] = useState<"existing" | "new">("existing");
  const [newFirst, setNewFirst] = useState("");
  const [newLast, setNewLast] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [paid, setPaid] = useState<Paid | null>(null);
  const [paidSummary, setPaidSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Tarozi mahsuloti panelдан bosilса — vazn (kg) so'raymiz (aks holда 1 dona = 1 kg bo'lib
  // ±1 stepper bilan noto'g'ri sotилаrди; tarozini/skanerни chetlab o'tardi).
  const [weigh, setWeigh] = useState<Product | null>(null);
  const [weighVal, setWeighVal] = useState("");
  const [prefs, setPrefs] = useState(readPrefs);
  // ── Phase 7 (kassa redizayni) — FAQAT KO'RINISH holati, biznes mantiqqa tegmaydi ──
  // Katalog endi doimiy grid EMAS: «Mahsulotlar» bosilganda vaqtinchalik oynada ochiladi.
  const [catalogOpen, setCatalogOpen] = useState(false);
  // Pastki panelning «Miqdor» va «Qatorni olib tashlash» tugmalari TANLANGAN qatorga ishlaydi.
  // Ilgari tanlov tushunchasi yo'q edi (har qatorning o'z ± va ✕ tugmasi bor, ular SAQLANADI).
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // O'ng paneldagi to'lov tugmasi bosilganda modal SHU usul bilan ochiladi. Ikkinchi to'lov
  // yo'li YARATILMAYDI — modal ochilish effekti shu qiymatni chip bosilgandek qo'llaydi.
  const presetRef = useRef<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  // QA CART-02: vazn (kg) dialogi ochiqligini window-keydown listener'ida ko'rish uchun (ref — listener
  // qayta obuna bo'lmaydi). Dialog ochiqda global F4/F6/F7/± yorliqlari bloklanadi.
  const weighRef = useRef(false);
  weighRef.current = !!weigh;
  // Katalog oynasi ochiqligini window-keydown listener'ida ko'rish uchun (weighRef naqshi).
  const catalogRef = useRef(false);
  catalogRef.current = catalogOpen;
  // To'lov oynasi ochiqligi — apparat-skaner tinglovchisi uchun (weighRef naqshi).
  const modalRef = useRef(false);
  modalRef.current = modal;

  // ── F-1: SKANER FOKUSI katalog ochilganda HAM, yopilganda HAM saqlanadi ──────
  // Skaner — oddiy klaviatura: barkod `pos-search` ga YOZILADI (`query` — buferning
  // o'zi) va Enter `onScan` ni ishga soladi. Ya'ni skan ishlashi FOKUSGA bog'liq.
  // Katalog ochilganda uchta narsa birlashib fokusni yo'qotardi: overlay inputni
  // qoplaydi, katalogni ochgan tugma fokusni o'ziga oladi, `onKey` esa katalog
  // ochiqda F2 ni ham to'sadi — natijada skaner zarbalari JIM yo'qolardi.
  //
  // Overlay inputni faqat KO'RINISHDA qoplaydi: element DOM'da qoladi va
  // fokuslanadi. Shu bois MAVJUD skaner yo'li (yagona `onScan`) o'zgarmaydi —
  // yangi tinglovchi ham, ikkinchi barkod parseri ham QO'SHILMAYDI, ya'ni bitta
  // skan ikki marta ishlanishi MUMKIN EMAS.
  //
  // ⚠️  Fokus O'G'IRLANMAYDI: vazn (kg) dialogi yoki to'lov oynasi ochiq bo'lsa
  //     tegmaymiz. Katalogdan VAZNLI mahsulot bosilganda katalog YOPILADI va vazn
  //     dialogi OCHILADI (uning inputi `autoFocus`) — `weighRef` render paytida
  //     yangilangani uchun effekt yangi qiymatni ko'radi.
  // ⚠️  MOUNT'da ATAYLAB ishlamaydi: ekran ochilishida fokus o'zgarmaydi (avvalgi
  //     xulq). Bu tuzatish FAQAT katalog holati o'zgarishiga javob beradi.
  const catalogFocusArmed = useRef(false);
  useEffect(() => {
    if (!catalogFocusArmed.current) { catalogFocusArmed.current = true; return; }
    if (weighRef.current || modal) return;
    searchRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalogOpen]);

  // ── XPAY QR avtomatik rejimi ──
  const [qrTxn, setQrTxn] = useState("");
  const [qrUrl, setQrUrl] = useState("");
  const [qrImgOk, setQrImgOk] = useState(true);
  const [qrStat, setQrStat] = useState<"idle" | "loading" | "waiting" | "done" | "error">("idle");
  const [qrErr, setQrErr] = useState("");
  const qrPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrDoneRef = useRef(false);
  const qrGenRef = useRef(false);
  const newCustIdRef = useRef<string>("");
  // QA OFF-5: yangi kredit-mijoz yaratish idempotentlik kaliti — response-lost/retry'да dublikat mijoz emas
  // (server ux_customers_client_uuid bo'yicha dedup). Checkout davomida BARQAROR; savdo yakunlangач yangilanadi.
  const custUuidRef = useRef<string>(crypto.randomUUID());
  // Savdo idempotentlik kaliti: BIR checkout uchun BARQAROR (to'lov oynasi ochilganda yangilanadi).
  // Tranzient xatoda (backend savdoni yozib javob yo'qolsa — Railway cold-start 502/504) oyna ochiq
  // qoladi va qayta bosishда AYNAN shu kalit ketadi -> backend dedup dublikat savdoni to'sadi.
  // Har finish()да yangi UUID yaratish (eski xato) tranzient xatodan keyin IKKI savdo yozardi.
  const saleUuidRef = useRef<string>(crypto.randomUUID());
  function resetQr() {
    if (qrPollRef.current) { clearInterval(qrPollRef.current); qrPollRef.current = null; }
    qrDoneRef.current = false; qrGenRef.current = false;
    setQrTxn(""); setQrUrl(""); setQrImgOk(true); setQrStat("idle"); setQrErr("");
  }

  const cart = useCart();
  const employee = useAuth((s) => s.employee);
  const openNav = useNav((s) => s.openNav);
  const updReady = useUpdate((s) => s.state === "ready");
  const online = useOnline();
  const pending = usePendingCount();
  const failed = useFailedCount();
  const t = useT();

  // ── Chek chop etish (Phase 5F) — sotuv holatidan MUSTAQIL yon ta'sir: printer xatosi `paid`/savatga
  //    tegmaydi, sotuvni qayta yubormaydi, "Yangi savdo"ni to'smaydi (hech narsa kutilmaydi). ──
  const printTarget = useMemo(() => (paid ? printTargetOf(paid) : null), [paid]);
  const pr = usePrintDoc(printTarget);
  // Avto-chop etish (shablon `auto_print`): har sotuvga BIR MARTA (StrictMode ham) — PrintStatus.tsx.
  useAutoPrint(pr, printTarget);

  function loadFromCache() {
    setProducts(cacheGet<Product[]>(CACHE.products, []));
    setCats(cacheGet<Category[]>(CACHE.cats, []));
  }
  async function load() {
    loadFromCache();                 // darhol (offline ham ishlaydi)
    const ok = await refreshCatalog();
    if (ok) { loadFromCache(); setPrefs(readPrefs()); } // onlayn bo'lsa yangilangan keshni o'qiymiz
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // QA CART-02: vazn (kg) dialogi ochiq — global savat/yakunlash yorliqlari (F4/F6/F7/±) ISHLAMASIN.
      // Aks holda F7 bosib vaznni tasdiqlaganda mahsulot BOSHQA savatga tushardi, F4 esa sotuvni tarozi
      // mahsulotisiz yakunlardi. Dialogning o'z Enter/Escape'i (input onKeyDown) alohida ishlayveradi.
      if (weighRef.current) return;
      // Katalog (vaqtinchalik oyna) ochiq — Escape uni yopadi va boshqa yorliqlar ISHLAMAYDI.
      // ⚠️  Kassir katalogni ochib qo'yib skanerlashga qaytishi odatiy: Escape'siz u sichqoncha
      //     bilan ✕ ni qidirishga majbur bo'lardi (skaner-birinchi oqim buziladi).
      if (catalogRef.current) {
        if (e.key === "Escape") { e.preventDefault(); setCatalogOpen(false); }
        return;
      }
      // Escape har doim ishlaydi — to'lov modalini yopadi (busy paytida emas)
      if (e.key === "Escape") { if (!busyRef.current) setModal(false); return; }
      // To'lov modali ochiq — savat/yakunlash shortcut'lari (F2/F4/F6/F7/+/−) modal ORTIDA
      // ishlamasin (aks holda modal ochiqligi bilan savat/miqdorlar o'zgarib ketardi).
      if (modal) return;
      const inField = document.activeElement?.tagName === "INPUT";
      if (e.key === "F2") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "F4") { e.preventDefault(); if (cart.items.length) setModal(true); }
      else if (e.key === "F6") { e.preventDefault(); useCart.getState().newCart(); }   // yangi mijoz savati
      else if (e.key === "F7") { e.preventDefault(); const c = useCart.getState(); c.switchCart((c.active + 1) % c.carts.length); } // keyingi savat
      else if ((e.key === "+" || e.key === "=") && !inField) { e.preventDefault(); bumpLast(1); }
      else if ((e.key === "-" || e.key === "_") && !inField) { e.preventDefault(); bumpLast(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line
  }, [cart.items.length, modal]);

  // ── APPARAT SKANER: FOKUSDAN MUSTAQIL YO'L ───────────────────────────────
  //  ROOT CAUSE (haqiqiy apparat bilan tasdiqlangan). Bu ekranda skanerning
  //  YAGONA yo'li `pos-search` inputi edi: barkod buferi — uning `query`
  //  state'i, terminator — uning `onKeyDown` i. Ya'ni skan FAQAT o'sha input
  //  fokusda bo'lganda ishlardi. Ekran ochilganda esa hech narsa fokusda
  //  EMAS (`autoFocus` yo'q, F-1 effekti esa mount'da ATAYLAB o'tkazib
  //  yuboradi) — zarbalar `<body>` ga ketib JIM yo'qolardi. F2 bosilgach
  //  ishlagani shuni tasdiqlaydi: F2 shunchaki `searchRef.focus()` qiladi.
  //
  //  Yechim — skanerni fokusdan AJRATISH, F2 ga doimiy fokus bermasdan:
  //  tahrirlanadigan element fokusda bo'lsa zarbalar O'SHANIKI (odam yozmoqda,
  //  F2 qo'lda qidiruv ham shunda ishlayveradi); fokusda hech narsa bo'lmasa —
  //  bu skaner va barkod shu yerda yig'iladi. Ikki yo'l O'ZARO INKOR, shu bois
  //  bitta skan IKKI MARTA ishlanmaydi (`addByScan` ham yagona).
  useEffect(() => {
    const wedge = createWedge();
    const onWedgeKey = (e: KeyboardEvent) => {
      //  Yorliq birikmasi (Ctrl/Alt/Cmd) — skaner EMAS.
      if (e.ctrlKey || e.altKey || e.metaKey) { wedge.reset(); return; }
      //  Vazn (kg) dialogi yoki to'lov oynasi ochiq — savat skan bilan
      //  QIMIRLAMAYDI (mavjud yorliq gardlari bilan AYNI qoida).
      if (weighRef.current || modalRef.current) { wedge.reset(); return; }
      //  Odam tahrirlanadigan maydonda yozmoqda (F2 qidiruvi, to'lov summasi,
      //  mijoz ismi…) — bu yo'l CHETDA turadi.
      if (isEditableTarget(document.activeElement)) { wedge.reset(); return; }
      const code = wedge.push(e.key);
      if (code === null) return;
      //  Skan DA'VO QILINDI. `preventDefault` SHART: fokus tugmada bo'lsa
      //  (masalan kassir «Mahsulotlar» ni bosgan) skanerning `Enter` i o'sha
      //  tugmani BOSARDI. Bufer qisqa bo'lsa da'vo QILINMAYDI va `Enter`
      //  o'z standart ishini bajaradi — klaviatura bilan boshqarish buzilmaydi.
      e.preventDefault();
      e.stopPropagation();
      scanRef.current(code);
    };
    //  ── BURST CHEGARALARI (vaqt o'lchamasdan) ─────────────────────────────
    //  Odam o'rtaga tushsa (bosish, fokus almashishi, oynani almashtirish)
    //  yarim bufer keyingi skanga PREFIKS bo'lib qo'shilmasligi kerak. Bu
    //  chegaralar HODISA bo'yicha aniqlanadi — inter-key millisekund chegarasi
    //  ATAYLAB kiritilmaydi (skaner tezligiga bog'liq bo'lib qolardi).
    const drop = () => wedge.reset();
    //  CAPTURE fazasi: tugmaning standart «bosilishi»dan va boshqa
    //  tinglovchilardan OLDIN qaror qilinadi.
    window.addEventListener("keydown", onWedgeKey, true);
    window.addEventListener("pointerdown", drop, true);
    window.addEventListener("focusin", drop, true);
    document.addEventListener("visibilitychange", drop);
    return () => {
      window.removeEventListener("keydown", onWedgeKey, true);
      window.removeEventListener("pointerdown", drop, true);
      window.removeEventListener("focusin", drop, true);
      document.removeEventListener("visibilitychange", drop);
    };
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (modal && prefs.qarz && customers.length === 0) {
      get<CustomerRow[]>("/customers").then(setCustomers).catch(() => {});
    }
  }, [modal, prefs.qarz, customers.length]);

  // Modal ochilganda to'lov holatini tozalab boshlaymiz (eski qatorlar/mijoz/chek qolmasin).
  // setPaid(null) — F4 (klaviatura) bilan ochilganda ham oldingi chek ekrani chiqib qolmasin.
  useEffect(() => {
    if (modal) {
      setPaid(null);
      setSplitAmts({}); setCustomerId(""); setCustQuery(""); setCreditMode("existing");
      setNewFirst(""); setNewLast(""); setNewPhone(""); newCustIdRef.current = ""; setErr("");
      // QA OFF5-review: yangi-mijoz idempotentlik kaliti newCustIdRef bilan BIRGA yangilanadi (modal ochilganда
      // = yangi checkout/yangi mijoz). Aks holda oldingi savdoда yaratilgan mijozning kaliti qolib, keyingi
      // BOSHQA yangi mijoz server dedup'ida o'sha oldingi mijozga bog'lanib ketardi (misattribution).
      // Response-lost retry modalни QAYTA OCHMAYDI (xato o'sha oynada ko'rsatiladi) — shu bois barqarorlik buzilmaydi.
      custUuidRef.current = crypto.randomUUID();
      // O'ng panelda AYNIQ usul bosilgan bo'lsa — uni chip bosilgandek qo'yamiz (yuqoridagi
      // `setSplitAmts({})` dan KEYIN). Aralash/«Boshqa» uchun preset yo'q: kassir o'zi tanlaydi.
      if (presetRef.current) {
        const code = presetRef.current;
        presetRef.current = null;
        setSplitAmts({ [code]: String(Math.max(Math.round(cart.subtotal() + 1e-6), 0)) });
      }
      // QA PAY-10: idempotentlik kaliti bu yerda YANGILANMAYDI — u faol-savat checkout'i uchun
      // BARQAROR (finish() da savdo yakunlangach yangilanadi). Ilgari modal HAR ochilganda yangi
      // kalit yaratilardi: osilgan so'rovda kassir modalni yopib-ochib qayta yuborsa TURLI uuid
      // ketib, dublikat savdo yozilishi mumkin edi. Endi qayta ochish o'sha kalitni saqlaydi.
    }
    // eslint-disable-next-line
  }, [modal]);

  function bumpLast(d: number) {
    const items = useCart.getState().items;
    const last = items[items.length - 1];
    // Tarozi mahsuloti (kasr kg) ±1 bilan buziladi — klaviatura +/− ni ham qo'llamaymiz
    if (last && !last.weighted) cart.delta(last.id, d);
  }

  const [usageTick, setUsageTick] = useState(0);
  // QA CART-06: qidiruv debounce — har harfda ~8000 mahsulotni filter/sort/slice qilish UI'ni sekinlatardi.
  // useDeferredValue grid filtrini kechiktiradi (yozish darhol, ro'yxat bir kadr keyin) — skaner/Enter (onScan)
  // esa doim jonli `query`ni o'qiydi, shu bois barcode/tarozi-etiketka oqimi sekinlashmaydi.
  const deferredQuery = useDeferredValue(query);
  const shown = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase();
    const usage = readUsage();
    return products
      .filter(
        (p) =>
          (activeCat === "all" || p.category_id === activeCat) &&
          (!q || p.name.toLowerCase().includes(q) || p.article_code.toLowerCase().includes(q))
      )
      // Tartib: (1) kassir qidirib sotganlari, (2) eng ko'p sotilganlar, (3) nom bo'yicha
      .sort((a, b) =>
        (usage[b.id] || 0) - (usage[a.id] || 0) ||
        (b.sold_qty || 0) - (a.sold_qty || 0) ||
        a.name.localeCompare(b.name)
      )
      .slice(0, 120);   // katta katalogda (8000+) UI qotmasin — qolgani qidiruv/skaner bilan topiladi
    // eslint-disable-next-line
  }, [products, activeCat, deferredQuery, usageTick]);

  const subtotal = cart.subtotal();
  // QA CART-05: arxivlangan (is_active=false) mahsulotlar savat qatorida ham "Arxiv" belgisi bilan
  // ko'rsatiladi (grid'dagidek). Katalogda topilmasa (o'chirilgan) belgisiz qoladi.
  const archivedIds = useMemo(() => new Set(products.filter((p) => p.is_active === false).map((p) => p.id)), [products]);

  // ── Birlashgan to'lov: usullar (yoqilganlari). Har biri bosilsa qator qo'shiladi.
  //    Bitta usul = oddiy to'lov (naqddan qaytim ham), 2+ usul = aralash. ──
  const payMethods = [
    { code: "cash", label: t("pay.cash"), Icon: Money },
    ...(prefs.karta ? [{ code: "card", label: t("pay.card"), Icon: CreditCard }] : []),
    ...(prefs.qr ? [{ code: "qr", label: t("pos.qrPay"), Icon: QrCode }] : []),
    ...(prefs.qarz ? [{ code: "credit", label: t("pay.credit"), Icon: Notebook }] : []),
  ];
  const curUnit = fmt(0).replace(/[0-9\s.,]/g, ""); // valyuta birligi (сом / so'm)
  // O'ng paneldagi to'lov tugmalari uchun TO'LIQ yorliqlar (oynadagi qisqa chiplardan farqli).
  const PAY_BIG: Record<string, string> = {
    cash: t("pk.mCash"), card: t("pk.mCard"), qr: t("pk.mQr"), credit: t("pk.mCredit"),
  };
  // Naqd som'da kasr yo'q — to'lov butun som'da (tarozi mahsuloti kasr summa berishi mumkin).
  // Backend ham total'ni butun som'ga yaxlitlaydi (Decimal ROUND_HALF_UP); fmt() ayni shu qiymatni
  // ko'rsatadi. MUHIM: subtotal — IEEE-754 float yig'indisi; tarozi qatorining ANIQ .5 qiymati
  // float'da .4999… ga tushadi va Math.round pastga yaxlitlab serverdan 1 som farq qilardi
  // (chek≠kassa, split to'lov RAD etilardi). Kichik epsilon (1e-6) shu underflow'ni tuzatadi —
  // haqiqiy .5-dan past qiymatlar (≤5 kasr) unga yaqin bo'lmaydi, shu bois xavfsiz.
  const payTotal = Math.round(subtotal + 1e-6);
  const payAmt = (c: string) => parseInt((splitAmts[c] || "").replace(/\D/g, ""), 10) || 0;
  const activeCodes = payMethods.map((m) => m.code).filter((c) => c in splitAmts);
  const paidSum = activeCodes.reduce((s, c) => s + payAmt(c), 0);
  const cashOnly = activeCodes.length === 1 && activeCodes[0] === "cash";
  const payRemaining = payTotal - paidSum;                     // >0 qoldi, <0 ortiqcha
  const payChange = cashOnly ? Math.max(0, -payRemaining) : 0; // faqat naqd bo'lsa — qaytim
  const hasCredit = activeCodes.includes("credit");
  const creditReady = !hasCredit || (creditMode === "existing" ? !!customerId : `${newFirst} ${newLast}`.trim().length > 0);
  const payOk = payTotal > 0 && activeCodes.length > 0 && (cashOnly ? paidSum >= payTotal : payRemaining === 0) && creditReady;
  // XPAY avto-QR: QR YAGONA usul sifatida tanlanganda ishlaydi (chip-UI'da eski `method`
  // state hech qachon "qr" bo'lmay qolgan edi — oqim butunlay o'lik edi).
  const qrOnly = activeCodes.length === 1 && activeCodes[0] === "qr";
  const xpayQr = qrOnly && prefs.qrMode === "xpay";
  const xpayWait = xpayQr && qrStat !== "done"; // to'lov tasdiqlanmaguncha Yakunlash yopiq
  const activeKey = activeCodes.join(",");

  // Usul tanlovi o'zgarsa yoki modal yopilsa — QR holatini tozalaymiz (yangi summa/rejim uchun)
  useEffect(() => { resetQr(); /* eslint-disable-next-line */ }, [activeKey, modal]);

  // XPAY QR: modal ochilib QR tanlanganda BIR MARTA yaratamiz (qrStat dep emas -> o'zini bekor qilmaydi)
  useEffect(() => {
    const active = modal && xpayQr && !paid;
    if (!active || qrGenRef.current) return;
    qrGenRef.current = true;
    setQrStat("loading"); setQrErr(""); qrDoneRef.current = false;
    post<{ txn_id: string; qr_url: string }>("/payments/qr", { amount: payTotal, comment: prefs.storeName, client_uuid: saleUuidRef.current })
      .then((r) => { setQrTxn(r.txn_id); setQrUrl(r.qr_url); setQrImgOk(true); setQrStat("waiting"); })
      .catch((e: any) => {
        const msg = String(e?.message || "");
        setQrStat("error");
        setQrErr(msg.includes("XPAY sozlanmagan") ? t("pos.errXpayDisabled") : (msg || t("pos.qrGenFail")));
      });
    // eslint-disable-next-line
  }, [modal, xpayQr, paid]);

  // Alohida polling effekt — QR "waiting" bo'lgach holatni so'raymiz
  useEffect(() => {
    const active = modal && xpayQr && !paid;
    if (!active || qrStat !== "waiting" || !qrTxn) {
      if (qrPollRef.current) { clearInterval(qrPollRef.current); qrPollRef.current = null; }
      return;
    }
    const tick = async () => {
      try {
        const st = await get<{ status: string }>(`/payments/qr/${qrTxn}`);
        if (st.status === "COMPLETED" && !qrDoneRef.current) {
          qrDoneRef.current = true;
          if (qrPollRef.current) { clearInterval(qrPollRef.current); qrPollRef.current = null; }
          setQrStat("done");
          finish();
        } else if (["CANCELED", "ERROR", "EXPIRED", "FAILED"].includes(st.status)) {
          if (qrPollRef.current) { clearInterval(qrPollRef.current); qrPollRef.current = null; }
          setQrStat("error"); setQrErr(t("pos.errQrCanceled"));
        }
      } catch { /* keyingi urinishda qayta so‘raymiz */ }
    };
    qrPollRef.current = setInterval(tick, 2500);
    return () => { if (qrPollRef.current) { clearInterval(qrPollRef.current); qrPollRef.current = null; } };
    // eslint-disable-next-line
  }, [modal, xpayQr, qrStat, qrTxn, paid]);

  const shownCustomers = customers.filter((c) => {
    const q = custQuery.trim().toLowerCase();
    return !q || c.full_name.toLowerCase().includes(q) || (c.phone || "").includes(q) || c.code.toLowerCase().includes(q);
  });
  const previewId = "M-" + (1001 + customers.length);

  // ── YAGONA SKAN RESOLVERI ────────────────────────────────────────────────
  //  Ikki yo'l ham (F2 inputining `onScan` i va apparat-skaner tinglovchisi)
  //  AYNAN shuni chaqiradi: ikkinchi barkod parseri ham, ikkinchi `cart.add`
  //  chaqiruvi ham YARATILMAYDI. Ikki yo'l FOKUS bo'yicha O'ZARO INKOR
  //  (`isEditableTarget`), shu bois bitta skan ikki marta ishlanishi MUMKIN EMAS.
  //
  //  `allowNameFallback` — `shown[0]` zaxirasi, FAQAT odamning QO'LDA qidiruvi
  //  uchun (nom/artikul yozib Enter — mavjud va ataylab saqlanadigan UX).
  //  Apparat skaner yo'lida DOIM `false`: tanilmagan barkod savatni MUTLAQO
  //  qimirlatmasin, taxmin bilan «eng yaqin» mahsulot sotilmasin.
  function addByScan(term: string, allowNameFallback: boolean): void {
    // Tarozi etiketkasi: 27 + PLU(5) + gramm(5) + EAN-13 nazorat(1) — YAGONA qoida
    // `lib/scaleBarcode.ts` da (server `GET /products/scan` ham AYNAN shu vektorlar bilan tekshiriladi).
    const scale = parseScaleBarcode(term);
    if (scale) {
      const wp = products.find((p) => p.is_weighted && pluMatches(p.plu_code, scale.plu));
      if (wp) {
        // Haqiqiy mahsulot id + vazn (kg) qty sifatida — savdo/ombor to'g'ri yoziladi (narx = 1 kg narxi)
        cart.add({ id: wp.id, name: wp.name, price: wp.base_sell_price, article: wp.article_code, qty: scale.grams / 1000, weighted: true });
        bumpUsage(wp.id); setUsageTick((v) => v + 1);
        setQuery("");
        return;
      }
      // ⚠️  Etiketka TANILDI, lekin shu PLU'li vaznli mahsulot yo'q. Pastdagi oddiy qidiruvga
      //     TUSHIRMAYMIZ: u yerda `shown[0]` zaxirasi bor va kassir bexabar BOSHQA mahsulotni
      //     1 dona qilib sotib yuborardi (`deferredQuery` kechikkanda `shown` butun katalog bo'ladi).
      //     Tarozi etiketkasi — aniq hujjat: mos kelmasa ochiq xato beriladi.
      setErr(t("pos.scaleNoProduct", { plu: scale.plu }));
      setQuery("");
      return;
    }
    const exact = products.find((p) => (p.barcodes || []).includes(term));
    const hit = exact || (allowNameFallback ? shown[0] : undefined);
    if (!hit) {
      //  ⚠️  FAIL-LOUD. Skaner yo'lida tanilmagan barkod ILGARI JIMGINA
      //      yo'qolardi (`if (hit)` — `else` yo'q edi): kassir skanerni ikki-uch
      //      marta bosib, nima bo'lmaganini tushunmasdi. Savat QIMIRLAMAYDI,
      //      lekin sabab KO'RINADI.
      if (!allowNameFallback) setErr(t("pos.notFound"));
      return;
    }
    // QA PC-014: tarozi mahsuloti skaner/Enter yo'lida ham VAZN so'raydi (grid bilan bir xil) —
    // aks holda 1 dona = 1 kg bo'lib, ±1 stepper bilan noto'g'ri sotilardi.
    if (hit.is_weighted) { setWeigh(hit); setWeighVal(""); setQuery(""); return; }
    cart.add({ id: hit.id, name: hit.name, price: hit.base_sell_price, article: hit.article_code });
    bumpUsage(hit.id); setUsageTick((v) => v + 1);
    setQuery("");
  }

  function onScan(e: React.KeyboardEvent) {
    if (e.key !== "Enter") return;
    const term = query.trim();
    if (!term) return;
    //  ⚠️  `shown` KECHIKTIRILGAN `deferredQuery` dan hisoblanadi, `term` esa
    //      JONLI `query`. Skan tez bo'lganda `shown` hali OLDINGI (bo'sh) so'rov
    //      natijasi — ya'ni BUTUN katalog — va `shown[0]` zaxirasi kassir bexabar
    //      BOSHQA mahsulotni sotib yuborardi (aynan shu xavf tarozi yo'lida
    //      izohlangan, lekin oddiy barkod yo'lida OCHIQ qolgan edi). Zaxira endi
    //      FAQAT kechiktirilgan qiymat jonlisiga YETIB OLGANDA ishlaydi — odam
    //      yozib Enter bosganda doim shunday, tez skanda esa HECH QACHON.
    addByScan(term, deferredQuery.trim() === term);
  }

  //  Tinglovchi `[]` deps bilan bir marta obuna bo'ladi, `addByScan` esa har
  //  renderda yangi katalog/savatni ko'radi — shu bois chaqiruv REF orqali.
  const scanRef = useRef<(term: string) => void>(() => {});
  scanRef.current = (term: string) => addByScan(term, false);

  async function finish() {
    setBusy(true);
    setErr("");
    try {
      const active = payMethods.map((m) => m.code).filter((c) => c in splitAmts && payAmt(c) > 0);
      if (active.length === 0) throw new Error(t("pos.splitPick"));
      const single = active.length === 1;    // bitta usul → oddiy to'lov (naqd qaytimi/nasiya backendda)
      const soleCode = active[0];
      const isCredit = active.includes("credit");
      let custId = customerId;
      let custName = "";
      if (isCredit) {
        if (creditMode === "new") {
          if (!online) throw new Error(t("pos.errNoInternet"));
          const name = `${newFirst} ${newLast}`.trim();
          if (!name) throw new Error(t("pos.errNewName"));
          if (newCustIdRef.current) {
            custId = newCustIdRef.current;
            custName = name;
          } else {
            const c = await post<CustomerRow>("/customers", { full_name: name, phone: newPhone || null, client_uuid: custUuidRef.current });
            custId = c.id; newCustIdRef.current = c.id;
            custName = c.full_name;
            setCustomers((a) => [...a, c]);
          }
        } else {
          if (!custId) throw new Error(t("pos.errPickCustomer"));
          custName = customers.find((c) => c.id === custId)?.full_name || t("pos.customer");
        }
      }
      const splitPayments = single ? undefined : active.map((c) => ({ method: c, amount: payAmt(c) }));
      // Offline ruxsat: har bir faol usul internetsiz ishlay olsagina savdo navbatga tushadi.
      //  naqd/qarz — doim; karta — offlineCard; QR — faqat qo'lda rejim + offlineQr (XPAY offline emas).
      // QA PAY-01: XPAY QR ALLAQACHON tasdiqlangan (qrDoneRef) bo'lsa — pul olingan; savdo submit
      // transient xatoда yo'qolmasin, navbatga tushsin. Flush /sync/push qr_txn_id bilan qayta uradi,
      // server COMPLETED (hali consume qilinmagan) QR'ni tekshirib savdoni yozadi (pul-olindi-savdo-yo'q yopiladi).
      const methodOffline = (c: string): boolean =>
        c === "cash" || c === "credit" ? true
        : c === "card" ? prefs.offlineCard
        : c === "qr" ? ((prefs.qrMode === "manual" && prefs.offlineQr) || qrDoneRef.current)
        : false;
      const methodsOffline = active.every(methodOffline);
      // P9 XAVFSIZLIK DARVOZASI: `force_shift` yoqilgan do'konda ochiq smenasiz OFFLINE
      // yakunlash TAQIQLANADI — pul olinib, mijoz ketib, keyin `/sync/push` chekni 400
      // bilan rad etishi (serverda savdo/naqd/stok YO'Q) shu yerda to'siladi. Qaror
      // SERVERDAN keladi (`GET /shifts/offline-sale-policy`, `lib/sync.ts`); tasdiq yo'q/
      // eskirgan/boshqa kassirniki bo'lsa — FAIL-CLOSED (false).
      //
      // ⚠️  ONLAYN savdo TEGILMAYDI: bu bayroq faqat tarmoq uzilganda navbatga qo'yishni
      //     boshqaradi. Smenasiz savdo `force_shift` O'CHIQ do'konda AVVALGIDEK ishlaydi
      //     (server ALLOWED beradi), «To'lovni yakunlash» tugmasi ham ochiq qoladi.
      // ⚠️  PUL ALLAQACHON KO'CHGAN holat. XPAY QR tasdiqlangan (`qrDoneRef`) yoki tashqi
      //     karta terminali «internetsiz» rejimda ishlatilgan bo'lsa — mijozning puli
      //     `finish()` GACHA yechilgan. Bunday chekni darvoza bilan TO'SISH savdoni
      //     navbatga ham, dead-letter'ga ham yozmasdan YO'Q QILARDI: pul ketgan, izi
      //     qolmagan — bu HEAD'dagi holatdan ham YOMON. Shu bois pul ko'chgan bo'lsa
      //     chek AVVALGIDEK navbatga tushadi (server rad etsa dead-letter'da dalil qoladi).
      const moneyCaptured = active.some(
        (c) => (c === "qr" && qrDoneRef.current) || (c === "card" && prefs.offlineCard));
      const offlineOk = offlineSaleAllowed() || moneyCaptured;
      const allowOffline = methodsOffline && offlineOk;
      const payload = {
        // QA PC-001: unit_price = savat SNAPSHOT'i. Onlayn savdoda server e'tiborga olmaydi
        // (o'z narxidan hisoblaydi, expected_total mos kelmasa 409); offline navbatdan
        // flush'da esa server AYNAN shu narxda yozadi — kassa naqdiga mos.
        items: cart.items.map((i) => ({ product_id: i.id, qty: i.qty, unit_price: i.price })),
        payment_method: single ? soleCode : "cash",
        payments: splitPayments,
        // Aniq to'lovda given=null → backend total'ni ishlatadi (yaxlitlash chekkasiga chidamli);
        // faqat ortiqcha berilsa (qaytim uchun) aniq summani yuboramiz.
        given_amount: single && soleCode === "cash" && payAmt("cash") > payTotal ? payAmt("cash") : null,
        customer_id: isCredit ? custId : undefined,
        client_uuid: saleUuidRef.current,
        // §5/§6 AYNAN KASSA: ochiq smenaning saqlangan identity'si. Server AVTORITET bo'lib
        // qoladi (yakuniy Sale.till_id smenadan olinadi) — bu qiymat MOSLIKNI tekshirish uchun:
        // zid bo'lsa server 409 qaytaradi (jimgina tuzatish YO'Q). Offline navbatda ham
        // saqlanadi, shu bois replay paytida drawer QAYTA TIKLANMAYDI.
        till_id: currentTillId(),
        expected_total: payTotal,   // QA PC-001: POS ko'rsatgan jami — server farq ko'rsa 409
        qr_txn_id: qrTxn || undefined,   // QA PAY-01: XPAY QR bo'lsa server tasdiqlaydi/consume qiladi (offline flush'da ham)
      };
      const r = await submitSale(payload, {
        allowOffline,
        // Sabab ANIQ aytiladi: to'lov usuli internetni talab qiladimi, kassa soati
        // xatomi, yoki ochiq smena yo'qmi. Server bergan barqaror kodga qarab tanlanadi.
        // Sabab uch xil bo'ladi va uchovi BOSHQA-BOSHQA harakat talab qiladi:
        //   · usul internetni talab qiladi          -> internetni kuting
        //   · server BLOCKED dedi, sababi soat      -> kompyuter sanasini to'g'rilang
        //   · server BLOCKED dedi (smena/kassa)     -> smenani oching
        //   · sabab YO'Q (tasdiq umuman olinmagan / eskirgan / begona) -> smena ochish
        //     YORDAM BERMAYDI; serverga ulanish kerak. Alohida xabar beriladi.
        offlineErr: !methodsOffline
          ? t("pos.errNeedNet")
          : offlineSaleReason() === "DEVICE_CLOCK_UNRELIABLE"
            ? t("pos.errOfflineClock")
            : offlineSaleReason() === null
              ? t("pos.errOfflineNoPolicy")
              : t("pos.errOfflineShift"),
      });
      const payLbl = (code: string) => code === "cash" ? t("pay.cash") : code === "card" ? t("pay.card") : code === "qr" ? t("pos.qrPay") : t("pay.credit");
      setPaidSummary(
        !single
          ? `${fmt(payTotal)} · ${active.map((c) => `${payLbl(c)} ${fmt(payAmt(c))}`).join(" + ")}`
          : soleCode === "credit" ? `${fmt(payTotal)} · ${payLbl("credit")} · ${custName}` : `${fmt(payTotal)} · ${payLbl(soleCode)}`
      );
      // Chek surati — oddiy ma'lumot nusxasi (chek kodi bu yerda ISHLAMAYDI, faqat chop etishda). Onlayn
      // sotuvda ham olinadi: eski server (chek marshruti yo'q) bo'lsa chek shu suratdan chiqadi.
      const unitOf = new Map(products.map((p) => [p.id, p.unit_code ?? null]));
      setPaid({
        receipt_no: r.offline ? "OFFLINE" : r.receipt_no || "—",
        offline: r.offline,
        uid: r.uid,
        id: r.offline ? null : r.id ?? null,
        client_uuid: payload.client_uuid,
        snap: {
          payload,
          lines: cart.items.map((i) => ({ name: i.name, weighted: !!i.weighted, unit: unitOf.get(i.id) ?? null })),
          cashier: employee?.full_name || null,
          storeName: prefs.storeName,
          branchName: employee?.branch_name || prefs.branchName || null,  // QA SB-014: xodimning haqiqiy filiali
          sold_at: r.sold_at || new Date().toISOString(),
          currency: companyCurrency() ?? null,   // VALYUTA SURATI (sotuv paytida)
        },
      });
      cart.finishActive(); // faol savat yopiladi (boshqa mijozlarniki qoladi) — qayta sotib bo'lmaydi
      // QA PAY-10: kalit "ishlatildi" — keyingi checkout (istalgan savat) YANGI kalit oladi. Aks holda
      // "Yangi savdo" bosilmay keyingi mijoz savdosi shu kalit bilan serverда dedup'ga tushardi.
      saleUuidRef.current = crypto.randomUUID();
      custUuidRef.current = crypto.randomUUID();   // QA OFF-5: keyingi kredit-mijoz uchun yangi idempotentlik kaliti
    } catch (e: any) {
      // QA PC-001: 409 = "narx yangilandi" — katalogni yangilab savatni yangi narxga moslaymiz,
      // kassir yangi jami bilan qayta uradi (mijoz X to'lab bazaga Y yozilishi yopildi).
      if (e?.status === 409) {
        try {
          const ok = await refreshCatalog();
          if (ok) {
            loadFromCache();
            const fresh = cacheGet<Product[]>(CACHE.products, []);
            useCart.getState().reprice(Object.fromEntries(fresh.map((p) => [p.id, p.base_sell_price])));
          }
        } catch { /* katalog yangilanmasa ham xato ko'rsatiladi */ }
      }
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  function newSale() {
    // Eslatma: savat to'lov o'tganda finishActive() bilan yopilgan — bu yerda clear()
    // chaqirilsa KEYINGI mijozning savati o'chib ketardi.
    setModal(false);
    setPaid(null);
    setGiven("");
    setSplitAmts({});
    setCustomerId("");
    setCustQuery("");
    setCreditMode("existing");
    setNewFirst(""); setNewLast(""); setNewPhone("");
    setMethod("cash");
    resetQr();
    newCustIdRef.current = "";
    load();
  }

  // ── Phase 7: sarlavha uchun HAQIQIY seans ma'lumoti (taxmin YO'Q) ──
  const shiftCur = useShift((s) => s.current);
  const shiftOpen = !!shiftCur;
  // ⚠️  `pos.cashier` = KASSIR (odam), kassa EMAS — shu bois alohida `pk.tillN` kaliti.
  //     Smena yopiq bo'lsa kassa raqami NOMA'LUM: taxmin qilmaymiz, do'kon/filial nomini beramiz.
  const tillLabel = shiftCur?.till_code
    ? t("pk.tillN", { n: shiftCur.till_code })
    : (prefs.branchName || prefs.storeName || t("pk.screen"));
  // Soat: har 30 soniyada yangilanadi (sekundsiz ko'rsatiladi — keraksiz qayta chizish yo'q).
  const [clock, setClock] = useState(() => new Date().toLocaleString());
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleString()), 30_000);
    return () => clearInterval(id);
  }, []);
  // Pastki paneldagi ikki amal TANLANGAN qatorga ishlaydi. Qator savatdan chiqib ketsa
  // (to'lov, tozalash, ✕) tanlov O'Z-O'ZIDAN bekor bo'ladi — `find` undefined qaytaradi.
  const selected = cart.items.find((i) => i.id === selectedId) || null;

  const cartMap: Record<string, number> = {};
  cart.items.forEach((i) => (cartMap[i.id] = i.qty));

  const payDisabled = cart.items.length === 0;

  // Dizayn: to'lov usullari sozlamadan (savdoos_payments) — o'chirilganlari ko'rinmaydi
  //
  // ═══ PHASE 7 — TASDIQLANGAN KASSA MAKETI ═════════════════════════════════════
  //  Chap ~65%: qidiruv + «Mahsulotlar» + KATTA savat jadvali (ekranning asosiy elementi)
  //  O'ng ~35%: mijoz · jami · to'lov usullari · yashil to'lov tugmasi
  //  Past: AYNAN TO'RT amal (Miqdor, Qatorni olib tashlash, Chekni kutishda saqlash, Savdoni tozalash)
  //
  // ⚠️  KATALOG DOIMIY EMAS: mahsulot kartalari faqat «Mahsulotlar» bosilganda vaqtinchalik
  //     oynada ko'rinadi — skaner-birinchi ish oqimi uchun savat ekranni egallaydi.
  // ⚠️  YORLIQLAR MAKETDAN OLINMAYDI: faqat HAQIQIY, testlar bilan qotirilgan yorliqlar
  //     ko'rsatiladi (qidiruv F2, to'lov F4). Maketdagi F3/F5–F11/Enter yozuvlari — vizual
  //     namuna; ular koddagi F6/F7 (savat almashtirish) bilan TO'QNASHADI, shu bois yozilmaydi.
  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* ═══ HEADER ═══ */}
      <header style={{ display: "flex", alignItems: "center", gap: 14, padding: "0 20px", height: 58, flex: "none", background: "var(--card)", borderBottom: "1px solid var(--border)" }}>
        <button onClick={openNav} title={t("pos.menu")} data-testid="pos-menu"
          style={{ width: 36, height: 36, flex: "none", border: "1px solid var(--border)", background: "var(--card)", borderRadius: 9, cursor: "pointer", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
          <List size={18} />
          {updReady && <span style={{ position: "absolute", top: 5, right: 5, width: 8, height: 8, borderRadius: "50%", background: B, border: "2px solid var(--card)" }} />}
        </button>
        <div style={{ display: "flex", alignItems: "baseline", gap: 9, flex: "none" }}>
          <span style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.03em", color: B }}>BinOS</span>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text2)" }}>{t("pk.screen")}</span>
        </div>
        {/* DO'KON nomi — eski sarlavhada bor edi va u YO'QOLMASLIGI kerak: kassir qaysi
            do'konda ishlayotganini ko'rsatadi (ko'p filialli tarmoqda muhim). */}
        {prefs.storeName && (
          <span style={{ flex: "none", fontSize: 13, fontWeight: 600, color: "var(--text3)", whiteSpace: "nowrap", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
            {prefs.storeName}
          </span>
        )}

        {/* Seans ma'lumoti — HAQIQIY holat (taxmin yo'q) */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, fontSize: 12.5, color: "var(--text3)", flexWrap: "wrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: shiftOpen ? "var(--ok)" : "var(--faint)" }} />
            {tillLabel}
          </span>
          <span style={{ color: "var(--faint)" }}>·</span>
          <span style={{ whiteSpace: "nowrap", color: shiftOpen ? "var(--ok)" : "var(--muted)", fontWeight: 600 }}>
            {shiftOpen ? t("pk.shiftOpen") : t("pk.shiftClosed")}
          </span>
          {employee?.full_name && (<>
            <span style={{ color: "var(--faint)" }}>·</span>
            <span style={{ whiteSpace: "nowrap" }}>{t("pk.cashierIs")}: {employee.full_name}</span>
          </>)}
        </div>

        <span className="tabular" style={{ flex: "none", fontSize: 12.5, color: "var(--muted)", whiteSpace: "nowrap" }}>{clock}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderRadius: 9, flex: "none", background: online ? "var(--ok-soft)" : "var(--warn-soft)", color: online ? "var(--ok)" : "var(--warn)", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: online ? "var(--ok)" : "var(--warn)" }} />
          {online ? t("common.online") : t("common.offline")}{pending > 0 ? ` · ${t("pos.pending", { n: pending })}` : ""}
        </div>
        {failed > 0 && (
          <button data-testid="failed-badge" title={t("pos.failed", { n: failed })} onClick={() => setShowFailed(true)}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderRadius: 9, flex: "none", background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12, fontWeight: 700, whiteSpace: "nowrap", border: "none", cursor: "pointer" }}>
            <Warning size={14} weight="fill" />{t("pos.failed", { n: failed })}
          </button>
        )}
      </header>

      {err && !modal && <div style={{ padding: "8px 20px", color: "var(--danger)", fontSize: 13, flex: "none" }}>{t("common.error")}: {err}</div>}

      {/* ═══ ISH MAYDONI ═══ */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", gap: 14, padding: 14 }}>

        {/* ─── CHAP ~65%: qidiruv + savat ─── */}
        <section style={{ flex: "1 1 64%", minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 12, flex: "none" }}>
            <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
              <Barcode size={19} color={B} style={{ position: "absolute", left: 15, top: "50%", transform: "translateY(-50%)" }} />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onScan}
                placeholder={t("pos.searchPlaceholder")}
                data-testid="pos-search"
                style={{ width: "100%", height: 52, padding: "0 84px 0 44px", border: `1.5px solid ${B}`, borderRadius: 12, background: "var(--card)", font: "inherit", fontSize: 15, color: "var(--text)", outline: "none" }}
              />
              <span style={{ position: "absolute", right: 44, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "var(--faint)", border: "1px solid var(--border-input)", background: "var(--surface)", borderRadius: 6, padding: "3px 8px", letterSpacing: "0.04em" }}>{t("pos.f2search")}</span>
              <MagnifyingGlass size={18} color="var(--muted)" style={{ position: "absolute", right: 15, top: "50%", transform: "translateY(-50%)" }} />
            </div>
            <button onClick={() => setCatalogOpen(true)} data-testid="open-catalog"
              style={{ flex: "none", height: 52, padding: "0 20px", border: "1px solid var(--border)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14.5, fontWeight: 600, color: "var(--text2)", display: "flex", alignItems: "center", gap: 10 }}>
              <Package size={19} color={B} />{t("pk.products")}
            </button>
          </div>

          {/* Parallel mijoz savatlari (F6 yangi · F7 keyingisi) — «kutishda saqlangan» cheklar shular */}
          {cart.carts.length > 1 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", flex: "none" }}>
              {cart.carts.map((c, i) => {
                const on = i === cart.active;
                const n = c.reduce((tt, x) => tt + (x.weighted ? 1 : x.qty), 0);
                return (
                  <div key={i} onClick={() => cart.switchCart(i)} data-testid="cart-tab"
                    style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 9, cursor: "pointer", fontSize: 12.5, fontWeight: 700, userSelect: "none",
                      background: on ? "var(--surface)" : "var(--card)", color: on ? B : "var(--text3)", border: `1.5px solid ${on ? B : "var(--border)"}` }}>
                    <span>{t("pos.customerN", { n: i + 1 })}</span>
                    {n > 0 && <span className="tabular" style={{ fontSize: 11, fontWeight: 800, background: on ? B : "var(--border-input)", color: on ? "#fff" : "var(--text3)", borderRadius: 8, padding: "1px 6px" }}>{n}</span>}
                    <span onClick={(e) => { e.stopPropagation(); if (c.length === 0 || window.confirm(t("pos.closeCartConfirm", { n: i + 1 }))) cart.closeCart(i); }}
                      style={{ marginLeft: 2, color: "var(--faint)", fontWeight: 600, fontSize: 13, lineHeight: 1 }}>✕</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* ─── SAVAT JADVALI — ekranning asosiy elementi ─── */}
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", flex: "none", padding: "0 14px", height: 44, borderBottom: "1px solid var(--border)", background: "var(--surface)", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)" }}>
              <span style={{ width: 40, flex: "none" }}>{t("pk.colNo")}</span>
              <span style={{ flex: 1, minWidth: 0 }}>{t("pk.colProduct")}</span>
              <span style={{ width: 110, flex: "none", textAlign: "right" }}>{t("pk.colPrice")}</span>
              <span style={{ width: 150, flex: "none", textAlign: "center" }}>{t("pk.colQty")}</span>
              <span style={{ width: 120, flex: "none", textAlign: "right" }}>{t("pk.colSum")}</span>
              <span style={{ width: 48, flex: "none" }} />
            </div>

            <div className="scroll" style={{ flex: 1, minHeight: 0 }} data-testid="cart-list">
              {cart.items.length === 0 ? (
                <div style={{ height: "100%", minHeight: 260, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", color: "var(--faint)" }}>
                  <div style={{ width: 66, height: 66, borderRadius: "50%", background: "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--faint)", marginBottom: 14 }}>
                    <ShoppingCart size={30} />
                  </div>
                  <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--muted)" }}>{t("pos.cartEmpty")}</div>
                  <div style={{ fontSize: 12.5, marginTop: 4, maxWidth: 240 }}>{t("pos.cartHint")}</div>
                </div>
              ) : (
                cart.items.map((it, idx) => {
                  const sel = selectedId === it.id;
                  return (
                    <div key={it.id} onClick={() => setSelectedId(it.id)} data-testid="cart-row"
                      style={{ display: "flex", alignItems: "center", padding: "0 14px", minHeight: 68, borderBottom: "1px solid var(--border-soft)", cursor: "pointer",
                        background: sel ? "var(--surface)" : "transparent", boxShadow: sel ? `inset 3px 0 0 ${B}` : "none" }}>
                      <span className="tabular" style={{ width: 40, flex: "none", fontSize: 13.5, color: "var(--muted)" }}>{idx + 1}</span>
                      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 11 }}>
                        <div style={{ width: 40, height: 40, flex: "none", borderRadius: 9, background: "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: B, fontSize: 15, fontWeight: 700 }}>
                          {it.name.charAt(0).toUpperCase()}
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em", display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</span>
                            {archivedIds.has(it.id) && (
                              <span style={{ flex: "none", padding: "1px 6px", borderRadius: 6, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 9.5, fontWeight: 800, letterSpacing: "0.04em", textTransform: "uppercase" }}>{t("pos.archived")}</span>
                            )}
                          </div>
                          {it.article && <div className="tabular" style={{ fontSize: 11, color: "var(--faint)", marginTop: 2 }}>{it.article}</div>}
                        </div>
                      </div>
                      <span className="tabular" style={{ width: 110, flex: "none", textAlign: "right", fontSize: 14, fontWeight: 600 }}>{fmt(it.price)}</span>
                      <div style={{ width: 150, flex: "none", display: "flex", justifyContent: "center" }} onClick={(e) => e.stopPropagation()}>
                        {it.weighted ? (
                          // Tarozi mahsuloti: kasr kg — ±1 stepper uni buzadi (0.5 − 1 = −0.5).
                          // Vazn FAQAT o'qish uchun; o'zgartirish qayta tortish/skaner orqali.
                          <div className="tabular" style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 11, padding: "8px 12px", fontSize: 15, fontWeight: 700 }}>
                            {it.qty} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>{t("unit.kg")}</span>
                          </div>
                        ) : (
                          <CartQty id={it.id} qty={it.qty} />
                        )}
                      </div>
                      <span className="tabular" style={{ width: 120, flex: "none", textAlign: "right", fontSize: 15, fontWeight: 700, letterSpacing: "-0.02em" }}>{fmt(it.qty * it.price)}</span>
                      <div style={{ width: 48, flex: "none", display: "flex", justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                        <button onClick={() => { cart.remove(it.id); if (selectedId === it.id) setSelectedId(null); }} title={t("pk.removeLine")}
                          style={{ width: 34, height: 34, border: "none", background: "none", cursor: "pointer", color: "var(--faint)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Trash size={17} />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </section>

        {/* ─── O'NG ~35%: mijoz · jami · to'lov ─── */}
        <aside style={{ flex: "0 0 34%", maxWidth: 470, minWidth: 320, display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Mijoz — ixtiyoriy. Tanlash to'lov oynasida (MAVJUD yo'l), bu yerda faqat holat. */}
          <div style={{ flex: "none", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14, padding: "13px 15px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <User size={18} color={B} />
              <span style={{ fontSize: 14.5, fontWeight: 700 }}>{t("pos.customer")}</span>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>({t("pk.customerOptional")})</span>
            </div>
            {/* ⚠️  `pos.creditNote` EMAS: unda `{sum}` o'zgaruvchisi bor va u to'lov oynasi uchun —
                bu yerda o'rinbosar almashmay ekranga chiqib qolardi. */}
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 7, lineHeight: 1.45 }}>{t("pk.customerHint")}</div>
          </div>

          {/* Jami */}
          <div style={{ flex: "none", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 14, padding: "15px 17px" }}>
            <div style={{ fontSize: 13.5, color: "var(--text3)", fontWeight: 600 }}>{t("pk.totalSum")}</div>
            <div className="tabular" data-testid="cart-total" style={{ fontSize: 40, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.1, marginTop: 2 }}>{fmt(payTotal)}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 6 }}>
              {t("pk.countLine", { q: cart.count(), n: cart.items.length })}
            </div>
          </div>

          {/* To'lov usullari — MAVJUD oynani o'sha usul bilan ochadi (ikkinchi yo'l YO'Q) */}
          {/* ⚠️  O'NG PANEL YORLIQLARI OYNADAGI CHIPLARDAN FARQ QILADI ("Naqd to‘lov" ≠ "Naqd").
              Maket ham shunday. Sabab shunchaki uslub emas: oyna ochiq turganda ekranda IKKI
              xil tugma bir xil nom bilan qolardi — skrinrider ham, test ham ularni ajrata
              olmasdi (a11y noaniqligi). */}
          <div style={{ flex: "none", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {payMethods.map((p) => {
              const Ic = p.Icon;
              const big = PAY_BIG[p.code] || p.label;
              return (
                <button key={p.code} disabled={payDisabled} data-testid={`pay-${p.code}`}
                  onClick={() => { if (payDisabled) return; presetRef.current = p.code; setPaid(null); setModal(true); }}
                  style={{ height: 56, borderRadius: 12, cursor: payDisabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600,
                    display: "flex", alignItems: "center", gap: 10, padding: "0 14px", opacity: payDisabled ? 0.5 : 1,
                    border: "1px solid var(--border)", background: "var(--card)", color: "var(--text2)" }}>
                  <Ic size={20} color={B} />{big}
                </button>
              );
            })}
            {/* Aralash: preset YO'Q — kassir oynada 2+ usul tanlaydi (mavjud xulq) */}
            <button disabled={payDisabled} data-testid="pay-mixed"
              onClick={() => { if (payDisabled) return; presetRef.current = null; setPaid(null); setModal(true); }}
              style={{ height: 56, borderRadius: 12, cursor: payDisabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600,
                display: "flex", alignItems: "center", gap: 10, padding: "0 14px", opacity: payDisabled ? 0.5 : 1,
                border: "1px solid var(--border)", background: "var(--card)", color: "var(--text2)" }}>
              <Tray size={20} color={B} />{t("pk.payMixed")}
            </button>
          </div>

          <div style={{ flex: 1 }} />

          {/* Asosiy to'lov — MAVJUD F4 yo'li bilan AYNI (`setModal(true)`) */}
          <button
            disabled={payDisabled}
            data-testid="pay-go"
            onClick={() => { if (!payDisabled) { presetRef.current = null; setModal(true); setPaid(null); } }}
            style={{ flex: "none", width: "100%", height: 64, border: "none", borderRadius: 14, cursor: payDisabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 17, fontWeight: 700,
              color: "#fff", background: payDisabled ? "var(--border-input)" : G, display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
              boxShadow: payDisabled ? "none" : "0 8px 22px rgba(22,163,74,0.30)" }}
          >
            <CheckCircle size={22} weight="bold" />{t("pk.payGo")}
            <span style={{ opacity: 0.75, fontSize: 12, fontWeight: 600, marginLeft: 4 }}>F4</span>
          </button>
        </aside>
      </div>

      {/* ═══ PASTKI PANEL — AYNAN TO'RT AMAL ═══ */}
      <footer style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, padding: "12px 14px", background: "var(--card)", borderTop: "1px solid var(--border)" }}>
        {[
          { key: "qty", testid: "act-qty", Icon: Plus, label: t("pk.qty"),
            disabled: !selected || !!selected.weighted,
            run: () => { const el = document.querySelector<HTMLInputElement>(`[data-qty-for="${selected!.id}"]`); el?.focus(); el?.select(); } },
          { key: "rm", testid: "act-remove", Icon: Trash, label: t("pk.removeLine"),
            disabled: !selected,
            run: () => { cart.remove(selected!.id); setSelectedId(null); } },
          { key: "hold", testid: "act-hold", Icon: Tray, label: t("pk.hold"),
            disabled: cart.items.length === 0 || cart.carts.length >= 6,
            run: () => { cart.newCart(); setSelectedId(null); } },
          { key: "clear", testid: "act-clear", Icon: X, label: t("pk.clearSale"),
            disabled: cart.items.length === 0,
            run: () => { if (window.confirm(t("pos.clearCartConfirm"))) { cart.clear(); setSelectedId(null); } } },
        ].map((a) => {
          const Ic = a.Icon;
          return (
            <button key={a.key} data-testid={a.testid} disabled={a.disabled} onClick={a.run}
              style={{ height: 52, borderRadius: 12, border: "1px solid var(--border)", background: a.disabled ? "var(--surface)" : "var(--card)",
                cursor: a.disabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600,
                color: a.disabled ? "var(--faint)" : "var(--text2)", display: "flex", alignItems: "center", justifyContent: "center", gap: 10, opacity: a.disabled ? 0.65 : 1 }}>
              <Ic size={18} color={a.disabled ? "var(--faint)" : B} />{a.label}
            </button>
          );
        })}
      </footer>

      {/* ═══ KATALOG — VAQTINCHALIK oyna (doimiy grid YO'Q) ═══ */}
      {catalogOpen && (
        <div onClick={() => setCatalogOpen(false)} data-testid="catalog-overlay"
          style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", display: "flex", alignItems: "stretch", justifyContent: "flex-end", zIndex: 21 }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{ width: "min(980px, 92vw)", background: "var(--bg)", display: "flex", flexDirection: "column", boxShadow: "-18px 0 50px rgba(0,0,0,0.30)" }}>
            <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 12, padding: "0 20px", height: 58, background: "var(--card)", borderBottom: "1px solid var(--border)" }}>
              <Package size={20} color={B} />
              <span style={{ fontSize: 16, fontWeight: 700 }}>{t("pk.catalogTitle")}</span>
              <div style={{ flex: 1 }} />
              <button onClick={() => setCatalogOpen(false)} data-testid="catalog-close"
                style={{ width: 36, height: 36, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <X size={17} />
              </button>
            </div>

            <div style={{ flex: "none", padding: "14px 20px 4px", display: "flex", gap: 9, flexWrap: "wrap" }}>
              {[{ id: "all", name: t("pos.all") }, ...cats].map((c) => {
                const on = activeCat === c.id;
                return (
                  <button key={c.id} onClick={() => setActiveCat(c.id)}
                    style={{ height: 36, padding: "0 16px", borderRadius: 19, font: "inherit", fontSize: 13, fontWeight: 600, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${on ? B : "var(--border)"}`, background: on ? B : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>
                    {c.name}
                  </button>
                );
              })}
            </div>

            <div className="scroll" style={{ flex: 1, minHeight: 0, padding: "14px 20px 20px" }}>
              {products.length === 0 && (
                <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("pos.catalogEmpty")}</div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 13 }}>
                {shown.map((p) => {
                  const qty = cartMap[p.id] || 0;
                  const low = p.stock <= 5;
                  return (
                    <button key={p.id} data-testid="catalog-product"
                      onClick={() => {
                        if (p.is_weighted) { setWeigh(p); setWeighVal(""); setCatalogOpen(false); return; }
                        cart.add({ id: p.id, name: p.name, price: p.base_sell_price, article: p.article_code });
                        if (query.trim()) { bumpUsage(p.id); setUsageTick((v) => v + 1); }
                      }}
                      style={{ textAlign: "left", cursor: "pointer", padding: 13, borderRadius: 13, background: "var(--card)", border: `1.5px solid ${qty > 0 ? B : "var(--border)"}`, display: "flex", flexDirection: "column", gap: 10, position: "relative", font: "inherit", color: "var(--text)" }}>
                      {qty > 0 && (
                        <span style={{ position: "absolute", top: 10, right: 10, minWidth: 22, height: 22, padding: "0 6px", borderRadius: 11, background: B, color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{qty}</span>
                      )}
                      {p.is_active === false && (
                        <span style={{ position: "absolute", top: 10, left: 10, padding: "2px 8px", borderRadius: 8, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 10.5, fontWeight: 800, letterSpacing: "0.04em", textTransform: "uppercase" }}>{t("pos.archived")}</span>
                      )}
                      <div style={{ width: "100%", aspectRatio: "1.6", borderRadius: 10, background: "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: qty > 0 ? B : "var(--faint)", fontSize: 26, fontWeight: 700, letterSpacing: "-0.03em" }}>{p.name.charAt(0).toUpperCase()}</div>
                      <div>
                        <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.25, letterSpacing: "-0.01em" }}>{p.name}</div>
                        <div className="tabular" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>{p.article_code}</div>
                        <div style={{ fontSize: 11.5, color: low ? "var(--danger)" : "var(--muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
                          <Package size={12} />{p.stock} {p.unit_code || t("pos.unit")}{low ? ` · ${t("pos.low")}` : ""}
                        </div>
                      </div>
                      <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.02em" }}>{fmt(p.base_sell_price)}</div>
                    </button>
                  );
                })}
              </div>
              {products.length > 0 && shown.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("pos.notFound")}</div>}
            </div>
          </div>
        </div>
      )}

      {showFailed && (
        <Modal onClose={() => setShowFailed(false)} width={560}>
          <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>{t("pos.failedTitle")}</div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14, lineHeight: 1.5 }}>{t("pos.failedHelp")}</div>
          {confirmClear && (
            <div data-testid="failed-clear-warn"
                 style={{ fontSize: 13, color: "var(--danger)", fontWeight: 700, marginBottom: 14, lineHeight: 1.5 }}>
              {t("pos.failedClearWarn")}
            </div>
          )}
          <div className="scroll" style={{ maxHeight: 320, display: "flex", flexDirection: "column", gap: 8 }}>
            {failedSales().map((f: any, i: number) => (
              <div key={f.client_uuid || i} data-testid="failed-row"
                   style={{ padding: "10px 12px", borderRadius: 10, background: "var(--surface)", fontSize: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ fontWeight: 700 }}>{new Date(f.created_at).toLocaleString()}</span>
                  <span className="tabular" style={{ fontWeight: 800 }}>
                    {fmt(Number((f.payload as any)?.expected_total ?? (f.payload as any)?.total ?? (f.payload as any)?.paid ?? 0))}
                  </span>
                </div>
                <div style={{ color: "var(--danger)", marginTop: 4, wordBreak: "break-word" }}>{f.error}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }}
                    onClick={() => { setConfirmClear(false); setShowFailed(false); }}>{t("common.close")}</button>
            {!confirmClear ? (
              <button className="btn" data-testid="failed-clear" style={{ flex: 1, background: "var(--danger)", color: "#fff" }}
                      onClick={() => setConfirmClear(true)}>{t("pos.failedClear")}</button>
            ) : (
              <button className="btn" data-testid="failed-clear-confirm" style={{ flex: 1, background: "var(--danger)", color: "#fff" }}
                      onClick={() => { clearFailed(); setConfirmClear(false); setShowFailed(false); }}>
                {t("pos.failedClearConfirm")}
              </button>
            )}
          </div>
        </Modal>
      )}

      {/* ═══ VAZN (kg) KIRITISH — tarozi mahsuloti panelдан bosilганда ═══ */}
      {weigh && (() => {
        // 0.001 kg ga server qoidasi bilan — savat, ko'rinadigan summa, payload va chek BIR xil qty'da.
        const kg = kgOf(weighVal);
        const addWeighed = () => {
          if (kg <= 0) return;
          cart.add({ id: weigh.id, name: weigh.name, price: weigh.base_sell_price, article: weigh.article_code, qty: kg, weighted: true });
          setWeigh(null); setWeighVal("");
        };
        return (
          <div onClick={() => { setWeigh(null); setWeighVal(""); }} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 22 }}>
            <div onClick={(e) => e.stopPropagation()} style={{ width: 360, background: "var(--card)", borderRadius: 18, padding: 24, boxShadow: "0 24px 60px rgba(0,0,0,0.4)" }}>
              <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em" }}>{weigh.name}</div>
              <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>{fmt(weigh.base_sell_price)} / {t("unit.kg")}</div>
              <input autoFocus type="text" inputMode="decimal" value={weighVal}
                onChange={(e) => setWeighVal(e.target.value.replace(/[^0-9.,]/g, ""))}
                onKeyDown={(e) => { if (e.key === "Enter") addWeighed(); if (e.key === "Escape") { setWeigh(null); setWeighVal(""); } }}
                placeholder={`0.000 ${t("unit.kg")}`}
                style={{ width: "100%", marginTop: 16, height: 54, borderRadius: 12, border: "1px solid var(--border)", background: "var(--surface)", textAlign: "center", fontSize: 24, fontWeight: 800, color: "var(--text)" }} />
              <div className="tabular" style={{ textAlign: "center", marginTop: 10, fontSize: 15, fontWeight: 700, color: kg > 0 ? "var(--text)" : "var(--faint)" }}>{fmt(Math.round(kg * weigh.base_sell_price + 1e-6))}</div>
              <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                <button onClick={() => { setWeigh(null); setWeighVal(""); }} style={{ flex: 1, height: 46, border: "1px solid var(--border)", background: "var(--surface)", borderRadius: 11, cursor: "pointer", fontWeight: 600, color: "var(--text)" }}>{t("common.cancel")}</button>
                <button onClick={addWeighed} disabled={kg <= 0} style={{ flex: 1, height: 46, border: "none", background: kg > 0 ? A : "var(--border)", color: "#fff", borderRadius: 11, cursor: kg > 0 ? "pointer" : "default", fontWeight: 700 }}>{t("common.add")}</button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ═══ PAYMENT MODAL ═══ */}
      {modal && (
        <div onClick={() => !busy && setModal(false)} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: 428, background: "var(--card)", borderRadius: 20, padding: 26, boxShadow: "0 24px 60px rgba(0,0,0,0.4)", maxHeight: "92vh", overflowY: "auto" }}>
            {!paid ? (
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                  <div style={{ fontSize: 21, fontWeight: 700, letterSpacing: "-0.02em" }}>{t("pay.title")}</div>
                  <button onClick={() => setModal(false)} style={{ width: 34, height: 34, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <X size={16} />
                  </button>
                </div>
                <div style={{ textAlign: "center", padding: "18px 0 22px", background: "var(--surface-accent)", borderRadius: 14, marginBottom: 20 }}>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>{t("pay.amount")}</div>
                  <div className="tabular" style={{ fontSize: 44, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 4 }}>{fmt(payTotal)}</div>
                </div>

                {/* ═══ Usul chiplari — bosilsa o'sha usul qatori qo'shiladi (summa = qolgan, avto). Bittasi = oddiy, ko'pi = aralash ═══ */}
                <div style={{ fontSize: 13, color: "var(--text3)", marginBottom: 11 }}>{t("pos.splitHint")}</div>
                <div style={{ display: "flex", gap: 9, marginBottom: activeCodes.length ? 16 : 2, flexWrap: "wrap" }}>
                  {payMethods.map((p) => {
                    const on = p.code in splitAmts;
                    const Ic = p.Icon;
                    return (
                      <button key={p.code}
                        onClick={() => setSplitAmts((s) => (p.code in s ? s : { ...s, [p.code]: String(Math.max(payRemaining, 0)) }))}
                        style={{ position: "relative", flex: "1 1 0", minWidth: 76, height: 76, borderRadius: 14, cursor: "pointer", font: "inherit", fontSize: 12.5, fontWeight: 600, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, border: `1.5px solid ${on ? A : "var(--border)"}`, background: on ? ASOFT : "var(--card)", color: on ? AT : "var(--muted)" }}>
                        {on && <span style={{ position: "absolute", top: 7, right: 7, width: 18, height: 18, borderRadius: "50%", background: A, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}><Check size={11} weight="bold" /></span>}
                        <Ic size={23} />{p.label}
                      </button>
                    );
                  })}
                </div>

                {activeCodes.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                    {payMethods.filter((p) => p.code in splitAmts).map((p) => {
                      const Ic = p.Icon;
                      return (
                        <div key={p.code} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 8px 9px 14px", borderRadius: 13, background: "var(--surface)", border: "1px solid var(--border)" }}>
                          <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 9, fontSize: 14.5, fontWeight: 600, color: AT }}><Ic size={20} />{p.label}</div>
                          <input value={splitAmts[p.code] || ""} inputMode="numeric" placeholder="0"
                            onFocus={() => setSplitAmts((s) => ({ ...s, [p.code]: "" }))}
                            onChange={(e) => setSplitAmts((s) => ({ ...s, [p.code]: e.target.value.replace(/\D/g, "") }))}
                            style={{ flex: 1, minWidth: 0, height: 40, padding: "0 6px", border: "none", background: "transparent", font: "inherit", fontSize: 22, fontWeight: 800, color: "var(--text)", outline: "none", textAlign: "right", letterSpacing: "-0.02em" }} />
                          <span style={{ flex: "none", fontSize: 13, color: "var(--muted)", fontWeight: 600 }}>{curUnit}</span>
                          <button onClick={() => setSplitAmts((s) => { const n = { ...s }; delete n[p.code]; return n; })}
                            style={{ width: 30, height: 30, flex: "none", border: "none", background: "var(--card)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                            <X size={14} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}

                {activeCodes.length === 0 && (
                  <div style={{ padding: "16px 0 4px", textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("pos.splitPick")}</div>
                )}

                {hasCredit && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                      <button onClick={() => setCreditMode("existing")} style={{ flex: 1, height: 46, borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, border: `1.5px solid ${creditMode === "existing" ? A : "var(--border)"}`, background: creditMode === "existing" ? ASOFT : "var(--card)", color: creditMode === "existing" ? AT : "var(--muted)" }}>
                        <User size={17} />{t("pos.customer")}
                      </button>
                      <button onClick={() => setCreditMode("new")} style={{ flex: 1, height: 46, borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, border: `1.5px solid ${creditMode === "new" ? A : "var(--border)"}`, background: creditMode === "new" ? ASOFT : "var(--card)", color: creditMode === "new" ? AT : "var(--muted)" }}>
                        <UserPlus size={17} />{t("pos.newCustomer")}
                      </button>
                    </div>

                    {creditMode === "existing" && (
                      <div>
                        <div style={{ position: "relative", marginBottom: 10 }}>
                          <MagnifyingGlass size={16} color="var(--muted)" style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)" }} />
                          <input value={custQuery} onChange={(e) => setCustQuery(e.target.value)} placeholder={t("pos.custSearch")}
                            style={{ width: "100%", height: 44, padding: "0 14px 0 38px", border: "1.5px solid var(--border-input)", borderRadius: 11, font: "inherit", fontSize: 13.5, background: "var(--card)", color: "var(--text)", outline: "none" }} />
                        </div>
                        <div style={{ maxHeight: 160, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                          {shownCustomers.map((cu) => {
                            const on = customerId === cu.id;
                            return (
                              <button key={cu.id} onClick={() => setCustomerId(cu.id)}
                                style={{ textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: 11, padding: "10px 12px", borderRadius: 11, border: `1.5px solid ${on ? A : "var(--border)"}`, background: on ? ASOFT : "var(--card)", font: "inherit" }}>
                                <div style={{ width: 34, height: 34, flex: "none", borderRadius: "50%", background: ASOFT, color: AT, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700 }}>{cu.full_name.charAt(0)}</div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{cu.full_name}</div>
                                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{cu.phone}</div>
                                </div>
                                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", background: "var(--surface)", padding: "3px 8px", borderRadius: 7 }}>{cu.code}</span>
                              </button>
                            );
                          })}
                          {shownCustomers.length === 0 && <div style={{ padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("pos.custNotFound")}</div>}
                        </div>
                      </div>
                    )}

                    {creditMode === "new" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        <div style={{ display: "flex", gap: 10 }}>
                          <input value={newFirst} onChange={(e) => setNewFirst(e.target.value)} placeholder={t("pos.firstName")} style={{ flex: 1, minWidth: 0, height: 44, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, font: "inherit", fontSize: 13.5, background: "var(--card)", color: "var(--text)", outline: "none" }} />
                          <input value={newLast} onChange={(e) => setNewLast(e.target.value)} placeholder={t("pos.lastName")} style={{ flex: 1, minWidth: 0, height: 44, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, font: "inherit", fontSize: 13.5, background: "var(--card)", color: "var(--text)", outline: "none" }} />
                        </div>
                        <input value={newPhone} onChange={(e) => setNewPhone(e.target.value)} placeholder={t("pos.phonePlaceholder")} inputMode="tel" style={{ width: "100%", height: 44, padding: "0 13px", border: "1.5px solid var(--border-input)", borderRadius: 11, font: "inherit", fontSize: 13.5, background: "var(--card)", color: "var(--text)", outline: "none" }} />
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "11px 14px", borderRadius: 11, background: "var(--surface)" }}>
                          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("pos.givenId")}</span>
                          <span style={{ fontSize: 13, fontWeight: 700, color: AT, background: ASOFT, padding: "3px 10px", borderRadius: 8 }}>{previewId}</span>
                        </div>
                      </div>
                    )}

                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "13px 15px", borderRadius: 12, background: "var(--warn-soft)", color: "var(--warn)", marginTop: 14 }}>
                      <Notebook size={18} style={{ marginTop: 1, flex: "none" }} />
                      <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{t("pos.creditNote", { sum: fmt(payAmt("credit")) })}</div>
                    </div>
                  </div>
                )}

                {activeCodes.length > 0 && (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", borderRadius: 12, background: payOk ? "var(--ok-soft)" : (payRemaining > 0 ? "var(--warn-soft)" : "var(--danger-soft)"), marginTop: 16, marginBottom: 4 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 600, color: payOk ? "var(--ok)" : "var(--text3)" }}>
                      {payOk && <CheckCircle size={18} weight="fill" />}
                      {payChange > 0 ? t("pay.change") : payRemaining < 0 ? t("pos.splitOver") : t("pos.splitRemaining")}
                    </span>
                    <span className="tabular" style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: payOk ? "var(--ok)" : (payRemaining > 0 ? "var(--warn)" : "var(--danger)") }}>{fmt(payChange > 0 ? payChange : Math.abs(payRemaining))}</span>
                  </div>
                )}

                {/* XPAY avto-QR paneli: mijoz skanerlashi uchun QR + jonli holat */}
                {xpayQr && (
                  <div style={{ marginTop: 14, padding: 16, border: "1.5px dashed var(--border-input)", borderRadius: 14, textAlign: "center" }}>
                    {qrStat === "loading" && <div style={{ color: "var(--muted)", fontSize: 13.5 }}>{t("pos.qrCreating")}</div>}
                    {qrStat === "waiting" && (
                      <>
                        {qrUrl && qrImgOk
                          ? <img src={qrUrl} alt="QR" onError={() => setQrImgOk(false)} style={{ width: 180, height: 180, borderRadius: 10, background: "#fff" }} />
                          : <div style={{ fontSize: 13, color: "var(--muted)" }}>{qrUrl}</div>}
                        <div style={{ marginTop: 10, fontSize: 13, fontWeight: 600, color: "var(--warn)" }}>{t("pos.qrWaiting")}</div>
                      </>
                    )}
                    {qrStat === "done" && <div style={{ color: "var(--ok)", fontSize: 14, fontWeight: 700 }}>✓ {t("pos.paidOk")}</div>}
                    {qrStat === "error" && <div style={{ color: "var(--danger)", fontSize: 13 }}>{qrErr}</div>}
                  </div>
                )}

                {err && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 12 }}>{err}</div>}

                <button
                  onClick={finish}
                  disabled={busy || !payOk || xpayWait}
                  style={{ width: "100%", height: 56, border: "none", borderRadius: 13, cursor: busy || !payOk || xpayWait ? "not-allowed" : "pointer", font: "inherit", fontSize: 16, fontWeight: 700, color: "#fff", background: busy || !payOk || xpayWait ? "#c9ccd8" : A, display: "flex", alignItems: "center", justifyContent: "center", gap: 9, boxShadow: busy || !payOk || xpayWait ? "none" : "0 8px 22px rgba(109,93,211,0.35)", marginTop: 16 }}
                >
                  <Check size={20} weight="bold" />{busy ? "..." : xpayWait ? t("pos.qrWaiting") : (activeCodes.length === 1 && activeCodes[0] === "credit") ? t("pay.creditWrite") : t("pay.finish")}
                </button>
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "12px 4px" }}>
                <div style={{ width: 82, height: 82, margin: "0 auto 18px", borderRadius: "50%", background: paid.offline ? "var(--warn-soft)" : "var(--ok-soft)", display: "flex", alignItems: "center", justifyContent: "center", color: paid.offline ? "var(--warn)" : "var(--ok)" }}>
                  {paid.offline ? <Tray size={44} weight="fill" /> : <CheckCircle size={44} weight="fill" />}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em" }}>{paid.offline ? t("pos.paidOffline") : t("pos.paidOk")}</div>
                <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 6 }}>{paid.offline ? `${paidSummary} · ${t("pos.willSync")}` : paidSummary}</div>
                {!paid.offline && (
                  <div className="tabular" style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 12, padding: "9px 15px", borderRadius: 10, background: "var(--surface)", fontSize: 14, fontWeight: 700, color: "var(--text2)" }}>
                    <span style={{ fontWeight: 500, color: "var(--muted)" }}>{t("pos.receiptNo")}</span>{paid.receipt_no}
                  </div>
                )}
                {prefs.returns && !paid.offline && paid.uid && (
                  <div style={{ margin: "18px 0 2px", padding: 14, border: "1px dashed var(--border-input)", borderRadius: 12 }}>
                    <div style={{ display: "flex", alignItems: "stretch", height: 44, justifyContent: "center" }}>
                      {posBars(paid.uid).map((b, i) => <div key={i} style={{ width: b.w, background: b.bg }} />)}
                    </div>
                    <div className="tabular" style={{ textAlign: "center", fontSize: 11.5, letterSpacing: 3, color: "var(--text3)", marginTop: 6 }}>{paid.uid}</div>
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 24 }}>
                  {/* Asl chek chop etilgach tugma NUSXA bo'ladi (qog'ozda "NUSXA #n" banneri). */}
                  <button data-testid="pos-print" onClick={() => void pr.print("manual")} style={{ height: 52, border: "1.5px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14.5, fontWeight: 600, color: "var(--text2)", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <Printer size={18} />{pr.printedOnce ? t("pr.reprint") : t("pos.printReceipt")}
                  </button>
                  {/* "E-chek" — hozirgidek AYNAN o'sha chop etish (alohida e-chek xizmati yo'q, o'ylab topilmaydi). */}
                  <button data-testid="pos-echek" onClick={() => void pr.print("manual")} title={t("pos.eReceiptTitle")} style={{ height: 52, border: "1.5px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600, color: "var(--text2)", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <DeviceMobile size={18} />{t("pos.eReceipt")}
                  </button>
                  <button onClick={newSale} style={{ gridColumn: "1 / -1", height: 52, border: "none", background: A, borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14.5, fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <Plus size={18} />{t("pos.newSale")}
                  </button>
                </div>
                <PrintStatus state={pr} style={{ marginTop: 12 }} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
