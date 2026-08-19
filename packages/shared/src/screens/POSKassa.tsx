import { useEffect, useMemo, useRef, useState } from "react";
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
import { refreshCatalog, submitSale, useOnline, usePendingCount } from "@/lib/sync";

interface Product { id: string; article_code: string; name: string; category_id: string | null; base_sell_price: number; stock: number; barcodes?: string[]; plu_code?: string | null; is_weighted?: boolean; }
interface Category { id: string; name: string }
interface CustomerRow { id: string; code: string; full_name: string; phone: string | null }

// Dizayn: to'lov usullari (NAQD/KARTA/QR/QARZ) — ikon + nom, vertikal.
const METHODS = [
  { code: "cash", label: "NAQD", Icon: Money },
  { code: "card", label: "KARTA", Icon: CreditCard },
  { code: "qr", label: "QR", Icon: QrCode },
  { code: "credit", label: "QARZ", Icon: Notebook },
];

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

export function POSKassa() {
  const [products, setProducts] = useState<Product[]>([]);
  const [cats, setCats] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(false);
  const [method, setMethod] = useState("cash");
  const [given, setGiven] = useState("");
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
  const [prefs, setPrefs] = useState(readPrefs);
  const searchRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;

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
      const inField = document.activeElement?.tagName === "INPUT";
      if (e.key === "F2") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "F4") { e.preventDefault(); if (cart.items.length) setModal(true); }
      else if (e.key === "Escape") { if (!busyRef.current) setModal(false); }
      else if ((e.key === "+" || e.key === "=") && !inField) { e.preventDefault(); bumpLast(1); }
      else if ((e.key === "-" || e.key === "_") && !inField) { e.preventDefault(); bumpLast(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line
  }, [cart.items.length]);

  useEffect(() => {
    if (modal && method === "credit" && customers.length === 0) {
      get<CustomerRow[]>("/customers").then(setCustomers).catch(() => {});
    }
  }, [modal, method, customers.length]);

  function bumpLast(d: number) {
    const items = useCart.getState().items;
    const last = items[items.length - 1];
    if (last) cart.delta(last.id, d);
  }

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products.filter(
      (p) =>
        (activeCat === "all" || p.category_id === activeCat) &&
        (!q || p.name.toLowerCase().includes(q) || p.article_code.toLowerCase().includes(q))
    );
  }, [products, activeCat, query]);

  const subtotal = cart.subtotal();
  // Naqd: bo'sh qoldirilsa "aniq summa berildi" deb hisoblanadi
  const givenRaw = parseInt(given.replace(/\D/g, ""), 10) || 0;
  const givenN = given.trim() === "" ? subtotal : givenRaw;
  const change = givenN - subtotal;
  const enough = givenN >= subtotal;
  const quickCash = [subtotal, Math.ceil(subtotal / 1000) * 1000, Math.ceil(subtotal / 5000) * 5000, Math.ceil(subtotal / 10000) * 10000].filter((v, i, a) => v > 0 && a.indexOf(v) === i).slice(0, 4);

  // Method almashsa yoki modal yopilsa — QR holatini tozalaymiz (yangi summa/rejim uchun)
  useEffect(() => { resetQr(); /* eslint-disable-next-line */ }, [method, modal]);

  // XPAY QR: modal ochilib QR tanlanganda BIR MARTA yaratamiz (qrStat dep emas -> o'zini bekor qilmaydi)
  useEffect(() => {
    const active = modal && method === "qr" && prefs.qrMode === "xpay" && !paid;
    if (!active || qrGenRef.current) return;
    qrGenRef.current = true;
    setQrStat("loading"); setQrErr(""); qrDoneRef.current = false;
    post<{ txn_id: string; qr_url: string }>("/payments/qr", { amount: subtotal, comment: prefs.storeName })
      .then((r) => { setQrTxn(r.txn_id); setQrUrl(r.qr_url); setQrImgOk(true); setQrStat("waiting"); })
      .catch((e: any) => {
        const msg = String(e?.message || "");
        setQrStat("error");
        setQrErr(msg.includes("XPAY sozlanmagan") ? t("pos.errXpayDisabled") : (msg || t("pos.qrGenFail")));
      });
    // eslint-disable-next-line
  }, [modal, method, prefs.qrMode, paid]);

  // Alohida polling effekt — QR "waiting" bo'lgach holatni so'raymiz
  useEffect(() => {
    const active = modal && method === "qr" && prefs.qrMode === "xpay" && !paid;
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
  }, [modal, method, prefs.qrMode, qrStat, qrTxn, paid]);

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
        cart.add({ id: wp.id, name: wp.name, price: wp.base_sell_price, article: wp.article_code, qty: grams / 1000 });
        setQuery("");
        return;
      }
    }
    const exact = products.find((p) => (p.barcodes || []).includes(term));
    const hit = exact || shown[0];
    if (hit) {
      cart.add({ id: hit.id, name: hit.name, price: hit.base_sell_price, article: hit.article_code });
      setQuery("");
    }
  }

  async function finish() {
    setBusy(true);
    setErr("");
    try {
      let custId = customerId;
      let custName = "";
      if (method === "credit") {
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
      const r = await submitSale({
        items: cart.items.map((i) => ({ product_id: i.id, qty: i.qty })),
        payment_method: method,
        given_amount: method === "cash" ? givenN : null,
        customer_id: method === "credit" ? custId : undefined,
        client_uuid: crypto.randomUUID(),
      });
      const mLabel = method === "cash" ? t("pay.cash") : method === "card" ? t("pay.card") : method === "qr" ? t("pos.qrPay") : t("pay.credit");
      setPaidSummary(method === "credit" ? `${fmt(subtotal)} · ${mLabel} · ${custName}` : `${fmt(subtotal)} · ${mLabel}`);
      setPaid({
        receipt_no: r.offline ? "OFFLINE" : r.receipt_no || "—",
        offline: r.offline,
        uid: r.uid,
        store: prefs.storeName,
        branch: prefs.branchName,
        cashier: employee?.full_name || t("pos.cashier"),
        items: cart.items.map((i) => ({ name: i.name, qty: i.qty, price: i.price, line: i.qty * i.price })),
        total: subtotal,
        method,
        given: givenN,
        change: Math.max(change, 0),
        date: new Date().toLocaleString("ru-RU"),
      });
      cart.clear(); // savat darhol tozalanadi — modal yopilsa ham qayta sotib bo'lmaydi
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  function newSale() {
    cart.clear();
    setModal(false);
    setPaid(null);
    setGiven("");
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
  const methods = METHODS.filter(
    (m) => m.code === "cash" || (m.code === "card" && prefs.karta) || (m.code === "qr" && prefs.qr) || (m.code === "credit" && prefs.qarz)
  );
  useEffect(() => {
    if (!methods.some((m) => m.code === method)) setMethod("cash");
    // eslint-disable-next-line
  }, [prefs.karta, prefs.qr, prefs.qarz]);

  // To'lov usullari tugmalari (savat panelida — vertikal; modalda — gorizontal)
  const methodBtn = (m: (typeof METHODS)[number], horizontal: boolean) => {
    const on = method === m.code;
    return (
      <button
        key={m.code}
        onClick={() => setMethod(m.code)}
        style={horizontal
          ? { flex: 1, minWidth: 92, height: 48, borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, border: `1.5px solid ${on ? A : "var(--border)"}`, background: on ? ASOFT : "var(--card)", color: on ? AT : "var(--muted)" }
          : { flex: 1, minWidth: 78, height: 52, borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3, border: `1.5px solid ${on ? A : "var(--border)"}`, background: on ? ASOFT : "var(--card)", color: on ? AT : "var(--muted)" }}
      >
        <m.Icon size={horizontal ? 18 : 19} />
        <span style={{ textTransform: "uppercase" }}>{t("pay." + m.code)}</span>
      </button>
    );
  };

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
                <button key={p.id} onClick={() => cart.add({ id: p.id, name: p.name, price: p.base_sell_price, article: p.article_code })}
                  style={{ textAlign: "left", cursor: "pointer", padding: 14, borderRadius: 14, background: "var(--card)", border: `1.5px solid ${qty > 0 ? A : "var(--border)"}`, boxShadow: "0 1px 2px rgba(10,12,20,0.04)", display: "flex", flexDirection: "column", gap: 11, position: "relative", font: "inherit", color: "var(--text)" }}>
                  {qty > 0 && (
                    <span style={{ position: "absolute", top: 10, right: 10, minWidth: 22, height: 22, padding: "0 6px", borderRadius: 11, background: A, color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{qty}</span>
                  )}
                  <div style={{ width: "100%", aspectRatio: "1.5", borderRadius: 10, background: qty > 0 ? ASOFT : "var(--surface)", display: "flex", alignItems: "center", justifyContent: "center", color: qty > 0 ? AT : "var(--faint)", fontSize: 28, fontWeight: 700, letterSpacing: "-0.03em" }}>{p.name.charAt(0).toUpperCase()}</div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.25, letterSpacing: "-0.01em" }}>{p.name}</div>
                    <div className="tabular" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>{p.article_code}</div>
                    <div style={{ fontSize: 11.5, color: low ? "var(--danger)" : "var(--muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
                      <Package size={12} />{p.stock} {t("pos.unit")}{low ? ` · ${t("pos.low")}` : ""}
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 22px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: "-0.02em" }}>{t("pos.cart")}</div>
            <span style={{ fontSize: 12, fontWeight: 600, color: A, background: ASOFT, padding: "2px 9px", borderRadius: 12 }}>{cart.count()}</span>
          </div>
          <button onClick={cart.clear} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", fontSize: 12.5, display: "flex", alignItems: "center", gap: 5, fontWeight: 500, font: "inherit" }}>
            <Trash size={15} />{t("pos.clearCart")}
          </button>
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
                      <div style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-0.01em" }}>{it.name}</div>
                      <button onClick={() => cart.remove(it.id)} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", padding: 0, lineHeight: 1 }}>
                        <X size={15} />
                      </button>
                    </div>
                    {it.article && <div className="tabular" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>{it.article}</div>}
                    <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{it.qty} × {fmt(it.price)}</div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 9 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 11, padding: 3 }}>
                        <button onClick={() => cart.delta(it.id, -1)} style={{ width: 38, height: 38, border: "none", background: "var(--surface)", cursor: "pointer", color: "var(--text3)", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Minus size={20} />
                        </button>
                        <span className="tabular" style={{ minWidth: 44, textAlign: "center", fontSize: 16, fontWeight: 700 }}>{it.qty}</span>
                        <button onClick={() => cart.delta(it.id, 1)} style={{ width: 38, height: 38, border: "none", background: ASOFT, cursor: "pointer", color: AT, borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center" }}>
                          <Plus size={20} />
                        </button>
                      </div>
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
            <span className="tabular" style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text)", lineHeight: 1 }}>{fmt(subtotal)}</span>
          </div>

          <div style={{ display: "flex", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
            {methods.map((m) => methodBtn(m, false))}
          </div>

          <button
            disabled={payDisabled}
            onClick={() => { if (!payDisabled) { setModal(true); setPaid(null); setGiven(""); } }}
            style={{ width: "100%", height: 60, border: "none", borderRadius: 14, cursor: payDisabled ? "not-allowed" : "pointer", font: "inherit", fontSize: 17, fontWeight: 700, letterSpacing: "0.01em", color: "#fff", background: payDisabled ? "#c9ccd8" : A, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, boxShadow: payDisabled ? "none" : "0 10px 26px rgba(109,93,211,0.38)" }}
          >
            <CheckCircle size={22} weight="bold" />{t("pos.finishBig")} <span style={{ opacity: 0.7, fontSize: 12, fontWeight: 600, marginLeft: 2 }}>F4</span>
          </button>
        </div>
      </aside>

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
                  <div className="tabular" style={{ fontSize: 44, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 4 }}>{fmt(subtotal)}</div>
                </div>

                <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
                  {methods.map((m) => methodBtn(m, true))}
                </div>

                {method === "cash" && (
                  <div>
                    <label style={{ display: "block", fontSize: 12.5, color: "var(--text3)", fontWeight: 600, marginBottom: 6 }}>{t("pay.given")}</label>
                    <input value={given} onChange={(e) => setGiven(e.target.value.replace(/\D/g, ""))} placeholder="0" inputMode="numeric"
                      style={{ width: "100%", height: 52, padding: "0 16px", border: "1.5px solid var(--border-input)", borderRadius: 12, font: "inherit", fontSize: 22, fontWeight: 700, color: "var(--text)", background: "var(--card)", outline: "none", marginBottom: 10 }} />
                    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                      {quickCash.map((v) => (
                        <button key={v} onClick={() => setGiven(String(v))} style={{ flex: 1, height: 36, border: "1px solid var(--border)", background: "var(--surface)", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, color: "var(--text3)" }}>{fmt(v)}</button>
                      ))}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", borderRadius: 12, background: enough ? "var(--ok-soft)" : "var(--danger-soft)", marginBottom: 20 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text3)" }}>{t("pay.change")}</span>
                      <span className="tabular" style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em", color: enough ? "var(--ok)" : "var(--danger)" }}>{fmt(Math.max(change, 0))}</span>
                    </div>
                  </div>
                )}

                {method === "card" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 13, padding: 16, borderRadius: 12, background: "var(--surface)", marginBottom: 20 }}>
                    <div style={{ width: 46, height: 46, flex: "none", borderRadius: 12, background: ASOFT, color: AT, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <CreditCard size={23} />
                    </div>
                    <div>
                      <div style={{ fontSize: 14.5, fontWeight: 600 }}>{t("pos.cardTitle")}</div>
                      <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 1 }}>{t("pos.cardHint")}</div>
                    </div>
                  </div>
                )}

                {method === "qr" && prefs.qrMode !== "xpay" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 13, padding: 16, borderRadius: 12, background: "var(--surface)", marginBottom: 20 }}>
                    <div style={{ width: 46, height: 46, flex: "none", borderRadius: 12, background: ASOFT, color: AT, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <QrCode size={23} />
                    </div>
                    <div>
                      <div style={{ fontSize: 14.5, fontWeight: 600 }}>{t("pos.qrTitle")}</div>
                      <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 1 }}>{t("pos.qrManualHint")}</div>
                    </div>
                  </div>
                )}

                {method === "qr" && prefs.qrMode === "xpay" && (
                  <div style={{ marginBottom: 20, padding: "20px 16px", borderRadius: 14, background: "var(--surface)", textAlign: "center" }}>
                    {qrStat === "loading" && (
                      <div style={{ padding: "40px 0", color: "var(--muted)", fontSize: 14, fontWeight: 500 }}>{t("pos.qrPreparing")}</div>
                    )}
                    {qrStat === "error" && (
                      <div style={{ padding: "8px 0" }}>
                        <div style={{ color: "var(--danger)", fontSize: 13.5, lineHeight: 1.5, marginBottom: 14 }}>{qrErr}</div>
                        <button onClick={resetQr} style={{ height: 42, padding: "0 20px", border: "1px solid var(--border-input)", background: "var(--card)", borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, color: "var(--text2)" }}>{t("common.retry")}</button>
                      </div>
                    )}
                    {(qrStat === "waiting" || qrStat === "done") && (
                      <>
                        <div style={{ width: 190, height: 190, margin: "0 auto 14px", borderRadius: 14, background: "#fff", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
                          {qrUrl && qrImgOk ? (
                            <img src={qrUrl} alt="QR" onError={() => setQrImgOk(false)} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
                          ) : (
                            <QrCode size={120} color="#1c1f2b" />
                          )}
                        </div>
                        <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 8 }}>{t("pos.qrScan")}</div>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 20, background: qrStat === "done" ? "var(--ok-soft)" : "var(--warn-soft)", color: qrStat === "done" ? "var(--ok)" : "var(--warn)", fontSize: 13, fontWeight: 600 }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: qrStat === "done" ? "var(--ok)" : "var(--warn)" }} />
                          {qrStat === "done" ? t("pos.qrAccepted") : t("pos.qrWaiting")}
                        </div>
                        {!qrImgOk && qrUrl && (
                          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 10, wordBreak: "break-all" }}>{qrUrl}</div>
                        )}
                      </>
                    )}
                  </div>
                )}

                {method === "credit" && (
                  <div style={{ marginBottom: 20 }}>
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
                        <div style={{ maxHeight: 180, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
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
                      <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{t("pos.creditNote", { sum: fmt(subtotal) })}</div>
                    </div>
                  </div>
                )}

                {err && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 12 }}>{err}</div>}

                {!(method === "qr" && prefs.qrMode === "xpay") && (
                  <button
                    onClick={finish}
                    disabled={busy || (method === "credit" && creditMode === "existing" && !customerId) || (method === "cash" && givenRaw > 0 && !enough)}
                    style={{ width: "100%", height: 56, border: "none", borderRadius: 13, cursor: "pointer", font: "inherit", fontSize: 16, fontWeight: 700, color: "#fff", background: busy || (method === "credit" && creditMode === "existing" && !customerId) || (method === "cash" && givenRaw > 0 && !enough) ? "#c9ccd8" : A, display: "flex", alignItems: "center", justifyContent: "center", gap: 9, boxShadow: busy ? "none" : "0 8px 22px rgba(109,93,211,0.35)" }}
                  >
                    <Check size={20} weight="bold" />{busy ? "..." : method === "credit" ? t("pay.creditWrite") : method === "qr" ? t("pay.confirm") : t("pay.finish")}
                  </button>
                )}
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
