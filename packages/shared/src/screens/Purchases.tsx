import { useCallback, useEffect, useRef, useState } from "react";
import { api, get, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { newClientUuid, q3 } from "@/lib/lots";
import { translateCashError } from "@/lib/serverErrorsCash";
import { translateLotError } from "@/lib/serverErrorsLots";
import { tillName } from "@/lib/tills";
import { useAuth } from "@/store/auth";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { Confirm, useModalFocus, useNarrow } from "@/components/lotui";
import { useT } from "@/lib/i18n";
import { FullReceiving, UNITS, unitL, moneyIn, qtyIn, type Product as CatalogProduct } from "./Products";
import {
  LotReceivingEditor, emptyLot, lotIssueText, lotLineState, lotsPayload, milli,
  useBusinessDate, type LotDraft,
} from "@/components/LotReceivingEditor";

interface Purchase { id: string; doc_no: string; supplier: string; date: string; total: number; status: string; }
interface Supplier { id: string; name: string; phone: string | null; balance: number; }
interface Product {
  id: string; name: string; base_buy_price: number; base_sell_price: number; stock: number;
  barcodes?: string[];
  // Partiya bayroqlari — `/products` ularni allaqachon qaytarardi, lekin bu
  // tip ularni «ko'rmagani» uchun rasm orqali kirim kuzatuvli tovarni
  // kuzatuvsizdek yuborib, butun hujjatni 400 ga olib borardi.
  track_lots?: boolean; track_expiry?: boolean;
}
interface Category { id: string; name: string }

// Kirim qatori: mavjud mahsulot (pid) YOKI yangi nom. Mavjudni tanlasa narxlar bazadan
// avto-to'ladi; foydalanuvchi o'zgartirsa — commit'da mahsulot kartochkasi ham yangilanadi.
interface KRow {
  pid: string; name: string; qty: string; cost: string; sell: string; catId: string; open: boolean;
  aiName?: string; unit?: string; barcode: string; plu: string;
  // `null` — kuzatuvsiz qator: payload bugungidek qoladi (`lots` kaliti YO'Q).
  lots: LotDraft[] | null; lotsAuto: boolean;
}

const emptyRow = (): KRow => ({ pid: "", name: "", qty: "", cost: "", sell: "", catId: "", open: false, unit: "dona", barcode: "", plu: "", lots: null, lotsAuto: true });

export function Purchases() {
  const purchases = useGet<Purchase[]>("/purchases");
  const suppliers = useGet<Supplier[]>("/suppliers");
  const catalog = useGet<CatalogProduct[]>("/products");
  const cats = useGet<Category[]>("/categories");
  const [add, setAdd] = useState(false);
  const [photo, setPhoto] = useState(false);
  const [editSup, setEditSup] = useState<Supplier | null>(null);
  const [selSup, setSelSup] = useState<string | null>(null); // yetkazib beruvchi batafsil
  const [supPage, setSupPage] = useState(false);   // yetkazib beruvchilar to'liq sahifasi
  const [newSup, setNewSup] = useState(false);
  const [kirimId, setKirimId] = useState<string | null>(null); // kirim batafsil + tahrir
  const t = useT();

  const list = purchases.data || [];
  const sup = suppliers.data || [];
  // FAQAT musbat balanslar (do'kon QARZDOR bo'lganlari) — do'kon ortiqcha to'lagan (manfiy) ta'minotchi
  // haqiqiy qarzни NETLAB kamaytirмасин (Yetkazib beruvchilar sahifasi bilan izchil "jami qarz").
  const debt = sup.reduce((t, s) => t + Math.max(0, s.balance), 0);
  const reload = () => { purchases.reload(); suppliers.reload(); catalog.reload(); };

  // "Yangi kirim" endi Ombordagi bilan bir xil oqim (FullReceiving) — takror bo'lmasin.
  if (add) {
    return <FullReceiving cats={cats.data || []} products={catalog.data || []} suppliers={sup}
      onBack={() => setAdd(false)}
      onSaved={() => { setAdd(false); reload(); }} />;
  }
  if (selSup) {
    return <SupplierDetail id={selSup} onBack={() => { setSelSup(null); suppliers.reload(); }}
      onEdit={() => { const s = sup.find((x) => x.id === selSup); if (s) setEditSup(s); }}
      editModal={editSup ? <SupplierEdit s={editSup} onClose={() => setEditSup(null)} onDone={() => { setEditSup(null); suppliers.reload(); }} /> : null} />;
  }
  if (supPage) {
    return <SuppliersPage suppliers={sup} onBack={() => { setSupPage(false); suppliers.reload(); }}
      onOpen={(id) => setSelSup(id)} onAdd={() => setNewSup(true)}
      newSupModal={newSup ? <SupplierNew onClose={() => setNewSup(false)} onDone={() => { setNewSup(false); suppliers.reload(); }} /> : null} />;
  }
  if (kirimId) {
    return <KirimDetail id={kirimId} onBack={() => { setKirimId(null); purchases.reload(); suppliers.reload(); }} />;
  }

  return (
    <main className="main">
      <Topbar title={t("nav.xaridlar")} sub={t("purch.sub")}
        right={<div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" onClick={() => setPhoto(true)}>📷 {t("purch.photoKirim")}</button>
          <button className="btn btn-primary" onClick={() => setAdd(true)}>＋ {t("purch.newKirim")}</button>
        </div>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, marginBottom: 20 }}>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.docs")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{list.length}</div></div>
          {/* Yetkazib beruvchilar CARD — bosilsa to'liq sahifa ochiladi */}
          <div className="card" onClick={() => setSupPage(true)} title={t("purch.openSuppliers")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent-border)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}>
            <div>
              <div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.suppliers")}</div>
              <div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{sup.length}</div>
            </div>
            <span style={{ color: "var(--accent-strong)", fontSize: 22 }}>›</span>
          </div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.supplierDebt")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: "var(--red)" }} className="tabular">{fmt(debt)}</div></div>
        </div>

        {/* Xarid hujjatlari — to'liq enlik */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "18px 20px 12px", fontSize: 16, fontWeight: 700 }}>{t("purch.docs")}</div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "var(--card-alt)" }}><th style={th}>{t("purch.thDoc")}</th><th style={th}>{t("purch.thSupplier")}</th><th style={th}>{t("purch.thDate")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th><th style={th}>{t("purch.thStatus")}</th></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} onClick={() => setKirimId(p.id)} style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--card-alt)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "")}>
                  <td style={{ ...td, fontWeight: 700 }}>{p.doc_no}</td>
                  <td style={{ ...td, color: "var(--text2)" }}>{p.supplier}</td>
                  <td style={{ ...td, color: "var(--muted)" }}>{p.date}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.total)}</td>
                  <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: p.status === "debt" ? "var(--warn-soft)" : "var(--ok-soft)", color: p.status === "debt" ? "var(--warn)" : "var(--ok)" }}>{p.status === "debt" ? t("pay.credit") : t("purch.paid")}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)" }}>{t("purch.noKirim")}</div>}
        </div>
      </div>

      {photo && <PhotoKirim suppliers={sup} onClose={() => setPhoto(false)} onSaved={() => { setPhoto(false); reload(); }} />}
      {editSup && <SupplierEdit s={editSup} onClose={() => setEditSup(null)} onDone={() => { setEditSup(null); suppliers.reload(); }} />}
    </main>
  );
}

// ═══ KIRIM BATAFSIL + MAHSULOTLARNI TAHRIRLASH ═══
interface KItem {
  id: string; product_id: string; name: string; qty: number; unit_cost: number; line_total: number;
  sell_price: number; unit: string; stock: number;
  // Server qo'shadi (Phase 5C). Eski server yubormaydi -> `undefined` -> qulf YO'Q.
  track_lots?: boolean; track_expiry?: boolean;
  // Phase 5D: shu qatorning kogortalari (server hisoblaydi — pastdagi izohga qarang)
  // va QATOR darajasidagi rad etish sababi (hujjat tuzatilsa ham ayrim qator yopiq
  // bo'lishi mumkin — masalan shu mahsulotda yopilmagan partiya qarzi bor).
  lots?: KLot[];
  correctable?: boolean;
  correction_blocked_reason?: string | null;
}
/** Qabul yaratgan kogorta — `GET /purchases/{id}` dagi O'QISH ko'rinishi.
 *
 *  ⚠️  `correctable` — SERVER qarori (`lot_correction.untouched`): «bu kogortaning
 *      identifikatsiyasini hali tuzatsa bo'ladimi». UI uni `remaining == received`
 *      deb o'zi hisoblasa YOLG'ON aytardi: sotilib keyin qaytarilgan kogortada
 *      qoldiq AYNAN tiklanadi, lekin partiya chekda ALLAQACHON ishlatilgan. */
interface KLot {
  id: string; batch_no: string | null; expiry_date: string | null;
  received_qty: number; remaining_qty: number; consumed_qty: number;
  unit_cost: number; status: string; correctable: boolean;
  /** ⚠️  HUJJAT TOMONINING NARXI — `unit_cost` EMAS. `unit_cost` kogortaning O'Z
   *  tannarxi (`StockBatch.unit_cost`), `doc_unit_cost` esa shu kogorta osilgan
   *  XARID QATORINING narxi (`PurchaseItem.unit_cost`) — hujjat jami AYNAN
   *  shundan tug'ilgan. Ikkovi kirimda partiyaga ALOHIDA narx berilganda
   *  ajraladi (`lot_receiving.create_lots`: partiyaning o'z narxi qator
   *  narxidan USTUN) va avvalgi tuzatish o'rniga boshqa narxli kogorta
   *  qo'yganda ham (xarid qatorlari TEGILMAYDI).
   *
   *  Eski server yubormaydi -> `undefined` -> kogorta narxiga qaytiladi. */
  doc_unit_cost?: number;
}
interface KCorrection { id: string; at: string | null; reason: string; delta_total: number; employee: string }
/** Kassa hisobining EKRANGA chiqadigan bo'lagi — server AYNAN shu 4 maydonni beradi
 *  (`label`, `terminal_id`, `branch_id`, `status` YO'Q: §A.3 oshkorlik chegarasi). */
interface KCashAccount { id: string; type: "TILL" | "SAFE"; code: string | null; currency: string }
/** Kassa custody bloki (Phase 5E, §A.3) — SERVER QARORI, mijoz hisobi EMAS.
 *
 *  ⚠️  UI BU QARORNI QAYTA HISOBLAMAYDI. «Qaysi kassadan pul o'tadi?» savoliga
 *      javobni yozuvchi bilan AYNI funksiya beradi
 *      (`cutover_guard.preview_cash_custody`): ikki joyda ikki xil hisob
 *      operatorga «mumkin» deb ko'rsatib, server 400 berardi.
 *
 *  ⚠️  ESKI SERVER bu kalitni YUBORMAYDI (`undefined`) — o'shanda ekran hech
 *      narsa ko'rsatmaydi va hech narsa yubormaydi (Phase 5D xatti-harakati). */
