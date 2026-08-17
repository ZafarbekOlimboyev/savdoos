import { useEffect, useMemo, useRef, useState } from "react";
import { get } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useCart } from "@/store/cart";
import { useAuth } from "@/store/auth";
import { CACHE, cacheGet } from "@/lib/offline";
import { printReceipt, type ReceiptData } from "@/lib/receipt";
import { refreshCatalog, submitSale, useOnline, usePendingCount } from "@/lib/sync";

interface Product { id: string; article_code: string; name: string; category_id: string | null; base_sell_price: number; stock: number; barcodes?: string[]; }
interface Category { id: string; name: string }

const METHODS = [
  { code: "cash", label: "NAQD", icon: "💵" },
  { code: "card", label: "KARTA", icon: "💳" },
  { code: "qr", label: "QR", icon: "🔲" },
  { code: "credit", label: "QARZ", icon: "📒" },
];

function posBars(uid: string) {
  const d = (uid || "").replace(/\D/g, "");
  const out: { w: string; bg: string }[] = [{ w: "2px", bg: "#1c1f2b" }, { w: "2px", bg: "transparent" }];
  for (let i = 0; i < d.length; i++) {
    const n = +d[i];
    out.push({ w: 1 + (n % 3) + "px", bg: "#1c1f2b" }, { w: 1 + ((n + i) % 3) + "px", bg: "transparent" }, { w: 1 + ((n * 3 + i) % 2) + "px", bg: "#1c1f2b" }, { w: "1px", bg: "transparent" });
  }
  out.push({ w: "2px", bg: "#1c1f2b" });
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
  const [customers, setCustomers] = useState<{ id: string; full_name: string; phone: string | null }[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [custQuery, setCustQuery] = useState("");
  const [paid, setPaid] = useState<ReceiptData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const cart = useCart();
  const employee = useAuth((s) => s.employee);
  const online = useOnline();
  const pending = usePendingCount();

  function loadFromCache() {
    setProducts(cacheGet<Product[]>(CACHE.products, []));
    setCats(cacheGet<Category[]>(CACHE.cats, []));
  }
  async function load() {
    loadFromCache();                 // darhol (offline ham ishlaydi)
    const ok = await refreshCatalog();
    if (ok) loadFromCache();         // onlayn bo'lsa yangilangan keshni o'qiymiz
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F2") { e.preventDefault(); searchRef.current?.focus(); }
      else if (e.key === "F4") { e.preventDefault(); if (cart.items.length) setModal(true); }
      else if (e.key === "Escape") setModal(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cart.items.length]);

  useEffect(() => {
    if (modal && method === "credit" && customers.length === 0) {
      get<{ id: string; full_name: string; phone: string | null }[]>("/customers").then(setCustomers).catch(() => {});
    }
  }, [modal, method, customers.length]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products.filter(
      (p) =>
        (activeCat === "all" || p.category_id === activeCat) &&
        (!q || p.name.toLowerCase().includes(q) || p.article_code.includes(q))
    );
  }, [products, activeCat, query]);

  const subtotal = cart.subtotal();
  const givenN = parseInt(given.replace(/\D/g, ""), 10) || 0;
  const change = givenN - subtotal;
  const quickCash = [subtotal, Math.ceil(subtotal / 1000) * 1000, Math.ceil(subtotal / 5000) * 5000, Math.ceil(subtotal / 10000) * 10000].filter((v, i, a) => v > 0 && a.indexOf(v) === i).slice(0, 4);

  function onScan(e: React.KeyboardEvent) {
    if (e.key !== "Enter") return;
    const term = query.trim();
    if (!term) return;
    const exact = products.find((p) => (p.barcodes || []).includes(term));
    const hit = exact || shown[0];
    if (hit) {
      cart.add({ id: hit.id, name: hit.name, price: hit.base_sell_price });
      setQuery("");
    }
  }

  async function finish() {
    setBusy(true);
    setErr("");
    try {
      const r = await submitSale({
        items: cart.items.map((i) => ({ product_id: i.id, qty: i.qty })),
        payment_method: method,
        given_amount: method === "cash" ? givenN : null,
        customer_id: method === "credit" ? customerId : undefined,
        client_uuid: crypto.randomUUID(),
      });
      setPaid({
        receipt_no: r.offline ? "OFFLINE" : r.receipt_no || "—",
        offline: r.offline,
        uid: r.uid,
        store: "Oltin Do'kon",
        branch: "Chilonzor filiali",
        cashier: employee?.full_name || "Kassir",
        items: cart.items.map((i) => ({ name: i.name, qty: i.qty, price: i.price, line: i.qty * i.price })),
        total: subtotal,
        method,
        given: givenN,
        change: Math.max(change, 0),
        date: new Date().toLocaleString("ru-RU"),
      });
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
    setMethod("cash");
    load();
  }

  const cartMap: Record<string, number> = {};
  cart.items.forEach((i) => (cartMap[i.id] = i.qty));

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex" }}>
      <main className="main">
        <header className="topbar" style={{ gap: 16 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Mahsulot nomi, artikul yoki barcode...   (F2 · Enter — qo'shish)"
              onKeyDown={onScan}
              style={{ width: "100%", height: 46, padding: "0 16px", border: "1px solid #e2e4ee", borderRadius: 11, background: "#f7f8fb", fontSize: 14.5, outline: "none" }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 12px", borderRadius: 10, background: online ? "#e9f7ef" : "#fef3e2", color: online ? "#12915a" : "#b8730c", fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: online ? "#17b26a" : "#e08a12" }} />
            {online ? "Onlayn" : "Oflayn"}{pending > 0 ? ` · ${pending} kutmoqda` : ""}
          </div>
        </header>

        {err && <div style={{ padding: "10px 24px", color: "var(--red)" }}>Xatolik: {err}</div>}

        <div style={{ padding: "16px 24px 4px", display: "flex", gap: 9, flexWrap: "wrap" }}>
          {[{ id: "all", name: "Barchasi" }, ...cats].map((c) => {
            const on = activeCat === c.id;
            return (
              <button key={c.id} onClick={() => setActiveCat(c.id)}
                style={{ height: 38, padding: "0 17px", borderRadius: 20, fontSize: 13.5, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "#e6e8f0"}`, background: on ? "var(--accent)" : "#fff", color: on ? "#fff" : "#5b6072" }}>
                {c.name}
              </button>
            );
          })}
        </div>

        <div className="scroll" style={{ flex: 1, padding: "16px 24px 24px" }}>
          {products.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
              Katalog bo'sh — server bilan bir marta ulaning (keyin oflayn ishlaydi).
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            {shown.map((p) => {
              const qty = cartMap[p.id] || 0;
              const low = p.stock <= 5;
              return (
                <button key={p.id} onClick={() => cart.add({ id: p.id, name: p.name, price: p.base_sell_price })}
                  style={{ textAlign: "left", cursor: "pointer", padding: 14, borderRadius: 14, background: "#fff", border: `1.5px solid ${qty > 0 ? "var(--accent)" : "#eef0f5"}`, display: "flex", flexDirection: "column", gap: 8, position: "relative" }}>
                  {qty > 0 && (
                    <span style={{ position: "absolute", top: 10, right: 10, minWidth: 22, height: 22, padding: "0 6px", borderRadius: 11, background: "var(--accent)", color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{qty}</span>
                  )}
                  <div style={{ width: "100%", aspectRatio: "1.5", borderRadius: 10, background: qty > 0 ? "var(--accent-soft)" : "#f4f5fa", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, fontWeight: 700, color: qty > 0 ? "var(--accent-ink)" : "#9096ab" }}>{p.name.charAt(0)}</div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.25 }}>{p.name}</div>
                    <div style={{ fontSize: 11.5, color: low ? "var(--red)" : "var(--muted)", marginTop: 3 }}>{p.stock} dona{low ? " · kam" : ""}</div>
                  </div>
                  <div className="tabular" style={{ fontSize: 18, fontWeight: 700 }}>{fmt(p.base_sell_price)}</div>
                </button>
              );
            })}
          </div>
          {products.length > 0 && shown.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Mahsulot topilmadi</div>}
        </div>
      </main>

      <aside style={{ width: 398, flex: "none", background: "#fff", borderLeft: "1px solid var(--line)", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 22px 14px" }}>
          <div style={{ fontSize: 19, fontWeight: 700 }}>Savat <span style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)", background: "var(--accent-soft)", padding: "2px 9px", borderRadius: 12 }}>{cart.count()}</span></div>
          <button onClick={cart.clear} style={{ border: "none", background: "none", cursor: "pointer", color: "#a9aec0", fontSize: 12.5, fontWeight: 500 }}>🗑 Tozalash</button>
        </div>

        <div className="scroll" style={{ flex: 1, padding: "0 22px" }}>
          {cart.items.length === 0 ? (
            <div style={{ height: "100%", minHeight: 300, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#b3b8c9" }}>
              <div style={{ fontSize: 40 }}>🛒</div>
              <div style={{ fontSize: 14.5, fontWeight: 600, color: "#8b91a4", marginTop: 10 }}>Savat bo'sh</div>
              <div style={{ fontSize: 12.5, marginTop: 4 }}>Mahsulotni tanlang</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, paddingBottom: 8 }}>
              {cart.items.map((it) => (
                <div key={it.id} style={{ display: "flex", gap: 12, padding: 12, borderRadius: 12, background: "#f7f8fb" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600 }}>{it.name}</div>
                      <button onClick={() => cart.remove(it.id)} style={{ border: "none", background: "none", cursor: "pointer", color: "#c0c4d2" }}>✕</button>
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{it.qty} × {fmt(it.price)}</div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 9 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 4, background: "#fff", border: "1px solid var(--line)", borderRadius: 11, padding: 3 }}>
                        <button onClick={() => cart.delta(it.id, -1)} style={{ width: 34, height: 34, border: "none", background: "#f2f3f7", cursor: "pointer", borderRadius: 9, fontSize: 18 }}>−</button>
                        <span className="tabular" style={{ minWidth: 40, textAlign: "center", fontSize: 15, fontWeight: 700 }}>{it.qty}</span>
                        <button onClick={() => cart.delta(it.id, 1)} style={{ width: 34, height: 34, border: "none", background: "var(--accent-soft)", color: "var(--accent-ink)", cursor: "pointer", borderRadius: 9, fontSize: 18 }}>+</button>
                      </div>
                      <div className="tabular" style={{ fontSize: 15, fontWeight: 700 }}>{fmt(it.qty * it.price)}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ padding: "16px 22px 20px", borderTop: "1px solid #eef0f5" }}>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", padding: "14px 16px", borderRadius: 13, background: "#f4f3fc", marginBottom: 14 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: "#5b6072" }}>JAMI</span>
            <span className="tabular" style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.03em" }}>{fmt(subtotal)}</span>
          </div>
          <button className="btn btn-primary" disabled={cart.items.length === 0} onClick={() => setModal(true)} style={{ width: "100%", height: 58, fontSize: 17 }}>
            ✓ TO'LOVNI YAKUNLASH <span style={{ opacity: 0.7, fontSize: 12, marginLeft: 4 }}>F4</span>
          </button>
        </div>
      </aside>

      {modal && (
        <div onClick={() => !busy && setModal(false)} style={{ position: "fixed", inset: 0, background: "rgba(28,31,43,0.42)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: 428, background: "#fff", borderRadius: 20, padding: 26 }}>
            {!paid ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                  <div style={{ fontSize: 21, fontWeight: 700 }}>To'lov</div>
                  <button onClick={() => setModal(false)} style={{ border: "none", background: "#f5f6fa", borderRadius: 9, width: 34, height: 34, cursor: "pointer" }}>✕</button>
                </div>
                <div style={{ textAlign: "center", padding: "18px 0", background: "#f4f3fc", borderRadius: 14, marginBottom: 20 }}>
                  <div style={{ fontSize: 12.5, color: "#8b91a4", fontWeight: 600, textTransform: "uppercase" }}>To'lov summasi</div>
                  <div className="tabular" style={{ fontSize: 40, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 4 }}>{fmt(subtotal)}</div>
                </div>
                <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
                  {METHODS.map((m) => {
                    const on = method === m.code;
                    return (
                      <button key={m.code} onClick={() => setMethod(m.code)}
                        style={{ flex: 1, minWidth: 88, height: 52, borderRadius: 11, cursor: "pointer", fontSize: 13, fontWeight: 600, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3, border: `1.5px solid ${on ? "var(--accent)" : "#e6e8f0"}`, background: on ? "var(--accent-soft)" : "#fff", color: on ? "var(--accent-ink)" : "#8b91a4" }}>
                        <span style={{ fontSize: 18 }}>{m.icon}</span>{m.label}
                      </button>
                    );
                  })}
                </div>
                {method === "credit" && (
                  <div style={{ marginBottom: 18 }}>
                    <input value={custQuery} onChange={(e) => setCustQuery(e.target.value)} placeholder="Mijozni qidirish (ism/telefon)..."
                      style={{ width: "100%", height: 44, padding: "0 14px", border: "1.5px solid #e2e4ee", borderRadius: 11, fontSize: 13.5, outline: "none", boxSizing: "border-box" }} />
                    <div style={{ maxHeight: 170, overflowY: "auto", marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                      {customers.filter((c) => !custQuery || c.full_name.toLowerCase().includes(custQuery.toLowerCase()) || (c.phone || "").includes(custQuery)).map((cu) => {
                        const on = customerId === cu.id;
                        return (
                          <button key={cu.id} onClick={() => setCustomerId(cu.id)}
                            style={{ textAlign: "left", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", borderRadius: 11, border: `1.5px solid ${on ? "var(--accent)" : "#eef0f5"}`, background: on ? "var(--accent-soft)" : "#fff" }}>
                            <span style={{ fontSize: 13.5, fontWeight: 600 }}>{cu.full_name}</span>
                            <span style={{ fontSize: 11.5, color: "#9aa0b4" }}>{cu.phone}</span>
                          </button>
                        );
                      })}
                      {customers.length === 0 && <div style={{ padding: 12, textAlign: "center", color: "#9aa0b4", fontSize: 13 }}>Mijozlar yuklanmoqda yoki yo'q</div>}
                    </div>
                    <div style={{ display: "flex", gap: 8, padding: "12px 14px", borderRadius: 11, background: "#fef3e2", color: "#8a5a12", marginTop: 12, fontSize: 12.5, lineHeight: 1.4 }}>
                      <span>📒</span><span>Summa <b>{fmt(subtotal)}</b> tanlangan mijozning qarz (nasiya) hisobiga yoziladi.</span>
                    </div>
                  </div>
                )}
                {method === "cash" && (
                  <div style={{ marginBottom: 18 }}>
                    <label style={{ display: "block", fontSize: 12.5, color: "#6b7183", fontWeight: 600, marginBottom: 6 }}>Berilgan summa</label>
                    <input value={given} onChange={(e) => setGiven(e.target.value.replace(/\D/g, ""))} placeholder="0" inputMode="numeric"
                      style={{ width: "100%", height: 52, padding: "0 16px", border: "1.5px solid #e2e4ee", borderRadius: 12, fontSize: 22, fontWeight: 700, outline: "none" }} />
                    <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                      {quickCash.map((v) => (
                        <button key={v} onClick={() => setGiven(String(v))} style={{ flex: 1, height: 36, border: "1px solid #e6e8f0", background: "#f7f8fb", borderRadius: 9, cursor: "pointer", fontSize: 12.5, fontWeight: 600, color: "#5b6072" }}>{fmt(v)}</button>
                      ))}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", borderRadius: 12, background: change >= 0 ? "#e9f7ef" : "#fdecec", marginTop: 10 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: "#5b6072" }}>Qaytim</span>
                      <span className="tabular" style={{ fontSize: 22, fontWeight: 800, color: change >= 0 ? "var(--green)" : "var(--red)" }}>{fmt(Math.max(change, 0))}</span>
                    </div>
                  </div>
                )}
                {err && <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 12 }}>{err}</div>}
                <button className="btn btn-primary" disabled={busy || (method === "credit" && !customerId)} onClick={finish} style={{ width: "100%", height: 56, fontSize: 16 }}>
                  {busy ? "..." : method === "credit" ? "Nasiyaga yozish" : "To'lovni yakunlash"}
                </button>
              </>
            ) : (
              <div style={{ textAlign: "center", padding: "12px 4px" }}>
                <div style={{ width: 82, height: 82, margin: "0 auto 18px", borderRadius: "50%", background: paid.offline ? "#fff8ef" : "#e9f7ef", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 44 }}>{paid.offline ? "📥" : "✅"}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{paid.offline ? "Oflayn saqlandi" : "Savdo yakunlandi"}</div>
                <div style={{ fontSize: 14, color: "#8b91a4", marginTop: 6 }}>
                  {paid.offline ? "Internetga ulanganda yuboriladi" : `Chek ${paid.receipt_no}`} · {fmt(paid.total)}
                </div>
                {!paid.offline && paid.uid && (
                  <div style={{ margin: "16px 0 2px", padding: 12, border: "1px dashed #e2e4ee", borderRadius: 12 }}>
                    <div style={{ display: "flex", alignItems: "stretch", height: 40, justifyContent: "center" }}>
                      {posBars(paid.uid).map((b, i) => <div key={i} style={{ width: b.w, background: b.bg }} />)}
                    </div>
                    <div style={{ textAlign: "center", fontSize: 11, letterSpacing: 3, color: "#5b6072", marginTop: 6 }} className="tabular">{paid.uid}</div>
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 24 }}>
                  <button className="btn btn-ghost" onClick={() => printReceipt(paid)} style={{ height: 52 }}>🖨 Chek chop etish</button>
                  <button className="btn btn-primary" onClick={newSale} style={{ height: 52 }}>+ Yangi savdo</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
