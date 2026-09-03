import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
  Barcode,
  Check,
  CheckCircle,
  CreditCard,
  DeviceMobile,
  List,
  MagnifyingGlass,
  MapPin,
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
import { fmt } from "@/lib/format";
import { useCart } from "@/store/cart";
import { useAuth } from "@/store/auth";
import { useNav } from "@/store/nav";
import { useUpdate } from "@/store/update";
import { CACHE, cacheGet } from "@/lib/offline";
import { readPrefs } from "@/lib/prefs";
import { useT } from "@/lib/i18n";
import { printReceipt, type ReceiptData } from "@/lib/receipt";
import { refreshCatalog, submitSale, useOnline, usePendingCount, useFailedCount } from "@/lib/sync";

interface Product { id: string; article_code: string; name: string; category_id: string | null; base_sell_price: number; stock: number; barcodes?: string[]; plu_code?: string | null; is_weighted?: boolean; sold_qty?: number; unit_code?: string; is_active?: boolean; }

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
  const [paid, setPaid] = useState<ReceiptData | null>(null);
  const [paidSummary, setPaidSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Tarozi mahsuloti panelдан bosilса — vazn (kg) so'raymiz (aks holда 1 dona = 1 kg bo'lib
  // ±1 stepper bilan noto'g'ri sotилаrди; tarozini/skanerни chetlab o'tardi).
  const [weigh, setWeigh] = useState<Product | null>(null);
  const [weighVal, setWeighVal] = useState("");
  const [prefs, setPrefs] = useState(readPrefs);
  const searchRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  // QA CART-02: vazn (kg) dialogi ochiqligini window-keydown listener'ida ko'rish uchun (ref — listener
  // qayta obuna bo'lmaydi). Dialog ochiqda global F4/F6/F7/± yorliqlari bloklanadi.
  const weighRef = useRef(false);
  weighRef.current = !!weigh;

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

  function onScan(e: React.KeyboardEvent) {
    if (e.key !== "Enter") return;
    const term = query.trim();
    if (!term) return;
    // Tarozi etiketkasi (EAN-13, prefiks "2"): 2 + PLU(6) + gramm(5) + nazorat(1)
    const digits = term.replace(/\D/g, "");
    if (digits.length === 13 && digits[0] === "2") {
      const pluNum = parseInt(digits.slice(1, 7), 10);
      const grams = parseInt(digits.slice(7, 12), 10);
      const wp = products.find((p) => p.is_weighted && p.plu_code && parseInt(String(p.plu_code), 10) === pluNum);
      if (wp && grams > 0) {
        // Haqiqiy mahsulot id + vazn (kg) qty sifatida — savdo/ombor to'g'ri yoziladi (narx = 1 kg narxi)
        cart.add({ id: wp.id, name: wp.name, price: wp.base_sell_price, article: wp.article_code, qty: grams / 1000, weighted: true });
        bumpUsage(wp.id); setUsageTick((v) => v + 1);
        setQuery("");
        return;
      }
    }
    const exact = products.find((p) => (p.barcodes || []).includes(term));
    const hit = exact || shown[0];
    if (hit) {
      // QA PC-014: tarozi mahsuloti skaner/Enter yo'lida ham VAZN so'raydi (grid bilan bir xil) —
      // aks holda 1 dona = 1 kg bo'lib, ±1 stepper bilan noto'g'ri sotilardi.
      if (hit.is_weighted) { setWeigh(hit); setWeighVal(""); setQuery(""); return; }
      cart.add({ id: hit.id, name: hit.name, price: hit.base_sell_price, article: hit.article_code });
      bumpUsage(hit.id); setUsageTick((v) => v + 1);
      setQuery("");
    }
  }

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
            const c = await post<CustomerRow>("/customers", { full_name: name, phone: newPhone || null });
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
      const allowOffline = active.every(methodOffline);
      const r = await submitSale({
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
        expected_total: payTotal,   // QA PC-001: POS ko'rsatgan jami — server farq ko'rsa 409
        qr_txn_id: qrTxn || undefined,   // QA PAY-01: XPAY QR bo'lsa server tasdiqlaydi/consume qiladi (offline flush'da ham)
      }, { allowOffline, offlineErr: t("pos.errNeedNet") });
      const payLbl = (code: string) => code === "cash" ? t("pay.cash") : code === "card" ? t("pay.card") : code === "qr" ? t("pos.qrPay") : t("pay.credit");
      setPaidSummary(
        !single
          ? `${fmt(payTotal)} · ${active.map((c) => `${payLbl(c)} ${fmt(payAmt(c))}`).join(" + ")}`
          : soleCode === "credit" ? `${fmt(payTotal)} · ${payLbl("credit")} · ${custName}` : `${fmt(payTotal)} · ${payLbl(soleCode)}`
      );
      setPaid({
        receipt_no: r.offline ? "OFFLINE" : r.receipt_no || "—",
        offline: r.offline,
        uid: r.uid,
        store: prefs.storeName,
        branch: employee?.branch_name || prefs.branchName,  // QA SB-014: kompaniya-darajali bitta nom emas, xodim filiali
        cashier: employee?.full_name || t("pos.cashier"),
        items: cart.items.map((i) => ({ name: i.name, qty: i.qty, price: i.price, line: i.qty * i.price })),
        total: payTotal,
        method: single ? soleCode : "split",
        given: cashOnly ? payAmt("cash") : payTotal,
        change: payChange,
        date: new Date().toLocaleString("ru-RU"),
      });
      cart.finishActive(); // faol savat yopiladi (boshqa mijozlarniki qoladi) — qayta sotib bo'lmaydi
      // QA PAY-10: kalit "ishlatildi" — keyingi checkout (istalgan savat) YANGI kalit oladi. Aks holda
      // "Yangi savdo" bosilmay keyingi mijoz savdosi shu kalit bilan serverда dedup'ga tushardi.
      saleUuidRef.current = crypto.randomUUID();
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

  const cartMap: Record<string, number> = {};
  cart.items.forEach((i) => (cartMap[i.id] = i.qty));

  const payDisabled = cart.items.length === 0;

  // Dizayn: to'lov usullari sozlamadan (savdoos_payments) — o'chirilganlari ko'rinmaydi
  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex" }}>
      <main className="main">
        {/* ═══ Top bar (dizayn: hamburger + do'kon nomi + qidiruv) ═══ */}
        <header style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 24px", background: "var(--card)", borderBottom: "1px solid var(--border)" }}>
          <button onClick={openNav} title={t("pos.menu")} style={{ width: 44, height: 44, flex: "none", border: "1px solid var(--border)", background: "var(--card)", borderRadius: 11, cursor: "pointer", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
            <List size={21} />
            {updReady && <span style={{ position: "absolute", top: 7, right: 7, width: 9, height: 9, borderRadius: "50%", background: "var(--accent)", border: "2px solid var(--card)" }} />}
          </button>
          <div style={{ flex: "none" }}>
            <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em", display: "flex", alignItems: "center", gap: 7 }}>
              <MapPin size={15} color={A} />{prefs.storeName}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1 }}>{prefs.branchName}</div>
          </div>

          <div style={{ flex: 1, position: "relative" }}>
            <Barcode size={19} color="var(--muted)" style={{ position: "absolute", left: 15, top: "50%", transform: "translateY(-50%)" }} />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onScan}
              placeholder={t("pos.searchPlaceholder")}
              style={{ width: "100%", height: 46, padding: "0 96px 0 44px", border: "1px solid var(--border-input)", borderRadius: 11, background: "var(--surface)", font: "inherit", fontSize: 14.5, color: "var(--text)", outline: "none" }}
            />
            <span style={{ position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "var(--faint)", border: "1px solid var(--border-input)", background: "var(--card)", borderRadius: 6, padding: "3px 8px", letterSpacing: "0.04em" }}>{t("pos.f2search")}</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 12px", borderRadius: 10, flex: "none", background: online ? "var(--ok-soft)" : "var(--warn-soft)", color: online ? "var(--ok)" : "var(--warn)", fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "var(--ok)" : "var(--warn)" }} />
            {online ? t("common.online") : t("common.offline")}{pending > 0 ? ` · ${t("pos.pending", { n: pending })}` : ""}
          </div>
          {failed > 0 && (
            <div title={t("pos.failed", { n: failed })} style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 12px", borderRadius: 10, flex: "none", background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12.5, fontWeight: 700, whiteSpace: "nowrap" }}>
              <Warning size={15} weight="fill" />{t("pos.failed", { n: failed })}
            </div>
          )}
        </header>

        {err && !modal && <div style={{ padding: "10px 24px", color: "var(--danger)", fontSize: 13 }}>{t("common.error")}: {err}</div>}

        {/* ═══ Categories ═══ */}
        <div style={{ padding: "18px 24px 4px", display: "flex", gap: 9, flexWrap: "wrap" }}>
          {[{ id: "all", name: t("pos.all") }, ...cats].map((c) => {
            const on = activeCat === c.id;
            return (
              <button key={c.id} onClick={() => setActiveCat(c.id)}
                style={{ height: 38, padding: "0 17px", borderRadius: 20, font: "inherit", fontSize: 13.5, fontWeight: 600, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${on ? A : "var(--border)"}`, background: on ? A : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>
                {c.name}
              </button>
            );
          })}
        </div>

        {/* ═══ Product grid ═══ */}
        <div className="scroll" style={{ flex: 1, padding: "16px 24px 24px" }}>
          {products.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
              {t("pos.catalogEmpty")}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            {shown.map((p) => {
              const qty = cartMap[p.id] || 0;
              const low = p.stock <= 5;
              return (
                <button key={p.id} onClick={() => { if (p.is_weighted) { setWeigh(p); setWeighVal(""); return; } cart.add({ id: p.id, name: p.name, price: p.base_sell_price, article: p.article_code }); if (query.trim()) { bumpUsage(p.id); setUsageTick((v) => v + 1); } }}
                  style={{ textAlign: "left", cursor: "pointer", padding: 14, borderRadius: 14, background: "var(--card)", border: `1.5px solid ${qty > 0 ? A : "var(--border)"}`, boxShadow: "0 1px 2px rgba(10,12,20,0.04)", display: "flex", flexDirection: "column", gap: 11, position: "relative", font: "inherit", color: "var(--text)" }}>
                  {qty > 0 && (
                    <span style={{ position: "absolute", top: 10, right: 10, minWidth: 22, height: 22, padding: "0 6px", borderRadius: 11, background: A, color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{qty}</span>
                  )}
                  {/* QA PC-006 (boss qarori): arxiv tovar SOTILADI, lekin kassir ANIQ ko'rsin */}
                  {p.is_active === false && (
                    <span style={{ position: "absolute", top: 10, left: 10, padding: "2px 8px", borderRadius: 8, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 10.5, fontWeight: 800, letterSpacing: "0.04em", textTransform: "uppercase" }}>{t("pos.archived")}</span>
                  )}
                  <div style={{ width: "100%", aspectRatio: "1.5", borderRadius: 10, background: qty > 0 ? ASOFT : "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: qty > 0 ? AT : "var(--faint)", fontSize: 28, fontWeight: 700, letterSpacing: "-0.03em" }}>{p.name.charAt(0).toUpperCase()}</div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.25, letterSpacing: "-0.01em" }}>{p.name}</div>
                    <div className="tabular" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>{p.article_code}</div>
                    <div style={{ fontSize: 11.5, color: low ? "var(--danger)" : "var(--muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
                      <Package size={12} />{p.stock} {p.unit_code || t("pos.unit")}{low ? ` · ${t("pos.low")}` : ""}
                    </div>
                  </div>
                  <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--text)" }}>{fmt(p.base_sell_price)}</div>
                </button>
              );
            })}
          </div>
          {products.length > 0 && shown.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("pos.notFound")}</div>}
        </div>
      </main>

      {/* ═══ CART ═══ */}
      <aside style={{ width: 398, flex: "none", background: "var(--card)", borderLeft: "1px solid var(--border)", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 22px 10px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.02em" }}>{t("pos.cart")}</div>
            <span style={{ fontSize: 12, fontWeight: 600, color: A, background: ASOFT, padding: "2px 9px", borderRadius: 12 }}>{cart.count()}</span>
          </div>
          <button onClick={() => { if (cart.items.length === 0 || window.confirm(t("pos.clearCartConfirm"))) cart.clear(); }} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, fontWeight: 500, font: "inherit" }}>
            <Trash size={15} />{t("pos.clearCart")}
          </button>
        </div>

        {/* Parallel mijozlar: har tab — alohida savat. + yangi mijoz (F6), F7 — keyingisi */}
        <div style={{ display: "flex", gap: 6, padding: "0 22px 12px", flexWrap: "wrap", alignItems: "center" }}>
          {cart.carts.map((c, i) => {
            const on = i === cart.active;
            // QA CART-03: tarozi qatori 1 dona (kasr kg emas) — savat-tab badge'i butun son bo'lsin
            const n = c.reduce((tt, x) => tt + (x.weighted ? 1 : x.qty), 0);
            return (
              <div key={i} onClick={() => cart.switchCart(i)}
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 9,
                  cursor: "pointer", fontSize: 12.5, fontWeight: 700, userSelect: "none",
                  background: on ? ASOFT : "var(--surface)", color: on ? AT : "var(--text3)",
                  border: `1.5px solid ${on ? "var(--accent-border)" : "var(--border)"}`,
                }}>
                <span>{t("pos.customerN", { n: i + 1 })}</span>
                {n > 0 && <span className="tabular" style={{ fontSize: 11, fontWeight: 800, background: on ? "var(--accent)" : "var(--border-input)", color: on ? "#fff" : "var(--text3)", borderRadius: 8, padding: "1px 6px" }}>{n}</span>}
                {cart.carts.length > 1 && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation();
                      if (c.length === 0 || window.confirm(t("pos.closeCartConfirm", { n: i + 1 }))) cart.closeCart(i);
                    }}
                    style={{ marginLeft: 2, color: "var(--faint)", fontWeight: 600, fontSize: 13, lineHeight: 1 }}>✕</span>
                )}
              </div>
            );
          })}
          {cart.carts.length < 6 && (
            <button onClick={cart.newCart} title={t("pos.newCartTip")}
              style={{ border: "1.5px dashed var(--accent-border)", background: "none", color: AT, cursor: "pointer", borderRadius: 9, padding: "5px 11px", fontSize: 13, fontWeight: 800, font: "inherit" }}>
              ＋
            </button>
          )}
        </div>

        <div className="scroll" style={{ flex: 1, padding: "0 22px" }}>
          {cart.items.length === 0 ? (
            <div style={{ height: "100%", minHeight: 340, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", color: "var(--faint)" }}>
              <div style={{ width: 66, height: 66, borderRadius: "50%", background: "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--faint)", marginBottom: 14 }}>
                <ShoppingCart size={30} />
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--muted)" }}>{t("pos.cartEmpty")}</div>
              <div style={{ fontSize: 12.5, marginTop: 4, maxWidth: 210 }}>{t("pos.cartHint")}</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, paddingBottom: 8 }}>
              {cart.items.map((it) => (
                <div key={it.id} style={{ display: "flex", gap: 12, padding: 12, borderRadius: 12, background: "var(--surface)" }}>
                  <div style={{ width: 42, height: 42, flex: "none", borderRadius: 9, background: ASOFT, display: "flex", alignItems: "center", justifyContent: "center", color: AT, fontSize: 16, fontWeight: 700 }}>{it.name.charAt(0).toUpperCase()}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-0.01em", display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</span>
                        {archivedIds.has(it.id) && (
                          <span style={{ flex: "none", padding: "1px 6px", borderRadius: 6, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 9.5, fontWeight: 800, letterSpacing: "0.04em", textTransform: "uppercase" }}>{t("pos.archived")}</span>
                        )}
                      </div>
                      <button onClick={() => cart.remove(it.id)} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", padding: 0, lineHeight: 1, flex: "none" }}>
                        <X size={15} />
                      </button>
                    </div>
                    {it.article && <div className="tabular" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>{it.article}</div>}
                    <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{it.qty} × {fmt(it.price)}</div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 9 }}>
                      {it.weighted ? (
                        // Tarozi mahsuloti: vazn (kg) kasr — ±1 stepper uni buzadi (0.5 − 1 = −0.5 → qator o'chib ketardi).
                        // Shuning uchun vaznni FAQAT o'qish uchun ko'rsatamiz; o'zgartirish qayta tortish/skaner orqali.
                        <div className="tabular" style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 11, padding: "9px 14px", fontSize: 16, fontWeight: 700 }}>
                          {it.qty} <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--muted)" }}>{t("unit.kg")}</span>
                        </div>
                      ) : (
                        <CartQty id={it.id} qty={it.qty} />
                      )}
                      <div className="tabular" style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.02em" }}>{fmt(it.qty * it.price)}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ═══ Totals + payment ═══ */}
        <div style={{ padding: "16px 22px 20px", borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, color: "var(--text3)", marginBottom: 8 }}>
            <span>{t("pos.subtotal")}</span><span className="tabular" style={{ fontWeight: 600, color: "var(--text2)" }}>{fmt(subtotal)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, color: "var(--text3)", marginBottom: 14 }}>
            <span>{t("pos.discount")}</span><span className="tabular" style={{ fontWeight: 600, color: "var(--text2)" }}>{fmt(0)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", padding: "14px 16px", borderRadius: 13, background: "var(--surface-accent)", marginBottom: 14 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text3)", letterSpacing: "0.01em" }}>{t("pos.total")}</span>
            <span className="tabular" style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text)", lineHeight: 1 }}>{fmt(payTotal)}</span>
          </div>

          <button
            disabled={payDisabled}
            onClick={() => { if (!payDisabled) { setModal(true); setPaid(null); } }}
            style={{ width: "100%", height: 60, border: "none", borderRadius: 14, cursor: payDisabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 17, fontWeight: 700, letterSpacing: "0.01em", color: "#fff", background: payDisabled ? "#c9ccd8" : A, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, boxShadow: payDisabled ? "none" : "0 10px 26px rgba(109,93,211,0.38)" }}
          >
            <CheckCircle size={22} weight="bold" />{t("pos.finishBig")} <span style={{ opacity: 0.7, fontSize: 12, fontWeight: 600, marginLeft: 2 }}>F4</span>
          </button>
        </div>
      </aside>

      {/* ═══ VAZN (kg) KIRITISH — tarozi mahsuloti panelдан bosilганда ═══ */}
      {weigh && (() => {
        const kg = parseFloat((weighVal || "").replace(",", ".").replace(/[^0-9.]/g, "")) || 0;
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
              <div className="tabular" style={{ textAlign: "center", marginTop: 10, fontSize: 15, fontWeight: 700, color: kg > 0 ? "var(--text)" : "var(--faint)" }}>{fmt(Math.round(kg * weigh.base_sell_price))}</div>
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
                  <button onClick={() => printReceipt(paid)} style={{ height: 52, border: "1.5px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14.5, fontWeight: 600, color: "var(--text2)", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <Printer size={18} />{t("pos.printReceipt")}
                  </button>
                  <button onClick={() => printReceipt(paid)} title={t("pos.eReceiptTitle")} style={{ height: 52, border: "1.5px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600, color: "var(--text2)", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <DeviceMobile size={18} />{t("pos.eReceipt")}
                  </button>
                  <button onClick={newSale} style={{ gridColumn: "1 / -1", height: 52, border: "none", background: A, borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14.5, fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <Plus size={18} />{t("pos.newSale")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