interface KCashCustody {
  mode: "NOT_APPLICABLE" | "NOT_REQUIRED" | "SERVER_RESOLVED" | "OPERATOR_MUST_CHOOSE" | "BLOCKED";
  /** Barqaror kod (`serverErrorsCash.ts`) — nega yopiq yoki nega hisob so'ralmoqda. */
  reason: string | null;
  resolved: KCashAccount | null;
  options: KCashAccount[];
  /** HUJJATNING filiali (aktyorniki emas) — bo'sh ro'yxat matnida aynan u aytiladi. */
  branch: { id: string; name: string } | null;
}
interface KDetail {
  id: string; doc_no: string; supplier: string; supplier_id: string | null; date: string;
  status: string; payment: string; subtotal: number; total: number; paid_amount: number; items: KItem[];
  // Phase 5D — QO'SHIMCHA maydonlar. Eski server ularni YUBORMAYDI (`undefined`):
  // o'shanda endpoint ham yo'q, shu bois oqim UMUMAN ko'rinmaydi.
  receiving_id?: string | null;
  correctable?: boolean;
  correction_blocked_reason?: string | null;
  corrections?: KCorrection[];
  // ⚠️  ISH KUNI HUJJATNIKI. `business_date` — SERVER hisoblagan, qabul QAYSI
  //     filialga tegishli bo'lsa o'shaning kuni (`branch_id` bilan birga).
  //     Eski server yubormaydi -> `undefined` -> eski xatti-harakat.
  branch_id?: string | null;
  business_date?: string | null;
  // Phase 5E — kassa custody bloki (yuqoridagi izohga qarang).
  cash_custody?: KCashCustody;
}
interface ERow { id: string; name: string; unit: string; qty: string; cost: string; sell: string; stock: number; removed: boolean; tracked: boolean; }

function KirimDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const t = useT();
  const detail = useGet<KDetail>(`/purchases/${id}`);
  const d = detail.data;
  const [rows, setRows] = useState<ERow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // QA PR-002: tahrir uchun BARQAROR client_uuid — tranzient xato + qayta bosishda backend
  // (FOR UPDATE qulfi) reconcile'ni ikki marta qo'llamasin. Har save()'da yangi UUID (eski) EMAS.
  const editUuid = useRef<string>(crypto.randomUUID());
  // ── TUZATISH OQIMI (Phase 5D) ───────────────────────────────────────────────
  // ⚠️  RUXSAT SERVER TALABI BILAN AYNI (`require("xaridlar.edit")`). Tugmani
  //     hammaga ko'rsatish operatorga butun oynani to'ldirtirib, faqat
  //     «Yozish» bosgandan KEYIN 403 berardi.
  const perms = useAuth((s) => s.employee?.permissions);
  const canCorrect = (perms || []).includes("xaridlar.edit");
  const [corrOpen, setCorrOpen] = useState(false);
  const [corrMsg, setCorrMsg] = useState("");
  // `correctable === undefined` — ESKI SERVER: endpoint yo'q, oqim ko'rsatilmaydi.
  // `false` esa «sabab bor» degani va sabab operatorga AYTILADI.
  const corrShown = canCorrect && !!d?.receiving_id && d?.correctable === true;
  const corrBlocked = canCorrect && d?.correctable === false ? d.correction_blocked_reason : null;
  // ⚠️  TUZATILGAN HUJJATDA ESKI TAHRIR YO'LI YOPIQ. `PATCH /purchases/{id}`
  //     hujjat jamini `purchase_items` dan QAYTA hisoblaydi va tuzatishni
  //     jimgina teskari qilardi — server uni 409 bilan rad etadi. Tugmani
  //     ochiq qoldirish operatorni faqat bosgandan KEYIN xabardor qilardi
  //     (kuzatuvli qator qulfi bilan AYNI qoida).
  const docLocked = !!d?.corrections?.length;

  useEffect(() => {
    if (d) setRows(d.items.map((it) => ({ id: it.id, name: it.name, unit: it.unit, qty: String(it.qty), cost: String(it.unit_cost), sell: String(it.sell_price), stock: it.stock, removed: false, tracked: !!it.track_lots })));
  }, [d]);

  const live = rows || [];
  const total = live.filter((r) => !r.removed).reduce((s, r) => s + (+r.qty || 0) * (+r.cost || 0), 0);

  function upd(i: number, patch: Partial<ERow>) {
    setRows((rs) => (rs ? rs.map((r, j) => (j === i ? { ...r, ...patch } : r)) : rs));
  }

  async function save() {
    if (!rows) return;
    const removed = rows.filter((r) => r.removed).map((r) => r.id);
    const keep = rows.filter((r) => !r.removed);
    for (const r of keep) if (!(+r.qty > 0)) { setErr(t("purch.needQty")); return; }
    if (keep.length === 0) { if (!window.confirm(t("purch.cancelKirimConfirm"))) return; }
    setBusy(true); setErr("");
    try {
      await api(`/purchases/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          items: keep.map((r) => ({ id: r.id, qty: +r.qty, unit_cost: +r.cost, sell_price: r.sell !== "" ? +r.sell : null })),
          removed, client_uuid: editUuid.current,
        }),
      });
      onBack();
    } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); }
  }

  return (
    <main className="main">
      <Topbar title={d ? d.doc_no : "…"} sub={d ? `${d.supplier} · ${d.date}` : t("nav.xaridlar")} onBack={onBack}
        right={d ? (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
            <span style={{ fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 9, background: d.payment === "credit" ? "var(--warn-soft)" : "var(--ok-soft)", color: d.payment === "credit" ? "var(--warn)" : "var(--ok)" }}>{d.payment === "credit" ? t("pay.credit") : t("purch.paid")}</span>
            {corrShown && (
              <button className="btn btn-ghost" data-testid="kd-correct" onClick={() => setCorrOpen(true)}
                      style={{ height: 42, color: "var(--danger)" }}>{t("corr.action")}</button>
            )}
          </div>
        ) : undefined} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {!d || !rows ? <div style={{ color: "var(--muted)" }}>{t("common.loading")}</div> : (
          <div style={{ maxWidth: 900 }}>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 14 }}>{t("purch.editNote")}</div>
            {corrMsg && (
              <div role="status" data-testid="kd-corr-done"
                   style={{ padding: "11px 14px", borderRadius: 11, background: "var(--ok-soft)", color: "var(--ok)", fontSize: 12.5, fontWeight: 600, marginBottom: 14 }}>
                {corrMsg}
              </div>
            )}
            {corrBlocked && (
              // ⚠️  SABAB SERVERDAN KELADI va lug'at orqali operator tiliga
              //     o'giriladi: «tugma yo'q» degan jim holat operatorni
              //     qo'llab-quvvatlashga qo'ng'iroq qilishga majburlardi.
              <div role="note" data-testid="kd-correct-blocked"
                   style={{ padding: "11px 14px", borderRadius: 11, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12.5, fontWeight: 600, marginBottom: 14 }}>
                {translateLotError(corrBlocked) ?? corrBlocked}
              </div>
            )}
            {docLocked && (
              <div role="note" data-testid="kd-doc-locked"
                   style={{ padding: "11px 14px", borderRadius: 11, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12.5, fontWeight: 600, marginBottom: 14 }}>
                {t("corr.docLocked")}
              </div>
            )}
            {!!d.corrections?.length && (
              <div className="card" data-testid="kd-corrections" style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{t("corr.history")}</div>
                {d.corrections.map((c) => (
                  <div key={c.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12.5, color: "var(--text3)", padding: "4px 0" }}>
                    <span className="lot-wrap">{c.reason} · {c.employee}</span>
                    <span className="tabular" style={{ flex: "none", fontWeight: 700, color: c.delta_total < 0 ? "var(--danger)" : "var(--ok)" }}>
                      {c.delta_total > 0 ? "+" : ""}{fmt(c.delta_total)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {live.some((r) => r.tracked) && (
              // ⚠️  SERVER BARIBIR RAD ETADI (409): miqdor/o'chirish darvozasi va
              //     tannarx darvozasi. Tugmani ochiq qoldirish operatorni faqat
              //     bosgandan KEYIN xabardor qilardi.
              <div role="note" data-testid="kd-tracked-note"
                   style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "11px 14px", borderRadius: 11, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12.5, fontWeight: 600, marginBottom: 14 }}>
                {t("recv.trackedLockedEdit")}
              </div>
            )}
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr style={{ background: "var(--card-alt)" }}>
                  <th style={th}>{t("sales.thProduct")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("purch.stock")}</th>
                  <th style={{ ...th, textAlign: "right", width: 100 }}>{t("recv.qty")}</th>
                  <th style={{ ...th, textAlign: "right", width: 120 }}>{t("prod.buyPrice")}</th>
                  <th style={{ ...th, textAlign: "right", width: 120 }}>{t("prod.sellPrice")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th>
                  <th style={{ ...th, width: 44 }}></th>
                </tr></thead>
                <tbody>
                  {live.map((r, i) => (
                    <tr key={r.id} style={{ opacity: r.removed ? 0.42 : 1 }}>
                      <td style={{ ...td, fontWeight: 600, textDecoration: r.removed ? "line-through" : "none" }}>{r.name} <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: 12 }}>{unitL(t, r.unit)}</span></td>
                      <td style={{ ...td, textAlign: "right", color: "var(--muted)" }} className="tabular">{r.stock}</td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input value={r.qty} data-testid={`kd-qty-${i}`} disabled={r.removed || r.tracked || docLocked} onChange={(e) => upd(i, { qty: qtyIn(e.target.value) })} style={{ ...inputStyle, height: 38, textAlign: "right", width: 90 }} />
                      </td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input value={r.cost} data-testid={`kd-cost-${i}`} disabled={r.removed || r.tracked || docLocked} onChange={(e) => upd(i, { cost: moneyIn(e.target.value) })} style={{ ...inputStyle, height: 38, textAlign: "right", width: 110 }} />
                      </td>
                      <td style={{ ...td, textAlign: "right" }}>
                        <input value={r.sell} disabled={r.removed || docLocked} onChange={(e) => upd(i, { sell: moneyIn(e.target.value) })} style={{ ...inputStyle, height: 38, textAlign: "right", width: 110 }} />
                      </td>
                      <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt((+r.qty || 0) * (+r.cost || 0))}</td>
                      <td style={{ ...td, textAlign: "center" }}>
                        <button className="btn btn-ghost" title={t("purch.remove")} data-testid={`kd-remove-${i}`} disabled={r.tracked || docLocked} onClick={() => upd(i, { removed: !r.removed })} style={{ height: 34, padding: "0 10px", fontSize: 16, color: r.removed ? "var(--accent-strong)" : "var(--danger)", opacity: r.tracked ? 0.4 : 1 }}>{r.removed ? "↺" : "×"}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18, gap: 16 }}>
              <div style={{ fontSize: 15 }}>{t("sales.thSum")}: <b className="tabular" style={{ fontSize: 20 }}>{fmt(total)}</b></div>
              <div style={{ display: "flex", gap: 10 }}>
                <button className="btn btn-ghost" onClick={onBack}>{t("common.cancel")}</button>
                <button className="btn btn-primary" disabled={busy || docLocked} onClick={save}>{busy ? "..." : t("purch.saveChanges")}</button>
              </div>
            </div>
            {err && <div style={{ color: "var(--danger)", fontSize: 13.5, marginTop: 12, textAlign: "right" }}>{err}</div>}
          </div>
        )}
      </div>
      {corrOpen && d && (
        <KirimTuzatish d={d} onClose={() => setCorrOpen(false)}
          onDone={(res) => {
            setCorrOpen(false);
            // ⚠️  BEKOR QILINGAN hujjat keyingi `GET` da 404 beradi — shu ekranda
            //     qolish operatorga bo'sh «yuklanmadi» holatini ko'rsatardi.
            if (res.cancelled) { onBack(); return; }
            setCorrMsg(res.duplicate ? t("lot.alreadyApplied") : t("corr.done"));
            detail.reload();
          }}
          onStale={() => detail.reload()} />
      )}
    </main>
  );
}

// ═══ QABULNI TUZATISH (Phase 5D) — TESKARI YOZUV + O'RNIGA QO'YISH ═══════════
//
// ⚠️  BU QATOR TAHRIRI EMAS. Xarid qatorlari (`purchase_items`) TEGILMAYDI: ular
//     aslida nima yozilganining yozuvi. Operator kogortadan miqdorni TESKARI
//     qiladi va kerak bo'lsa o'rniga YANGI kogorta e'lon qiladi — ikkalasi ham
//     o'zgarmas hodisa. Shu bois bu yerda «saqlash» emas, «yozish» deyiladi.
//
// ⚠️  QAROR SERVERDA. Qaysi kogortaning identifikatsiyasi hali tuzatilishi
//     mumkinligini (`correctable`) va yopilmagan partiya qarzi borligini server
//     hisoblaydi; UI ularni QAYTA hisoblamaydi — ikki joyda ikki xil hisob
//     operatorga «mumkin» deb ko'rsatib, server 409 berardi.
interface CorrRes {
  ok: boolean; correction_id: string; cancelled: boolean; duplicate?: boolean;
  reversed_total: number; replaced_total: number; delta_total: number; purchase_status: string;
}

interface CLine {
  itemId: string; productId: string; name: string; unit: string; trackExpiry: boolean;
  lots: KLot[];
  /** ⚠️  SERVER QARORI. Hujjat tuzatilsa ham AYRIM qator yopiq bo'lishi mumkin
   *  (masalan shu mahsulotda yopilmagan partiya qarzi bor). Server sababni
   *  qator darajasida beradi; UI uni KO'RSATADI va o'sha qatorni yozdirmaydi —
   *  aks holda operator miqdor kiritib, 409 ni faqat «Yozish» dan keyin bilardi. */
  blocked: string | null;
  /** O'rniga qo'yish yoqilganmi va uning qoralamalari. */
  repOn: boolean; repQty: string; repCost: string; repLots: LotDraft[]; repAuto: boolean;
}

/**
 * Hujjat qatorlaridan tuzatish qatorlari.
 *
 * ⚠️  BITTA KOGORTA — BITTA MARTA. Server partiyani qator bilan MAHSULOT
 *     bo'yicha bog'laydi (`/receiving/commit` `purchase_item_id` ni yozmaydi —
 *     kanonik bog'lanish `receiving_id`), shu bois bir mahsulot ikki qatorda
 *     kelsa AYNI kogortalar IKKALA qatorda ham qaytadi. Ikkovida ham miqdor
 *     kiritilsa server «Partiya ikki marta ko'rsatilgan» bilan butun so'rovni
 *     rad etardi — shu bois kogorta faqat BIRINCHI qatorda ko'rsatiladi.
 */
function corrLines(d: KDetail): CLine[] {
  const seen = new Set<string>();
  const out: CLine[] = [];
  for (const it of d.items) {
    const lots = (it.lots || []).filter((l) => !seen.has(l.id));
    lots.forEach((l) => seen.add(l.id));
    if (!lots.length) continue;
    out.push({
      itemId: it.id, productId: it.product_id, name: it.name, unit: it.unit,
      trackExpiry: !!it.track_expiry, lots,
      blocked: it.correctable === false ? (it.correction_blocked_reason || null) : null,
      repOn: false, repQty: "", repCost: "", repLots: [], repAuto: true,
    });
  }
  return out;
}

function KirimTuzatish({ d, onClose, onDone, onStale }: {
  d: KDetail; onClose: () => void; onDone: (res: CorrRes) => void; onStale: () => void;
}) {
  const t = useT();
  const narrow = useNarrow();
  const box = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<CLine[]>(() => corrLines(d));
  const [rev, setRev] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // ⚠️  BARQAROR KALIT. Tranzient xatodan (Railway 504) keyin qayta bosish
  //     serverda IKKINCHI tuzatish yozmasin: dedup faqat AYNI `client_uuid` da
  //     ishlaydi va tuzatish qoldiqni, qarzni VA kassani birdaniga siljitadi.
  const cu = useRef<string>(newClientUuid());
  // Ikki marta bosish — bitta so'rov. `busy` holati RENDERDAN keyin ta'sir
  // qiladi; ref esa AYNI tick'da to'sadi.
  const sending = useRef(false);
  // ⚠️  OXIRGI YUBORILGAN QORALAMA. Tranzient xatodan keyin so'rov serverga
  //     YETIB BORGAN bo'lishi mumkin (faqat javob yo'qolgan): o'shanda hujjat
  //     qayta o'qilganda kogorta qoldig'i allaqachon kamaygan bo'ladi va
  //     mijoz tekshiruvi («qoldiqdan katta») AYNI kalitli takrorni butunlay
  //     to'sardi — holbuki Tier-2 dedup aynan shuning uchun bor: server
  //     `duplicate: true` deb javob beradi. Qoralamaning O'ZI o'zgarmagan
  //     bo'lsa tekshiruv qayta ishlatilmaydi (u jo'natish PAYTIDAGI holatga
  //     qarshi allaqachon o'tgan); o'zgargan bo'lsa — to'liq tekshiriladi.
  const sent = useRef<string | null>(null);
  // ⚠️  FOKUS QOPQONI KALLBEGI BARQAROR BO'LISHI SHART. `useModalFocus` uni
  //     `useEffect` bog'liqligi sifatida oladi: har renderda yangi funksiya
  //     bersak, effekt qayta o'rnatilib, HAR HARF terilganda fokus birinchi
  //     maydonga qaytarilardi (sabab maydoniga bitta harfdan ortiq yozib
  //     bo'lmasdi). Shu bois joriy qiymatlar ref orqali o'qiladi.
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const busyRef = useRef(busy); busyRef.current = busy;
  const askRef = useRef(ask); askRef.current = ask;
  // Tasdiq oynasi ochiq bo'lsa Escape FAQAT o'sha oynani yopadi — yarim
  // to'ldirilgan tuzatish tasodifan yo'q bo'lib ketmasin.
  const dismiss = useCallback(() => { if (!busyRef.current && !askRef.current) closeRef.current(); }, []);
  useModalFocus(box, dismiss, true);
  // Muddat kuzatiladigan qator bo'lsa — filial ish kuni (o'rniga qo'yiladigan
  // partiya muddati shundan oldin bo'lmasin). Ruxsat yo'q bo'lsa JIMGINA
  // maslahatsiz ishlaymiz: server baribir hakam.
  //
  // ⚠️  KUN HUJJAT TEGISHLI FILIALNIKI. `/lots/products/{id}` probi operator
  //     TURGAN filialning kunini qaytaradi: boshqa filialning qabulini
  //     tuzatayotgan menejerga u bir kunlik xato maslahat berib, server rad
  //     etadigan muddatni «to'g'ri» deb ko'rsatardi (yoki aksincha). Server
  //     hujjat bilan birga `business_date` yuborsa — AYNAN u ishlatiladi va
  //     ortiqcha probe umuman qilinmaydi; eski server yubormasa — eskicha.
  const probed = useBusinessDate(
    d.business_date ? null : lines.find((l) => l.trackExpiry)?.productId || null,
  );
  const bizDate = d.business_date || probed;

  const setLine = (i: number, patch: Partial<CLine>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  /** Qatorda teskari qilinayotgan jami miqdor (baza aniqligida). */
  const revSum = (l: CLine) => q3(l.lots.reduce((s, lt) => s + q3(rev[lt.id] || 0), 0));
  /** O'rniga qo'yiladigan jami miqdor — AYNAN serverga ketadigan qiymatlardan. */
  const repSum = (l: CLine) => (l.repOn ? q3(lotsPayload(l.repLots, l.trackExpiry).reduce((s, x) => s + x.qty, 0)) : 0);
  /** Teskari qilinayotgan kogortalardan biri allaqachon harakatlanganmi. */
  const touched = (l: CLine) => l.lots.some((lt) => q3(rev[lt.id] || 0) > 0 && !lt.correctable);

  /** Kogortaning HUJJAT tomonidagi narxi.
   *
   *  ⚠️  KOGORTA TANNARXI EMAS. Yozuvchi teskari yozuvni AYNAN xarid qatorining
   *      narxida baholaydi (`lot_correction.doc_unit_cost` -> `doc_reverse_value`,
   *      `items[purchase_item_id].unit_cost`) — hujjat jami o'sha narxdan
   *      tug'ilgan. Kogorta o'z tannarxini olib yurishi mumkin (kirimda
   *      partiyaga alohida narx berilgan yoki uni avvalgi tuzatish qo'ygan), va
   *      ekran o'shanda hisoblasa BUTUN xulosa serverdan ajralardi: jami ham,
   *      bekor qilish bashorati ham, eng muhimi «pul qimirlaydimi» darvozasi
   *      ham — ekran «kassa kerak emas» deb ko'rsatib, server 400 berardi.
   *
   *  ⚠️  `??` EMAS, TURNI TEKSHIRAMIZ: server yuborgan 0 ham JAVOB (qator narxi
   *      rostdan nol bo'lsa), zaxiraga faqat maydon UMUMAN kelmaganda tushamiz. */
  const docCost = (lt: KLot) => (typeof lt.doc_unit_cost === "number" ? lt.doc_unit_cost : lt.unit_cost);

  const reversedTotal = lines.reduce((s, l) => s + l.lots.reduce((a, lt) => a + q3(rev[lt.id] || 0) * docCost(lt), 0), 0);
  const replacedTotal = lines.reduce((s, l) => s + repSum(l) * (+l.repCost || 0), 0);
  const delta = replacedTotal - reversedTotal;
  const newTotal = d.total + delta;
  // Server bekor qilish shartini AYNAN shunday qo'yadi: hujjat jami 0 VA bu
  // qabulning birorta kogortasida qoldiq qolmagan. Pul 0.01 aniqligida —
  // float tengligi emas, tolerantlik bilan solishtiriladi.
  const allReversed = lines.every((l) => l.lots.every((lt) => q3(rev[lt.id] || 0) >= q3(lt.remaining_qty)));
  const fullCancel = allReversed && !lines.some((l) => l.repOn) && Math.abs(newTotal) < 0.005;

  // ══ KASSA CUSTODY (Phase 5E, §A.4) — SERVER QARORI, EKRAN FAQAT CHIZADI ═══
  //
  // ⚠️  «PUL QIMIRLAYDIMI» — BU EKRANNING QARORI, chunki u operator TERAYOTGAN
  //     qoralamaga bog'liq; server esa hujjat darajasidagi holatni aytadi
  //     (qarzmi/naqdmi, T0 o'tganmi, aktyorning smenasi bormi).
  //
  // ⚠️  HISOB YOZUVCHINIKI BILAN AYNI: `_correct_once` §13 kassa hisobini AYNAN
  //     `ret_amt = paid_amount - new_total` nolga teng bo'lmaganda so'raydi —
  //     `delta` ning o'zi bilan EMAS. Odatdagi naqd hujjatda `paid_amount ==
  //     total`, ya'ni `ret_amt == -delta` va ikki hisob bir xil natija beradi.
  //     Ular faqat hujjat jami to'langan summadan farq qilganda ajraladi (eski
  //     ma'lumot): o'shanda `delta` ga qarash ekranni serverdan AJRATARDI —
  //     «pul qimirlamaydi» deb ko'rsatib, server hisob so'rab 400 berardi.
  const retAmt = d.paid_amount - newTotal;
  const moneyMoves = Math.abs(retAmt) >= 0.005;
  const cust = d.cash_custody;
  const custOptions = cust?.options || [];
  // Eski server (`cash_custody` yo'q) va pul qimirlamaydigan qoralama — blok
  // UMUMAN chizilmaydi: sof identifikatsiya tuzatishi (muddat, partiya raqami)
  // smenasiz ham yoziladi va uni kassa savoli bilan to'sib qo'yish mumkin emas.
  const cashShown = moneyMoves && (cust?.mode === "SERVER_RESOLVED"
    || cust?.mode === "OPERATOR_MUST_CHOOSE" || cust?.mode === "BLOCKED");
  const mustChoose = cashShown && cust?.mode === "OPERATOR_MUST_CHOOSE";
  const [cashAcc, setCashAcc] = useState("");
  // ⚠️  ESKIRGAN TANLOV YUBORILMAYDI. Hujjat rad etishdan keyin qayta o'qiladi va
  //     ro'yxat o'zgargan bo'lishi mumkin (hisob arxivlangan): eski id serverda
  //     `CASH_CUSTODY_ACCOUNT_INVALID` berardi.
  useEffect(() => {
    if (cashAcc && !(cust?.options || []).some((o) => o.id === cashAcc)) setCashAcc("");
  }, [cust, cashAcc]);
  // Tanlash kerak, lekin bu filialda FAOL hisob yo'q — bo'sh «select» emas,
  // ANIQ matn: operator nimani kutayotganini bilsin.
  const cashEmpty = mustChoose && custOptions.length === 0;
  const cashBlocked = (cashShown && cust?.mode === "BLOCKED") || cashEmpty;
  const cashNeed = mustChoose && !cashEmpty && !cashAcc;
  /** Hisobning EKRANDAGI nomi — kod + turi (smena oynasi bilan AYNI qoida). */
  const accName = (a: KCashAccount) =>
    `${tillName(a)} · ${t(a.type === "SAFE" ? "corr.cashSafe" : "corr.cashTill")}`;
  /** Kassa to'sig'ining matni — SERVER kodidan, operator tilida. */
  const cashErr = cashEmpty
    ? t("corr.cashEmpty", { branch: cust?.branch?.name || "—" })
    : cashBlocked ? (translateCashError(cust?.reason || "") ?? cust?.reason ?? t("common.error"))
      : t("corr.cashNeed");

  /**
   * Bu AYNAN jo'natilgan qoralamaning takrorimi (javob yo'qolgan urinishdan
   * keyin).
   *
   * ⚠️  TAKROR KASSA TO'SIG'IDAN O'TADI. Tier-2 dedup aynan shuning uchun bor:
   *     yozuvchi `client_uuid` ni ENG BIRINCHI qadamda tekshiradi
   *     (`lot_correction._correct_once` §1 — «TAKROR, QULFSIZ TEZ YO'L») va
   *     `duplicate: true` ni kassa gardiga UMUMAN tegmasdan qaytaradi. To'siqni
   *     takror USTIGA qo'ysak, ikki urinish orasida hujjat holati o'zgarganda
   *     (smena yopilib eski usulda qayta ochilgan, kassa ro'yxati o'zgargan)
   *     operator serverda ALLAQACHON yozilgan tuzatishni tasdiqlay olmasdi —
   *     va uni yozilmagan deb bilib, yangi kalit bilan IKKINCHI marta yozardi.
   *
   * ⚠️  TA'RIF QAT'IY: `draftKey` kassa hisobini ham o'z ichiga oladi, ya'ni
   *     «aynan o'sha» qoralama jo'natish PAYTIDAGI payload'ni AYNAN takrorlaydi
   *     (boshqa hisob tanlansa yoki miqdor o'zgarsa — bu BOSHQA so'rov va
   *     to'siq odatdagidek ishlaydi).
   *
   * ⚠️  RENDER PAYTIDA HAM O'QILADI (tugma qulfi uchun). `sent` ref bo'lgani
   *     uchun o'zi qayta chizishga sabab bo'lmaydi, lekin u FAQAT `send()`
   *     ichida o'rnatiladi va o'sha yerdan keyin `setBusy`/`setErr` baribir
   *     qayta chizadi — operator qayta bosa oladigan paytda qiymat yangi.
   */
  const isReplay = () => sent.current !== null && sent.current === draftKey();
  const replayReady = isReplay();

  // ⚠️  RAD ETISHDAN KEYIN KOGORTALAR QAYTA O'QILADI. Server 409 bersa hujjat
  //     yangilanadi (`onStale`): ekrandagi qoldiq eskirgan bo'lishi mumkin
  //     (boshqa smena shu orada sotdi) va operator AYNI xatoni takrorlardi.
  //     Terilgan narsa yo'qolmaydi: teskari qilish miqdorlari PARTIYA id'si
  //     bilan saqlanadi, o'rniga qo'yish qoralamalari esa qator bo'yicha
  //     ko'chiriladi.
  useEffect(() => {
    setLines((prev) => corrLines(d).map((l) => {
      const old = prev.find((p) => p.itemId === l.itemId);
      return old ? { ...l, repOn: old.repOn, repQty: old.repQty, repCost: old.repCost,
                     repLots: old.repLots, repAuto: old.repAuto } : l;
    }));
  }, [d]);

  /** Serverga ketadigan qatorlar — bo'sh (na teskari, na o'rniga) qator tushmaydi. */
  function payload() {
    const out: Record<string, unknown>[] = [];
    for (const l of lines) {
      const reverse = l.lots
        .map((lt) => ({ stock_batch_id: lt.id, qty: q3(rev[lt.id] || 0) }))
        .filter((x) => x.qty > 0);
      const replace = l.repOn ? lotsPayload(l.repLots, l.trackExpiry) : [];
      if (!reverse.length && !replace.length) continue;
      // ⚠️  `unit_cost` FAQAT `replace` bilan birga ketadi. Bo'sh `replace` bilan
      //     kelgan tannarxni server 400 bilan rad etadi: `StockBatch.unit_cost`
      //     o'zgarmas, narxni «shunchaki yangilash» kogortani hujjatdan
      //     JIMGINA ajratardi.
      out.push(replace.length
        ? { purchase_item_id: l.itemId, reverse, replace, unit_cost: +l.repCost }
        : { purchase_item_id: l.itemId, reverse });
    }
    return out;
  }

  /** Server qoidalarining OYNASI — o'rniga emas: rad etishni oldindan aytadi. */
  function check(): string {
    const r = reason.trim();
    if (r.length < 3 || r.length > 300) return t("corr.reasonShort");
    for (const l of lines) {
      for (const lt of l.lots) {
        if (q3(rev[lt.id] || 0) > q3(lt.remaining_qty)) return t("corr.overRemaining", { name: l.name });
      }
      if (!l.repOn) continue;
      if (touched(l)) return t("corr.replaceLocked");
      const st = lotLineState(l.repQty, l.repLots, { track_expiry: l.trackExpiry }, bizDate);
      if (!st.ok) return `${t("recv.trackedRowBad", { name: l.name })} — ${lotIssueText(t, st, bizDate)}`;
      // Tannarx 0 bo'lsa partiya `cost_basis = unknown` bilan tug'iladi va o'sha
      // tovarning foydasi hisobotda haqiqatdan katta ko'rinardi (kirim bilan AYNI qoida).
      if (!(+l.repCost > 0)) return t("corr.replaceCostNeed", { name: l.name });
    }
    if (!payload().length) return t("corr.nothing");
    return "";
  }

  /**
   * Operator TERGAN narsaning izi — serverga ketadigan payload'dan emas,
   * kiritilgan qiymatlardan yig'iladi.
   *
   * ⚠️  HUJJATDAN KELGAN QOLDIQ BU YERGA KIRMAYDI. Payload kogortalar
   *     ro'yxatiga tayanadi va muvaffaqiyatsiz urinishdan keyingi qayta
   *     o'qishda u o'zgarishi mumkin — o'shanda AYNI qoralama «boshqa» bo'lib
   *     ko'rinardi. Kalit ham kiritiladi: kalit yangilangach bu boshqa so'rov.
   */
  function draftKey() {
    return JSON.stringify({
      u: cu.current,
      reason: reason.trim(),
      rev: Object.keys(rev).filter((k) => q3(rev[k]) > 0).sort().map((k) => [k, q3(rev[k])]),
      rep: lines.map((l) => [l.itemId, l.repOn, l.repQty, l.repCost, l.repLots]),
      // Kassa hisobi ham SO'ROVNING bir qismi: boshqa hisob tanlansa bu AYNI
      // qoralama emas va to'liq tekshiruv qayta ishlashi kerak.
      acc: mustChoose ? cashAcc : "",
    });
  }

  function submit() {
    // Ayni kalit bilan AYNI qoralamani takrorlash — dedup'ga yo'l ochiq.
    //
    // ⚠️  TAKROR ENG BIRINCHI HAL QILINADI. Ilgari kassa to'sig'i undan OLDIN
    //     turardi va javobi yo'qolgan so'rovni qayta yuborishning ILOJI
    //     qolmasdi: hujjat rad etishdan keyin qayta o'qiladi, holat o'zgargan
    //     bo'lsa (smena yopilgan, kassa ro'yxati bo'shagan) to'siq yopilardi —
    //     holbuki serverda o'sha `client_uuid` allaqachon yozilgan bo'lishi
    //     mumkin va u kassaga TEGMASDAN `duplicate: true` qaytarardi.
    const replay = isReplay();
    // ⚠️  KASSA TO'SIG'I TUGMADAN TASHQARI HAM TEKSHIRILADI: takror yo'li
    //     `check()` ni ATAYLAB o'tkazib yuboradi — YANGI qoralama hisobsiz
    //     (yoki yopiq smena bilan) serverga ketib, tushunarsiz 400 bo'lib
    //     qaytardi.
    if (!replay && (cashBlocked || cashNeed)) { setErr(cashErr); return; }
    const bad = replay ? "" : check();
    setErr(bad);
    if (!bad) setAsk(true);
  }

  async function send() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true); setErr("");
    // So'rov KETISHIDAN oldin belgilanadi: javob yo'qolgan urinish ham
    // «yuborilgan» hisoblanadi — takror aynan shundan keyin kerak bo'ladi.
    sent.current = draftKey();
    try {
      // ⚠️  `cash_account_id` FAQAT `OPERATOR_MUST_CHOOSE` da ketadi. Ochiq
      //     smena kassasini SERVER aniqlaydi (`resolve_cash_custody`) va mijoz
      //     taxmin qilgan hisob smena kassasidan farq qilsa, server butun
      //     tuzatishni rad etardi (`TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER`) —
      //     shu bois `SERVER_RESOLVED` da hech narsa yuborilmaydi.
      const res = await post<CorrRes>(`/receiving/${d.receiving_id}/corrections`, {
        client_uuid: cu.current, reason: reason.trim(), lines: payload(),
        ...(mustChoose && cashAcc ? { cash_account_id: cashAcc } : {}),
      });
      setAsk(false);
      onDone(res);
    } catch (e: any) {
      setAsk(false);
      setErr(e?.message || t("common.error"));
      // ⚠️  «Bu client_uuid BOSHQA so'rovda ishlatilgan» — bu TAKROR emas: ayni
      //     kalit bilan qayta urinish ABADIY 409 berardi. Server aynan yangi
      //     kalit so'raydi.
      // Yangi kalit — YANGI so'rov: eski qoralama izi endi takror emas, shu
      // bois keyingi «Yozish» to'liq tekshiruvdan o'tadi.
      if (e?.code === "LOT_CORRECTION_REPLAY_CONFLICT") { cu.current = newClientUuid(); sent.current = null; }
      // Ekrandagi kogortalar eskirgan bo'lishi mumkin (boshqa smena sotdi) —
      // rad etishdan keyin hujjat QAYTA o'qiladi (kirim ekrani bilan izchil).
      onStale();
    } finally {
      setBusy(false);
      sending.current = false;
    }
  }

  /** Butun hujjatni teskari qilish — har kogorta qoldig'i to'liq qaytariladi. */
  function reverseAll() {
    const next: Record<string, string> = {};
    for (const l of lines) for (const lt of l.lots) if (lt.remaining_qty > 0) next[lt.id] = String(lt.remaining_qty);
    setRev(next);
    setLines((ls) => ls.map((l) => ({ ...l, repOn: false, repLots: [], repQty: "", repCost: "", repAuto: true })));
  }

  /** O'rniga qo'yishni yoqish — boshlang'ich miqdor teskari qilinayotgani. */
  function toggleRep(i: number, on: boolean) {
    setLines((ls) => ls.map((l, j) => {
      if (j !== i) return l;
      if (!on) return { ...l, repOn: false };
      // ⚠️  TAXMIN EMAS, BOSHLANG'ICH QIYMAT. Identifikatsiya tuzatishining
      //     odatiy holi — «ayni miqdor, boshqa muddat/raqam/narx»; operator uni
      //     o'zgartira oladi va server baribir hakam.
      const q = revSum(l);
      const qs = q > 0 ? String(q) : "";
      return { ...l, repOn: true, repQty: qs, repAuto: true,
               repLots: l.repLots.length ? l.repLots : [emptyLot(qs)] };
    }));
  }

  const label: React.CSSProperties = { fontSize: 11.5, color: "var(--muted)", display: "block", marginBottom: 4 };

  return (
    <div onClick={() => { if (!busy) onClose(); }}
         style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 30, padding: 16 }}>
      {/* ⚠️  `Modal` EMAS: uning eni PIKSELDA belgilanadi va telefon ekranidan
          chiqib ketardi. Bu yerda `maxWidth: 100%` — `Confirm` bilan ayni naqsh. */}
      <div ref={box} className="lot-screen modal-scroll" role="dialog" aria-modal="true"
           aria-label={t("corr.title")} data-testid="corr-modal"
           onClick={(e) => e.stopPropagation()}
           style={{ width: 760, maxWidth: "100%", maxHeight: "88vh", overflow: "auto",
                    background: "var(--card)", borderRadius: 20, padding: narrow ? 16 : 24, minWidth: 0 }}>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{t("corr.title")}</div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 5 }}>{t("corr.sub")}</div>

        <label style={{ display: "block", marginTop: 16 }}>
          <span style={label}>{t("corr.reason")} *</span>
          <input value={reason} maxLength={300} data-testid="corr-reason"
                 placeholder={t("corr.reasonPh")} onChange={(e) => setReason(e.target.value)}
                 style={{ ...inputStyle, height: 44 }} />
        </label>

        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button type="button" className="btn btn-ghost" data-testid="corr-reverse-all" onClick={reverseAll}
                  style={{ height: 38, color: "var(--danger)" }}>{t("corr.reverseAll")}</button>
        </div>

        {lines.map((l, i) => (
          <section key={l.itemId} data-testid={`corr-line-${i}`}
                   style={{ border: "1px solid var(--border)", borderRadius: 14, padding: narrow ? 12 : 14, marginTop: 14, background: "var(--surface)", minWidth: 0 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <strong className="lot-wrap" style={{ fontSize: 14 }}>{l.name}</strong>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{unitL(t, l.unit)}</span>
              {revSum(l) > 0 && (
                <span data-testid={`corr-line-${i}-rev`} className="tabular"
                      style={{ fontSize: 12, fontWeight: 700, color: "var(--danger)" }}>
                  {t("corr.reversedLine", { n: revSum(l) })}
                </span>
              )}
            </div>

            {l.blocked && (
              <div role="status" data-testid={`corr-line-${i}-blocked`}
                   style={{ fontSize: 12, color: "var(--warn)", marginTop: 8 }}>
                {/* Sabab SERVERDAN keladi — hujjat darajasidagi to'siq bilan AYNI
                    yo'l: lug'atdan o'tkaziladi, aks holda operator xom lotin
                    matnini ko'radi. */}
                {translateLotError(l.blocked) ?? l.blocked}
              </div>
            )}

            {l.lots.map((lt) => {
              const n = q3(rev[lt.id] || 0);
              const over = n > q3(lt.remaining_qty);
              return (
                <div key={lt.id} data-testid={`corr-lot-${lt.id}`}
                     style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--border-input)" }}>
                  <div style={{ flex: "1 1 260px", minWidth: 0 }}>
                    <div className="lot-wrap" style={{ fontWeight: 700, fontSize: 13 }}>
                      {lt.batch_no || t("lot.noBatchNo")}
                      {lt.expiry_date ? ` · ${lt.expiry_date}` : ""}
                    </div>
                    <div className="tabular" style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                      {t("lot.received")}: {lt.received_qty} · {t("lot.remaining")}: {lt.remaining_qty}
                      {" · "}{t("corr.consumed")}: {lt.consumed_qty} · {t("lot.unitCost")}: {fmt(lt.unit_cost)}
                    </div>
                    {!lt.correctable && (
                      <div style={{ fontSize: 11.5, color: "var(--warn)", marginTop: 4 }}
                           data-testid={`corr-lot-${lt.id}-touched`}>{t("corr.touched")}</div>
                    )}
                  </div>
                  <label style={{ flex: "0 0 150px" }}>
                    <span style={label}>{t("corr.reverseQty")}</span>
                    <input value={rev[lt.id] || ""} inputMode="decimal" data-testid={`corr-rev-${lt.id}`}
                           disabled={lt.remaining_qty <= 0 || !!l.blocked} aria-invalid={over || undefined}
                           aria-label={`${t("corr.reverseQty")} — ${lt.batch_no || t("lot.noBatchNo")}`}
                           onChange={(e) => setRev((s) => ({ ...s, [lt.id]: qtyIn(e.target.value) }))}
                           style={{ ...inputStyle, height: 40, textAlign: "right", borderColor: over ? "var(--danger)" : undefined }} />
                  </label>
                </div>
              );
            })}

            <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px dashed var(--border-input)" }}>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, fontWeight: 600 }}>
                {/* ⚠️  YOQIB BO'LMAYDI, LEKIN O'CHIRIB BO'LADI. Tegilgan kogorta
                    tanlangach tugmani BUTUNLAY o'chirish operatorni yoqib
                    qo'yilgan o'rniga qo'yishdan chiqa olmaydigan holatda
                    qoldirardi. */}
                <input type="checkbox" checked={l.repOn} disabled={touched(l) && !l.repOn}
                       data-testid={`corr-replace-${i}`}
                       onChange={(e) => toggleRep(i, e.target.checked)} />
                {t("corr.replaceOn")}
              </label>
              {touched(l) && (
                <div style={{ fontSize: 11.5, color: "var(--warn)", marginTop: 6 }}
                     data-testid={`corr-replace-${i}-locked`}>{t("corr.replaceLocked")}</div>
              )}
              {l.repOn && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <label style={{ flex: "1 1 150px", minWidth: 0 }}>
                      <span style={label}>{t("corr.replaceQty")}</span>
                      <input value={l.repQty} inputMode="decimal" data-testid={`corr-rep-qty-${i}`}
                             onChange={(e) => {
                               const q = qtyIn(e.target.value);
                               // Bitta TEGILMAGAN partiya qator miqdoriga ergashadi (kirim ekrani bilan izchil).
                               const ls = l.repAuto && l.repLots.length === 1 ? [{ ...l.repLots[0], qty: q }] : l.repLots;
                               setLine(i, { repQty: q, repLots: ls });
                             }}
                             style={{ ...inputStyle, height: 40, textAlign: "right" }} />
                    </label>
                    <label style={{ flex: "1 1 170px", minWidth: 0 }}>
                      <span style={label}>{t("corr.replaceCost")}</span>
                      <input value={l.repCost} inputMode="numeric" data-testid={`corr-rep-cost-${i}`}
                             onChange={(e) => setLine(i, { repCost: moneyIn(e.target.value) })}
                             style={{ ...inputStyle, height: 40, textAlign: "right" }} />
                    </label>
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <LotReceivingEditor
                      product={{ id: l.productId, name: l.name, unit_code: l.unit, track_expiry: l.trackExpiry }}
                      lineQty={l.repQty} lots={l.repLots} bizDate={bizDate}
                      onChange={(ls) => setLine(i, { repLots: ls, repAuto: false })}
                      testid={`corr-lots-${i}`} idPrefix={`corr-lot-${i}`} />
                  </div>
                </div>
              )}
            </div>
          </section>
        ))}

        {lines.length === 0 && (
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 14 }} data-testid="corr-no-lots">{t("corr.noLots")}</div>
        )}

        <div data-testid="corr-summary" className="tabular"
             style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)", fontSize: 13 }}>
          {t("corr.sumReversed")}: <b style={{ color: "var(--danger)" }}>{fmt(reversedTotal)}</b>
          {" · "}{t("corr.sumReplaced")}: <b style={{ color: "var(--ok)" }}>{fmt(replacedTotal)}</b>
          {" · "}{t("corr.newTotal")}: <b>{fmt(newTotal)}</b>
        </div>

        {/* ── KASSA MANBAI (Phase 5E, §A.4) ────────────────────────────────────
            ⚠️  FAQAT PUL SILJIYDIGAN QORALAMADA. Sof identifikatsiya tuzatishi
                (muddat, partiya raqami) kassaga TEGMAYDI — server ham hisob
                so'ramaydi va uni savol bilan to'sib qo'yish operatorni
                smenasiz qoldirardi. */}
        {cashShown && (
          <section data-testid="corr-cash" aria-label={t("corr.cashTitle")}
                   style={{ marginTop: 14, padding: narrow ? 12 : 14, borderRadius: 14, minWidth: 0,
                            border: `1px solid ${cashBlocked ? "var(--warn)" : "var(--border)"}`,
                            background: cashBlocked ? "var(--warn-soft)" : "var(--surface)" }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{t("corr.cashTitle")}</div>

            {cust?.mode === "SERVER_RESOLVED" && cust.resolved && (
              // FAQAT O'QISH: smena o'rtasida kassa almashtirilmaydi, shu bois
              // bu yerda tanlov KO'RSATILMAYDI (server uni rad etardi).
              <div style={{ marginTop: 8 }}>
                <div data-testid="corr-cash-resolved" style={{ fontSize: 13.5, fontWeight: 700 }}>
                  {accName(cust.resolved)}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>{t("corr.cashResolvedNote")}</div>
              </div>
            )}

            {mustChoose && !cashEmpty && (
              <label style={{ display: "block", marginTop: 8 }}>
                <span style={label}>{t("corr.cashChoose")} *</span>
                {/* ⚠️  BITTA HISOB HAM AVTOMATIK TANLANMAYDI: pul qayerdan
                    o'tganini TAXMIN qilish — aynan shu bo'limda taqiqlangan
                    narsa (server ham «filialda bitta kassa» sababini qabul
                    qilmaydi). Operator buni AYTADI. */}
                <select value={cashAcc} data-testid="corr-cash-select" required
                        aria-invalid={cashNeed || undefined}
                        onChange={(e) => setCashAcc(e.target.value)}
                        style={{ ...inputStyle, height: 44 }}>
                  <option value="">{t("corr.cashChoosePh")}</option>
                  {custOptions.map((o) => <option key={o.id} value={o.id}>{accName(o)}</option>)}
                </select>
              </label>
            )}

            {(cashNeed || cashBlocked) && (
              <div role="note" data-testid={cashEmpty ? "corr-cash-empty" : cashBlocked ? "corr-cash-blocked" : "corr-cash-need"}
                   style={{ fontSize: 12.5, fontWeight: 600, marginTop: 8,
                            color: cashBlocked ? "var(--warn)" : "var(--muted)" }}>
                {/* To'siq sababi SERVER kodidan keladi va `serverErrorsCash.ts`
                    orqali operator tiliga o'giriladi — xom kod ko'rinmaydi. */}
                {cashBlocked && !cashEmpty ? `${t("corr.cashBlocked")} ${cashErr}` : cashErr}
              </div>
            )}
          </section>
        )}

        {err && <div role="alert" data-testid="corr-error"
                     style={{ color: "var(--danger)", fontSize: 13, marginTop: 12 }}>{err}</div>}

        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
          <button className="btn btn-ghost" style={{ flex: "1 1 140px", height: 46 }}
                  data-testid="corr-close" onClick={onClose} disabled={busy}>{t("common.cancel")}</button>
          {/* ⚠️  QULF FAQAT PUL SILJIYDIGAN QORALAMADA (`cashShown` ichidagi
              holatlar): pul tegmaydigan tuzatish HAR rejimda, `BLOCKED` da ham
              yoziladi — aks holda smenasiz menejer muddat xatosini ham
              tuzata olmasdi.
              ⚠️  TAKROR HAM QULFDAN TASHQARI (`replayReady`): javobi yo'qolgan
              so'rovni qayta yuborish yo'li tugmada ham ochiq turishi kerak —
              aks holda `submit()` dagi imtiyoz hech qachon ishga tushmasdi. */}
          <button className="btn" style={{ flex: "1 1 200px", height: 46, background: "var(--danger)", color: "#fff", opacity: busy || ((cashBlocked || cashNeed) && !replayReady) ? 0.6 : 1 }}
                  data-testid="corr-submit" onClick={submit} disabled={busy || ((cashBlocked || cashNeed) && !replayReady)}>
            {fullCancel ? t("corr.submitCancel") : t("corr.submit")}
          </button>
        </div>
      </div>

      {ask && (
        <Confirm title={fullCancel ? t("corr.confirmCancelTitle") : t("corr.confirmTitle")}
                 confirmLabel={fullCancel ? t("corr.submitCancel") : t("corr.submit")} busy={busy}
                 onCancel={() => setAsk(false)} onConfirm={send}
                 lines={[
                   t("corr.confirmIrreversible"),
                   ...(fullCancel ? [t("corr.confirmCancelBody")] : []),
                   t("corr.confirmMoney", { old: fmt(d.total), next: fmt(newTotal) }),
                   t("corr.confirmEffect"),
                 ]} />
      )}
    </div>
  );
}

function SupplierEdit({ s, onClose, onDone }: { s: Supplier; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(s.name);
  const [phone, setPhone] = useState(s.phone || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();
  async function save() { setBusy(true); setErr(""); try { await api(`/suppliers/${s.id}`, { method: "PATCH", body: JSON.stringify({ name, phone }) }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  async function del() { if (!window.confirm(t("cust.deleteConfirm", { name: `"${s.name}"` }))) return; setBusy(true); setErr(""); try { await api(`/suppliers/${s.id}`, { method: "DELETE" }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("purch.supplier")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("purch.name")} style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={inputStyle} />
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        {err && <div style={{ color: "var(--danger)", fontSize: 12.5, alignSelf: "center" }}>{err}</div>}
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function SupplierNew({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();
  async function save() { if (!name.trim()) return; setBusy(true); setErr(""); try { await post("/suppliers", { name, phone }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("purch.newSupplier")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("purch.name")} style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("common.add")}</button>
      </div>
    </Modal>
  );
}

// ── Kirim qatorlari muharriri (qo'lda + rasm oqimlari uchun umumiy) ──────────
function RowsEditor({ rows, setRows, products, cats, t, bizDate }: {
  rows: KRow[]; setRows: (f: (r: KRow[]) => KRow[]) => void;
  products: Product[]; cats: Category[]; t: (k: string, v?: Record<string, string | number>) => string;
  bizDate?: string | null;
}) {
  const setRow = (i: number, patch: Partial<KRow>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  // Miqdor: bitta TEGILMAGAN partiya qator miqdoriga ergashadi (kirim ekrani bilan izchil).
  const setQty = (i: number, qty: string) => setRows((r) => r.map((x, j) => {
    if (j !== i) return x;
    const lots = x.lots && x.lotsAuto && x.lots.length === 1 ? [{ ...x.lots[0], qty }] : x.lots;
    return { ...x, qty, lots };
  }));
  const pick = (i: number, p: Product) => setRows((r) => r.map((x, j) => (j === i ? {
    ...x, pid: p.id, name: p.name, cost: String(p.base_buy_price || ""),
    sell: String(p.base_sell_price || ""), open: false,
    lots: p.track_lots ? [emptyLot(x.qty)] : null, lotsAuto: true,
  } : x)));
  // Yangi mahsulot nomi yozilgach — kategoriya AVTO taxmini (katalogdagi o'xshash nomdan)
  async function guessCat(i: number, name: string) {
    if (name.trim().length < 3) return;
    try {
      const g = await get<{ category_id: string | null }>(`/products/guess-category?name=${encodeURIComponent(name.trim())}`);
      if (g.category_id) setRows((rs) => rs.map((x, j) => (j === i && !x.pid && !x.catId ? { ...x, catId: g.category_id! } : x)));
    } catch { /* taxmin bo'lmasa — foydalanuvchi o'zi tanlaydi */ }
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map((r, i) => {
        const q = r.name.trim().toLowerCase();
        const sugg = r.open && q.length >= 2 && !r.pid
          ? products.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8)
          : [];
        const prod = products.find((p) => p.id === r.pid);
        const isNew = !r.pid && r.name.trim().length > 0;
        return (
          <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px", background: "var(--surface)" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
                <input value={r.name} placeholder={t("purch.searchProduct")}
                  onChange={(e) => setRow(i, { name: e.target.value, pid: "", open: true, lots: null, lotsAuto: true })}
                  onFocus={() => setRow(i, { open: true })}
                  onBlur={(e) => { const v = e.target.value; setTimeout(() => void guessCat(i, v), 200); }}
                  style={{ ...inputStyle, height: 42, width: "100%" }} />
                {sugg.length > 0 && (
                  <div style={{ position: "absolute", left: 0, right: 0, top: 46, zIndex: 40, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "0 12px 30px rgba(0,0,0,0.18)", overflow: "hidden" }}>
                    {sugg.map((p) => (
                      <div key={p.id} onClick={() => pick(i, p)} style={{ padding: "9px 12px", cursor: "pointer", fontSize: 13, display: "flex", justifyContent: "space-between", gap: 10, borderTop: "1px solid var(--border-soft)" }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
                        <span className="tabular" style={{ color: "var(--muted)", flex: "none" }}>{fmt(p.base_sell_price)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {/* ⚠️  `qtyIn` — vergul ham o'nlik ajratgich (KirimDetail, FullReceiving va
                  partiya muharriri bilan AYNI). Xom regex vergulni O'CHIRARDI: «1,5»
                  15 bo'lib ketardi va partiya ham shu 15 ni olib, jimgina 10 baravar
                  ko'p qoldiq yozilardi (Phase 5C review, C-1). */}
              <input placeholder={t("purch.qty")} value={r.qty} data-testid={`kirim-qty-${i}`} onChange={(e) => setQty(i, qtyIn(e.target.value))} inputMode="decimal" style={{ ...inputStyle, height: 42, width: 76, textAlign: "right" }} />
              <button onClick={() => setRows((rr) => rr.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", fontSize: 15 }}>✕</button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 110 }}>
                <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{t("prod.buyPrice")}</div>
                <input value={r.cost} onChange={(e) => setRow(i, { cost: e.target.value.replace(/\D/g, "") })} inputMode="numeric" placeholder="0" style={{ ...inputStyle, height: 38, width: "100%", textAlign: "right" }} />
              </div>
              <div style={{ flex: 1, minWidth: 110 }}>
                <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{t("prod.sellPrice")}</div>
                <input value={r.sell} onChange={(e) => setRow(i, { sell: e.target.value.replace(/\D/g, "") })} inputMode="numeric" placeholder="0" style={{ ...inputStyle, height: 38, width: "100%", textAlign: "right" }} />
              </div>
              {isNew && (
                <div style={{ flex: 1.2, minWidth: 140 }}>
                  <div style={{ fontSize: 10.5, color: "var(--accent-ink)", marginBottom: 3 }}>{t("purch.newProd")}</div>
                  <select value={r.catId} onChange={(e) => setRow(i, { catId: e.target.value })} style={{ ...inputStyle, height: 38, width: "100%", borderColor: r.catId ? undefined : "var(--warn)" }}>
                    <option value="">{t("prod.pickCategory")}</option>
                    {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              )}
              {isNew && (
                <div style={{ minWidth: 84 }}>
                  <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{t("recv.unit")}</div>
                  <select value={r.unit || "dona"} onChange={(e) => setRow(i, { unit: e.target.value })} style={{ ...inputStyle, height: 38, width: "100%" }}>
                    {UNITS.map((u) => <option key={u} value={u}>{unitL(t, u)}</option>)}
                  </select>
                </div>
              )}
              {isNew && (
                // Yangi mahsulot: kg -> PLU majburiy, boshqa birliklar -> shtrix-kod majburiy (skanerlang yoki tering)
                <div style={{ flex: 1, minWidth: 130 }}>
                  <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{r.unit === "kg" ? t("recv.pluPh") : t("recv.barcodeReq")}</div>
                  {r.unit === "kg" ? (
                    <input value={r.plu} inputMode="numeric" placeholder={t("recv.pluPh")}
                      onChange={(e) => setRow(i, { plu: e.target.value.replace(/\D/g, "") })}
                      style={{ ...inputStyle, height: 38, width: "100%", fontFamily: "monospace", borderColor: r.plu ? undefined : "var(--warn)" }} />
                  ) : (
                    <input value={r.barcode} inputMode="numeric" placeholder={t("recv.barcodeReq")}
                      onChange={(e) => {
                        const c = e.target.value.replace(/\D/g, "");
                        // Skanerlangan kod bazada bor bo'lsa — qatorni mavjud mahsulotga bog'laymiz
                        const hit = c.length >= 6 ? products.find((p) => (p.barcodes || []).includes(c)) : undefined;
                        if (hit) pick(i, hit); else setRow(i, { barcode: c });
                      }}
                      style={{ ...inputStyle, height: 38, width: "100%", fontFamily: "monospace", borderColor: r.barcode ? undefined : "var(--warn)" }} />
                  )}
                </div>
              )}
              {prod && (
                <div className="tabular" style={{ fontSize: 12, fontWeight: 600, color: "var(--ok)", whiteSpace: "nowrap" }}>
                  {prod.stock} → {prod.stock + (+r.qty || 0)}
                </div>
              )}
            </div>
            {prod?.track_lots && (
              // Kuzatuvli tovar — partiyalarsiz hujjat SERVERDA 400 oladi
              // (butun hujjat, kuzatuvsiz qatorlari bilan birga).
              <div style={{ marginTop: 10 }}>
                <LotReceivingEditor
                  product={{ id: prod.id, name: prod.name, unit_code: r.unit,
                             track_expiry: !!prod.track_expiry }}
                  lineQty={r.qty} lots={r.lots || []} bizDate={bizDate}
                  onChange={(ls) => setRows((rr) => rr.map((x, j) => (j === i ? { ...x, lots: ls, lotsAuto: false } : x)))}
                  testid={`kirim-lots-${i}`} idPrefix={`kirim-lot-${i}`} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function trackedProduct(r: KRow, products: Product[]): Product | undefined {
  return r.pid ? products.find((p) => p.id === r.pid && p.track_lots) : undefined;
}

function buildItems(rows: KRow[], products: Product[] = []) {
  return rows
    .filter((r) => (r.pid || r.name.trim()) && +r.qty > 0)
    .map((r) => {
      const base = {
        product_id: r.pid || null,
        new_name: r.pid ? null : r.name.trim(),
        new_sell_price: r.sell !== "" ? +r.sell : null,
        new_category_id: !r.pid && r.catId ? r.catId : null,
        new_barcode: !r.pid && r.unit !== "kg" && r.barcode.trim() ? r.barcode.trim() : null,
        new_plu: !r.pid && r.unit === "kg" && r.plu.trim() ? r.plu.trim() : null,
        new_is_weighted: r.pid ? null : r.unit === "kg",
        qty: +r.qty,
        unit_cost: +r.cost || 0,
        ai_name: r.aiName || null,
        unit: r.unit || null,
      };
      const tr = trackedProduct(r, products);
      if (!tr) return base;          // KUZATUVSIZ QATOR — payload harfma-harf avvalgidek
      return { ...base, qty: (milli(r.qty) ?? 0) / 1000,
               lots: lotsPayload(r.lots || [], !!tr.track_expiry) };
    });
}

// ── Qo'lda kirim: mavjudni tanla (narxlar avto) yoki yangi nom + kategoriya + narxlar ──
function PhotoKirim({ suppliers, onClose, onSaved }: { suppliers: Supplier[]; onClose: () => void; onSaved: () => void }) {
  const { data: products } = useGet<Product[]>("/products?include_archived=1");
  const { data: cats } = useGet<Category[]>("/categories");
  const [stage, setStage] = useState<"pick" | "scanning" | "review">("pick");
  const [rows, setRows] = useState<KRow[]>([]);
  const [supplier, setSupplier] = useState("");
  const [payment, setPayment] = useState<"cash" | "credit">("cash");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [dup, setDup] = useState(false);
  const imgRef = useRef<{ b64: string; media: string; source: string; aiRaw: unknown[] }>({ b64: "", media: "", source: "ai", aiRaw: [] });
  const fileRef = useRef<HTMLInputElement>(null);
  // QA PR-003 (CRITICAL edi — Modul-3 PC-002 naqshi): client_uuid har save()'da YANGI yaratilardi —
  // tranzient xatodan (Railway 504) keyin qayta bosish backend dedup'ini chetlab IKKINCHI kirim
  // (stok+qarz 2x) yozardi. Endi BARQAROR ref (FullReceiving recvUuid bilan izchil).
  const commitUuid = useRef<string>(crypto.randomUUID());
  const t = useT();
  // Filial ish kuni — faqat muddat kuzatiladigan qator bo'lsa so'raladi; ruxsat
  // bo'lmasa JIMGINA maslahatsiz ishlaymiz (server baribir hakam).
  const bizProbe = rows.map((r) => (products || []).find((p) => p.id === r.pid))
    .find((p) => p?.track_lots && p?.track_expiry)?.id || null;
  const bizDate = useBusinessDate(bizProbe);

  async function onFile(f: File | null) {
    if (!f) return;
    setErr("");
    const b64 = await new Promise<string>((res, rej) => {
      const rd = new FileReader();
      rd.onload = () => res(String(rd.result).split(",")[1] || "");
      rd.onerror = () => rej(new Error("read"));
      rd.readAsDataURL(f);
    });
    imgRef.current.b64 = b64;
    imgRef.current.media = f.type || "image/jpeg";
    setStage("scanning");
    try {
      const r = await post<{ source: string; items: { ai_name: string; qty: number; unit: string; product_id: string | null; matched_name: string | null; unit_cost: number }[]; ai_raw: unknown[] }>(
        "/receiving/scan", { image_b64: b64, media_type: imgRef.current.media });
      imgRef.current.source = r.source;
      imgRef.current.aiRaw = r.ai_raw || [];
      const prods = products || [];
      const newRows: KRow[] = (r.items || []).map((it) => {
        const p = it.product_id ? prods.find((x) => x.id === it.product_id) : undefined;
        const qty = String(it.qty || 1);
        return {
          pid: it.product_id || "", name: it.matched_name || it.ai_name,
          qty, cost: String(Math.round(it.unit_cost || 0) || ""),
          sell: p ? String(p.base_sell_price || "") : "", catId: "", open: false,
          aiName: it.ai_name, unit: it.unit || "dona", barcode: "", plu: "",
          // Kuzatuvli tovarga darhol bitta partiya qoralamasi ochiladi.
          lots: p?.track_lots ? [emptyLot(qty)] : null, lotsAuto: true,
        };
      });
      // Yangi (bazada topilmagan) mahsulotlarga kategoriya AVTO taxmini (katalogdagi o'xshash nomdan)
      await Promise.all(newRows.map(async (row) => {
        if (row.pid || row.name.trim().length < 3) return;
        try {
          const g = await get<{ category_id: string | null }>(`/products/guess-category?name=${encodeURIComponent(row.name.trim())}`);
          if (g.category_id) row.catId = g.category_id;
        } catch { /* taxmin bo'lmasa — foydalanuvchi o'zi tanlaydi */ }
      }));
      setRows(() => newRows);
      setStage("review");
    } catch (e: any) { setErr(e.message); setStage("pick"); }
  }

  async function save() {
    if (busy) return;
    const prods = products || [];
    const items = buildItems(rows, prods);
    if (!items.length) { setErr(t("purch.errNeedItems")); return; }
    // KUZATUVLI QATOR: partiyalar to'liq va tannarx ANIQ bo'lishi shart.
    // ⚠️  Tannarx 0 bo'lsa partiya `cost_basis = unknown` bilan tug'iladi va
    //     o'sha tovarning foydasi hisobotda haqiqatdan katta ko'rinardi.
    // ⚠️  JIMGINA TUSHIB QOLMASIN (Phase 5C review, C-1). `buildItems` miqdori
    //     musbat bo'lmagan qatorni FILTRLAYDI. Kuzatuvli (yoki partiya kiritilgan)
    //     qatorda bu — partiyasi to'ldirilgan tovar hujjatga UMUMAN tushmasligi va
    //     operatorga «saqlandi» deyilishi demak edi. Kirim ekranidagi qoida bilan
    //     AYNI: bunday qator ANIQ xato bilan to'xtatiladi.
    const badQty = rows.find((r) => (trackedProduct(r, prods) || (r.lots || []).length > 0) && !(+r.qty > 0));
    if (badQty) {
      const nm = trackedProduct(badQty, prods)?.name || badQty.name.trim();
      setErr(`${t("recv.trackedRowBad", { name: nm })} — ${t("recv.needQty")}`);
      return;
    }
    for (const r of rows) {
      const tr = trackedProduct(r, prods);
      if (!tr || !(+r.qty > 0)) continue;
      const st = lotLineState(r.qty, r.lots || [], { track_expiry: tr.track_expiry }, bizDate);
      if (!st.ok) {
        setErr(`${t("recv.trackedRowBad", { name: tr.name })} — ${lotIssueText(t, st, bizDate)}`);
        return;
      }
      if (!(+r.cost > 0)) { setErr(`${t("recv.trackedRowBad", { name: tr.name })} — ${t("recv.needCostTracked")}`); return; }
    }
    // YANGI mahsulot: kg -> PLU majburiy; boshqa birliklar -> shtrix-kod majburiy (mobil/kirim bilan bir xil qoida)
    const noCode = rows.find((r) => !r.pid && r.name.trim() && +r.qty > 0 && (r.unit === "kg" ? !r.plu.trim() : !r.barcode.trim()));
    if (noCode) { setErr(noCode.unit === "kg" ? t("recv.needPlu") : t("recv.needBarcode")); return; }
    const noCat = rows.find((r) => !r.pid && r.name.trim() && +r.qty > 0 && !r.catId);
    if (noCat) { setErr(t("recv.needCat")); return; }
    setBusy(true); setErr("");
    try {
      const res = await post<{ duplicate?: boolean }>("/receiving/commit", {
        items, supplier_id: supplier || null, payment, source: imgRef.current.source,
        image_b64: imgRef.current.b64, ai_raw: imgRef.current.aiRaw,
        client_uuid: commitUuid.current,
      });
      // TAKROR — hujjat allaqachon yozilgan; jimgina yopib «saqlandimi?» degan
      // savolni qoldirmaymiz (kirim ekrani bilan izchil).
      if (res && res.duplicate) { setDup(true); return; }
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={680}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 14 }}>📷 {t("purch.photoKirim")}</div>

      {stage === "pick" && (
        <div>
          <div onClick={() => fileRef.current?.click()}
            style={{ border: "2px dashed var(--accent-border)", borderRadius: 14, padding: "44px 20px", textAlign: "center", cursor: "pointer", background: "var(--surface)" }}>
            <div style={{ fontSize: 34, marginBottom: 8 }}>📸</div>
            <div style={{ fontWeight: 700, fontSize: 14.5 }}>{t("purch.pickPhoto")}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 5 }}>{t("purch.photoHint")}</div>
          </div>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
            onChange={(e) => onFile(e.target.files?.[0] || null)} />
          {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>{err}</div>}
        </div>
      )}

      {stage === "scanning" && (
        <div style={{ padding: "50px 0", textAlign: "center", color: "var(--muted)", fontSize: 14, fontWeight: 600 }}>{t("purch.scanning")}</div>
      )}

      {stage === "review" && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
            <select value={supplier} onChange={(e) => setSupplier(e.target.value)} style={inputStyle}>
              <option value="">{t("purch.supplier")} —</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <select value={payment} onChange={(e) => setPayment(e.target.value as "cash" | "credit")} style={{ ...inputStyle, width: 160 }}>
              <option value="cash">{t("purch.paid")}</option>
              <option value="credit">{t("purch.statusDebt")}</option>
            </select>
          </div>
          <RowsEditor rows={rows} setRows={setRows} products={products || []} cats={cats || []} t={t} bizDate={bizDate} />
          <button onClick={() => setRows((r) => [...r, emptyRow()])} style={{ border: "1.5px dashed var(--accent-border)", background: "var(--surface)", borderRadius: 11, padding: "10px 16px", cursor: "pointer", fontWeight: 600, color: "var(--accent-ink)", marginTop: 10 }}>＋ {t("purch.addRow")}</button>
          {err && <div role="alert" data-testid="kirim-error" style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>{err}</div>}
          {dup && (
            <div role="status" data-testid="kirim-duplicate"
                 style={{ marginTop: 10, padding: "10px 13px", borderRadius: 11, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12.5, fontWeight: 600 }}>
              {t("lot.alreadyApplied")}
            </div>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={dup ? onSaved : onClose}>{dup ? t("common.close") : t("common.cancel")}</button>
            <button className="btn btn-primary" style={{ flex: 1 }} data-testid="kirim-save" disabled={busy || dup} onClick={save}>{busy ? "..." : t("purch.saveKirim")}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ═══ YETKAZIB BERUVCHI BATAFSIL: qarz, yetkazgan mahsulotlar, xaridlar tarixi ═══
interface SupDetail {
  id: string; name: string; phone: string | null; balance: number;
  purchase_count: number; total_purchased: number; paid_total: number; product_types: number;
  total_qty: number; avg_purchase: number; expected_profit: number; profit_margin: number;
  last_purchase: string | null;
  top_qty_product: { name: string; qty: number } | null;
  top_profit_product: { name: string; profit: number } | null;
  products: { name: string; qty: number; cost: number; profit: number }[];
  recent_purchases: { id: string; doc_no: string; date: string; total: number; status: string }[];
}

function SupplierDetail({ id, onBack, onEdit, editModal }: { id: string; onBack: () => void; onEdit: () => void; editModal?: React.ReactNode }) {
  const t = useT();
  const detail = useGet<SupDetail>(`/suppliers/${id}`);
  const [payOpen, setPayOpen] = useState(false);
  const d = detail.data;

  return (
    <main className="main">
      <Topbar title={d ? d.name : "…"} sub={d?.phone || t("purch.supplier")} onBack={onBack}
        right={<div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" onClick={onEdit}>{t("cust.edit")}</button>
          {d && d.balance > 0 && <button className="btn btn-primary" onClick={() => setPayOpen(true)}>{t("purch.payDebt")}</button>}
        </div>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {!d ? <div style={{ color: "var(--muted)" }}>{t("common.loading")}</div> : (
          <div style={{ maxWidth: 1000, display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{d.balance < 0 ? t("purch.advance") : t("purch.debt")}</div>
                {/* QA PR-009: manfiy balans (ta'minotchi bizga qarzdor — avans) endi ko'rinadi, 'toza' emas */}
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6, color: d.balance > 0 ? "var(--danger)" : d.balance < 0 ? "var(--accent-strong)" : "var(--ok)" }}>{d.balance !== 0 ? fmt(Math.abs(d.balance)) : t("purch.clean")}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.totalPurchased")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{fmt(d.total_purchased)}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.paidTotal")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6, color: "var(--ok)" }}>{fmt(d.paid_total)}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.avgPurchase")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{fmt(d.avg_purchase)}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.expectedProfit")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6, color: d.expected_profit >= 0 ? "var(--ok)" : "var(--danger)" }}>{fmt(d.expected_profit)}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.profitMargin")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6, color: d.profit_margin >= 0 ? "var(--ok)" : "var(--danger)" }}>{d.profit_margin.toFixed(1)}%</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.docs")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{d.purchase_count}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.productTypes")}</div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{d.product_types}</div></div>
            </div>

            {/* Diqqatga sazovor: eng ko'p olib kelingan / eng foydali / oxirgi xarid / jami miqdor */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
              <div className="card" style={{ background: "var(--card-alt)" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("purch.topProduct")}</div>
                <div style={{ fontSize: 15, fontWeight: 700, marginTop: 6 }}>{d.top_qty_product ? d.top_qty_product.name : "—"}</div>
                {d.top_qty_product && <div className="tabular" style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{d.top_qty_product.qty}</div>}</div>
              <div className="card" style={{ background: "var(--card-alt)" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("purch.topProfit")}</div>
                <div style={{ fontSize: 15, fontWeight: 700, marginTop: 6 }}>{d.top_profit_product ? d.top_profit_product.name : "—"}</div>
                {d.top_profit_product && <div className="tabular" style={{ fontSize: 12, color: "var(--ok)", marginTop: 2 }}>{fmt(d.top_profit_product.profit)}</div>}</div>
              <div className="card" style={{ background: "var(--card-alt)" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("purch.lastPurchase")}</div>
                <div style={{ fontSize: 15, fontWeight: 700, marginTop: 6 }}>{d.last_purchase || "—"}</div></div>
              <div className="card" style={{ background: "var(--card-alt)" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("purch.totalQty")}</div>
                <div className="tabular" style={{ fontSize: 15, fontWeight: 700, marginTop: 6 }}>{d.total_qty}</div></div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px 10px", fontSize: 15, fontWeight: 700 }}>{t("purch.deliveredProducts")}</div>
                <div style={{ maxHeight: 420, overflowY: "auto" }} className="no-sb">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr style={{ background: "var(--card-alt)" }}>
                      <th style={th}>{t("sales.thProduct")}</th><th style={{ ...th, textAlign: "right" }}>{t("recv.qty")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th><th style={{ ...th, textAlign: "right" }}>{t("purch.profit")}</th>
                    </tr></thead>
                    <tbody>
                      {d.products.map((p, i) => (
                        <tr key={i}>
                          <td style={{ ...td, fontWeight: 600 }}>{p.name}</td>
                          <td style={{ ...td, textAlign: "right" }} className="tabular">{p.qty}</td>
                          <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.cost)}</td>
                          <td style={{ ...td, textAlign: "right", fontWeight: 700, color: p.profit >= 0 ? "var(--ok)" : "var(--danger)" }} className="tabular">{fmt(p.profit)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.products.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("purch.noDeliveries")}</div>}
                </div>
              </div>

              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px 10px", fontSize: 15, fontWeight: 700 }}>{t("purch.purchaseHistory")}</div>
                <div style={{ maxHeight: 420, overflowY: "auto" }} className="no-sb">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr style={{ background: "var(--card-alt)" }}>
                      <th style={th}>{t("purch.thDoc")}</th><th style={th}>{t("purch.thDate")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th><th style={th}></th>
                    </tr></thead>
                    <tbody>
                      {d.recent_purchases.map((p) => (
                        <tr key={p.id}>
                          <td style={{ ...td, fontWeight: 700 }}>{p.doc_no}</td>
                          <td style={{ ...td, color: "var(--muted)" }}>{p.date}</td>
                          <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.total)}</td>
                          <td style={td}><span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 8, background: p.status === "debt" ? "var(--warn-soft)" : "var(--ok-soft)", color: p.status === "debt" ? "var(--warn)" : "var(--ok)" }}>{p.status === "debt" ? t("pay.credit") : t("purch.paid")}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.recent_purchases.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("purch.noKirim")}</div>}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      {payOpen && d && <PayDebt supplierId={id} balance={d.balance} onClose={() => setPayOpen(false)} onDone={() => { setPayOpen(false); detail.reload(); }} />}
      {editModal}
    </main>
  );
}

function PayDebt({ supplierId, balance, onClose, onDone }: { supplierId: string; balance: number; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [amount, setAmount] = useState(String(Math.round(balance)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function pay() {
    const a = +amount;
    if (!(a > 0)) { setErr(t("purch.enterAmount")); return; }
    setBusy(true); setErr("");
    try { await post(`/suppliers/${supplierId}/payments`, { amount: a, method: "cash", client_uuid: crypto.randomUUID() }); onDone(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Modal onClose={onClose} width={380}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{t("purch.payDebt")}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 14 }}>{t("purch.debt")}: <b style={{ color: "var(--danger)" }}>{fmt(balance)}</b></div>
      <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder="0" style={{ ...inputStyle, textAlign: "right", fontSize: 18 }} />
      {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 8 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={pay}>{busy ? "..." : t("purch.pay")}</button>
      </div>
    </Modal>
  );
}

// ═══ YETKAZIB BERUVCHILAR — TO'LIQ SAHIFA (ro'yxat + qo'shish, bosilsa batafsil) ═══
function SuppliersPage({ suppliers, onBack, onOpen, onAdd, newSupModal }: {
  suppliers: Supplier[]; onBack: () => void; onOpen: (id: string) => void; onAdd: () => void; newSupModal: React.ReactNode;
}) {
  const t = useT();
  const [q, setQ] = useState("");
  const qq = q.trim().toLowerCase();
  const rows = suppliers.filter((s) => !qq || s.name.toLowerCase().includes(qq) || (s.phone || "").includes(qq));
  const totalDebt = suppliers.reduce((a, s) => a + (s.balance > 0 ? s.balance : 0), 0);

  return (
    <main className="main">
      <Topbar title={t("purch.suppliers")} sub={t("purch.suppliersSub")} onBack={onBack}
        right={<button className="btn btn-primary" onClick={onAdd}>＋ {t("purch.newSupplier")}</button>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ maxWidth: 1000 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 18, marginBottom: 18 }}>
            <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.suppliers")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{suppliers.length}</div></div>
            <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.supplierDebt")}</div><div className="tabular" style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: totalDebt > 0 ? "var(--danger)" : "var(--ok)" }}>{fmt(totalDebt)}</div></div>
          </div>

          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("purch.searchSupplier")}
            style={{ ...inputStyle, marginBottom: 14, height: 46 }} />

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("purch.name")}</th><th style={th}>{t("cust.thPhone")}</th><th style={{ ...th, textAlign: "right" }}>{t("purch.debt")}</th><th style={{ ...th, width: 40 }}></th>
              </tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} onClick={() => onOpen(s.id)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td, fontWeight: 600 }}>{s.name}</td>
                    <td style={{ ...td, color: "var(--text3)" }}>{s.phone || "—"}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700, color: s.balance > 0 ? "var(--danger)" : s.balance < 0 ? "var(--accent-strong)" : "var(--ok)" }} className="tabular">{s.balance !== 0 ? (s.balance < 0 ? "+" : "") + fmt(Math.abs(s.balance)) : t("purch.clean")}</td>
                    <td style={{ ...td, textAlign: "center", color: "var(--faint)" }}>›</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("purch.noSuppliers")}</div>}
          </div>
        </div>
      </div>
      {newSupModal}
    </main>
  );
}
