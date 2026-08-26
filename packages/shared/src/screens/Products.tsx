import { useMemo, useState } from "react";
import {
  ArrowLeft,
  Barcode,
  Check,
  ClockCountdown,
  DotsThreeVertical,
  DownloadSimple,
  MagnifyingGlass,
  Package,
  PencilSimple,
  Plus,
  Prohibit,
  Warning,
  X,
} from "@phosphor-icons/react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, inputStyle, td, th, useGet } from "@/components/ui";
import { daysLeft, statusOf as statusOfShared, type StatusKey } from "@/lib/status";
import { useT } from "@/lib/i18n";

// Birlik kodini (dona/kg/litr/upak) joriy tilga o'giradi; noma'lum kod bo'lsa o'zini qaytaradi.
function unitL(t: (k: string) => string, u?: string | null): string {
  if (!u) return "";
  const v = t("unit." + u);
  return v.startsWith("unit.") ? u : v;
}

export interface Product {
  id: string; article_code: string; sku: string | null; name: string;
  category_id: string | null; base_buy_price: number; base_sell_price: number;
  stock: number; min_stock: number; unit_code: string | null; expiry_date: string | null;
  is_weighted?: boolean; plu_code?: string | null; scale_sync?: boolean; barcodes?: string[];
}
interface Category { id: string; name: string }

const STATUS: Record<StatusKey, { labelKey: string; color: string; soft: string }> = {
  ok: { labelKey: "prod.st_ok", color: "var(--ok)", soft: "var(--ok-soft)" },
  mid: { labelKey: "prod.st_mid", color: "var(--text3)", soft: "var(--surface)" },
  low: { labelKey: "prod.st_low", color: "var(--warn)", soft: "var(--warn-soft)" },
  soon: { labelKey: "prod.st_soon", color: "var(--warn)", soft: "var(--warn-soft)" },
  expired: { labelKey: "prod.st_expired", color: "var(--danger)", soft: "var(--danger-soft)" },
  out: { labelKey: "prod.st_out", color: "var(--danger)", soft: "var(--danger-soft)" },
};

const statusOf = (p: Product): StatusKey => statusOfShared(p);
function fmtDate(d: string | null): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  return `${String(dt.getDate()).padStart(2, "0")}.${String(dt.getMonth() + 1).padStart(2, "0")}.${dt.getFullYear()}`;
}

const TABS: { key: string; labelKey: string; match: (s: StatusKey) => boolean; Icon?: any }[] = [
  { key: "all", labelKey: "pos.all", match: () => true },
  { key: "low", labelKey: "prod.lowRunning", match: (s) => s === "low", Icon: Package },
  { key: "soon", labelKey: "prod.st_soon", match: (s) => s === "soon", Icon: ClockCountdown },
  { key: "expired", labelKey: "prod.st_expired", match: (s) => s === "expired", Icon: Prohibit },
  { key: "out", labelKey: "prod.st_out", match: (s) => s === "out", Icon: Warning },
];

export function Products() {
  const t = useT();
  const [arch, setArch] = useState(false);   // arxiv (is_active=false) ko'rinishi
  const products = useGet<Product[]>(arch ? "/products?archived=1" : "/products");
  const cats = useGet<Category[]>("/categories");
  const suppliers = useGet<{ id: string; name: string }[]>("/suppliers");
  async function archiveEmpty() {
    if (!window.confirm(t("prod.archiveEmptyConfirm"))) return;
    try { const r = await post<{ archived: number }>("/products/archive-empty", {}); products.reload(); window.alert(t("prod.archivedDone", { n: r.archived })); }
    catch (e: any) { window.alert(e.message); }
  }
  async function restore(id: string) {
    try { await api(`/products/${id}`, { method: "PATCH", body: JSON.stringify({ is_active: true }) }); products.reload(); }
    catch (e: any) { window.alert(e.message); }
  }
  const [q, setQ] = useState("");
  const [flt, setFlt] = useState("all");
  const [catFlt, setCatFlt] = useState("");     // kategoriya filtri
  const [detailId, setDetailId] = useState<string | null>(null); // mahsulot bosilsa — to'liq sahifa
  const [add, setAdd] = useState(false);        // yangi mahsulot — alohida sahifa
  const [imp, setImp] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [showTop, setShowTop] = useState(false); // "tepaga chiqish" tugmasi

  const list = products.data || [];
  const catName = (id: string | null) => (cats.data || []).find((c) => c.id === id)?.name || "—";

  // Skaner qidiruvi: skaner raqamlarni tez terib Enter yuboradi — aynan shu barcode'li
  // mahsulot topilsa darrov TO'LIQ sahifasi ochiladi.
  function onSearchEnter() {
    const code = q.trim();
    if (!/^\d{6,}$/.test(code)) return;
    const hit = list.find((p) => (p.barcodes || []).includes(code));
    if (hit) { setDetailId(hit.id); setQ(""); }
  }

  // Har mahsulotga holat + jonli sanagichlar (butun katalog bo'yicha)
  const withStatus = useMemo(() => list.map((p) => ({ p, s: statusOf(p) })), [list]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: list.length, low: 0, soon: 0, expired: 0, out: 0 };
    withStatus.forEach(({ s }) => { if (c[s] !== undefined) c[s]++; });
    return c;
  }, [withStatus, list.length]);

  const rows = useMemo(() => {
    const qq = q.trim().toLowerCase();
    const tab = TABS.find((tb) => tb.key === flt)!;
    return withStatus.filter(({ p, s }) =>
      tab.match(s) &&
      (!catFlt || p.category_id === catFlt) &&
      (!qq || p.name.toLowerCase().includes(qq) || p.article_code.includes(qq) || (p.sku || "").includes(qq) ||
        (p.barcodes || []).some((b) => b.includes(qq)))
    );
  }, [withStatus, q, flt, catFlt]);

  // Katta katalogda (masalan 8000 mahsulot) hammasini birdan render qilsak — UI qotadi.
  // Shuning uchun faqat birinchi LIMIT tasini ko'rsatamiz; qolganini qidiruv bilan topiladi.
  const LIMIT = 200;
  const shown = useMemo(() => rows.slice(0, LIMIT), [rows]);

  // ── Alohida sahifalar (mobiledagidek): qo'lda kirim / to'liq ma'lumot ──
  if (add) {
    return <FullReceiving cats={cats.data || []} products={list} suppliers={suppliers.data || []}
      onBack={() => setAdd(false)}
      onSaved={() => { setAdd(false); products.reload(); }} />;
  }
  if (detailId) {
    return <FullDetail productId={detailId} catName={catName}
      onBack={() => { setDetailId(null); products.reload(); }}
      onEdit={() => setEditId(detailId)}
      editModal={editId ? (
        <EditModal productId={editId} cats={cats.data || []} onClose={() => setEditId(null)}
          onSaved={() => { setEditId(null); products.reload(); }} />
      ) : null} />;
  }

  return (
    <main className="main">
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {arch && (
            <button className="btn btn-ghost" onClick={() => setArch(false)}
              style={{ display: "flex", alignItems: "center", gap: 7, height: 42 }}>
              <ArrowLeft size={17} weight="bold" />{t("prod.back")}
            </button>
          )}
          <div>
            <div className="h1">{arch ? t("prod.showArchive") : t("prod.title")}</div>
            <div className="sub">{t("prod.sub")}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {!arch && (
            <button className="btn btn-ghost" onClick={() => setArch(true)} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              {t("prod.showArchive")}
            </button>
          )}
          {!arch && <button className="btn btn-ghost" onClick={archiveEmpty} style={{ display: "flex", alignItems: "center", gap: 7 }}>{t("prod.archiveEmpty")}</button>}
          {/* Mahsulot qo'shish (kirim) endi faqat XARIDLAR bo'limidan — bu yerdan olib tashlandi */}
          <button className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setImp(true)}>
            <DownloadSimple size={17} />{t("prod.excelImport")}
          </button>
        </div>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
        <div id="prod-scroll" className="scroll" onScroll={(e) => setShowTop((e.target as HTMLDivElement).scrollTop > 400)} style={{ flex: 1, padding: 24 }}>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 18 }}>
            <SummaryCard Icon={Package} color="var(--accent-strong)" soft="var(--accent-soft)" label={t("prod.totalProducts")} value={counts.all} />
            <SummaryCard Icon={Warning} color="var(--warn)" soft="var(--warn-soft)" label={t("prod.lowRunning")} value={counts.low} />
            <SummaryCard Icon={ClockCountdown} color="var(--danger)" soft="var(--danger-soft)" label={t("prod.st_soon")} value={counts.soon} />
          </div>

          {/* Search + selects */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240, position: "relative" }}>
              <MagnifyingGlass size={17} color="var(--muted)" style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)" }} />
              <input value={q} onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onSearchEnter(); }}
                placeholder={t("prod.searchPlaceholder")}
                style={{ width: "100%", height: 48, padding: "0 44px 0 40px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--surface)", color: "var(--text)", font: "inherit", fontSize: 14, outline: "none" }} />
              {/* Skaner: kursorni shu maydonga qo'yib skanerlang — kod terilib Enter keladi */}
              <Barcode size={19} color="var(--accent-strong)" style={{ position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)" }} />
            </div>
            <CatFilter cats={cats.data || []} value={catFlt} onChange={setCatFlt} t={t} />
          </div>

          {/* Quick tabs */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {TABS.map((tb) => {
              const on = flt === tb.key;
              const n = counts[tb.key] ?? 0;
              return (
                <button key={tb.key} onClick={() => setFlt(tb.key)}
                  style={{ height: 36, padding: "0 13px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>
                  {tb.Icon && <tb.Icon size={15} />}{t(tb.labelKey)}
                  <span className="tabular" style={{ fontSize: 11.5, fontWeight: 700, padding: "1px 6px", borderRadius: 7, background: on ? "rgba(255,255,255,0.22)" : "var(--surface)", color: on ? "#fff" : "var(--muted)" }}>{n}</span>
                </button>
              );
            })}
          </div>

          {/* Table */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr style={{ background: "var(--card-alt)" }}>
                  <th style={th}>{t("sales.thProduct")}</th><th style={th}>{t("prod.thSku")}</th><th style={th}>{t("audit.f_category")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("prod.thStock")}</th><th style={{ ...th, textAlign: "right" }}>{t("prod.thMin")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("prod.sellPrice")}</th><th style={th}>{t("prod.thExpiry")}</th><th style={th}>{t("prod.thStatus")}</th><th style={{ ...th, width: 44 }}></th>
                </tr></thead>
                <tbody>
                  {shown.map(({ p, s }) => {
                    const st = STATUS[s];
                    const dl = daysLeft(p.expiry_date);
                    return (
                      <tr key={p.id} onClick={() => setDetailId(p.id)} style={{ cursor: "pointer" }}>
                        <td style={td}>
                          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                            <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700 }}>{p.name.charAt(0).toUpperCase()}</div>
                            <span style={{ fontWeight: 600 }}>{p.name}</span>
                          </div>
                        </td>
                        <td style={{ ...td, color: "var(--text3)" }} className="tabular">{p.sku || "—"}<div style={{ fontSize: 10.5, color: "var(--faint)" }}>{p.article_code}</div></td>
                        <td style={{ ...td, color: "var(--text3)" }}>{catName(p.category_id)}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700, color: s === "out" ? "var(--danger)" : "var(--text)" }} className="tabular">{p.stock} {unitL(t, p.unit_code)}</td>
                        <td style={{ ...td, textAlign: "right", color: "var(--muted)" }} className="tabular">{p.min_stock || "—"}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.base_sell_price)}</td>
                        <td style={{ ...td, color: dl !== null && dl <= 7 ? "var(--danger)" : "var(--text3)" }} className="tabular">{fmtDate(p.expiry_date)}</td>
                        <td style={td}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 9, background: st.soft, color: st.color }}>
                            <span style={{ width: 7, height: 7, borderRadius: "50%", background: st.color }} />{t(st.labelKey)}
                          </span>
                        </td>
                        <td style={td} onClick={(e) => { if (arch) { e.stopPropagation(); restore(p.id); } }}>{arch ? <span style={{ fontSize: 12, fontWeight: 700, color: "var(--accent-strong)", cursor: "pointer", whiteSpace: "nowrap" }}>{t("prod.restore")}</span> : <DotsThreeVertical size={18} color="var(--faint)" />}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && <div style={{ padding: 56, textAlign: "center", color: "var(--muted)" }}>{t("prod.nothingFound")}</div>}
            {rows.length > LIMIT && <div style={{ padding: "14px 20px", textAlign: "center", color: "var(--muted)", fontSize: 13, borderTop: "1px solid var(--border)" }}>{t("prod.capped", { shown: LIMIT, total: rows.length })}</div>}
          </div>
        </div>

        {/* Pastga tushganda — tepaga chiqish tugmasi (suzuvchi) */}
        {showTop && (
          <button onClick={() => document.getElementById("prod-scroll")?.scrollTo({ top: 0, behavior: "smooth" })}
            title={t("prod.toTop")}
            style={{ position: "absolute", right: 26, bottom: 26, width: 46, height: 46, borderRadius: "50%", border: "1px solid var(--accent-border)", background: "var(--accent)", color: "#fff", cursor: "pointer", boxShadow: "0 8px 22px rgba(0,0,0,0.28)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
            <ArrowLeft size={20} weight="bold" style={{ transform: "rotate(90deg)" }} />
          </button>
        )}
      </div>

      {imp && <ImportWizard onClose={() => setImp(false)} onDone={() => { setImp(false); products.reload(); }} />}
    </main>
  );
}

// Kategoriya filtri — custom dropdown (native select emas; scrollbar chizig'i yo'q)
function CatFilter({ cats, value, onChange, t }: { cats: Category[]; value: string; onChange: (v: string) => void; t: (k: string) => string }) {
  const [open, setOpen] = useState(false);
  const sel = cats.find((c) => c.id === value);
  const item = (id: string, name: string) => (
    <div key={id || "all"} onMouseDown={() => { onChange(id); setOpen(false); }}
      style={{ padding: "10px 14px", cursor: "pointer", fontSize: 13.5, whiteSpace: "nowrap",
        background: value === id ? "var(--accent-soft)" : "transparent",
        color: value === id ? "var(--accent-strong)" : "var(--text2)", fontWeight: value === id ? 700 : 500 }}>
      {name}
    </div>
  );
  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)} onBlur={() => setTimeout(() => setOpen(false), 160)}
        style={{ height: 48, minWidth: 200, padding: "0 14px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--card)", color: sel ? "var(--accent-strong)" : "var(--text3)", font: "inherit", fontSize: 13.5, fontWeight: sel ? 600 : 500, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{sel ? sel.name : t("prod.allCats")}</span>
        <span style={{ color: "var(--muted)", fontSize: 11 }}>▾</span>
      </button>
      {open && (
        <div className="no-sb" style={{ position: "absolute", top: "100%", right: 0, marginTop: 6, zIndex: 60, minWidth: 224, maxHeight: 360, overflowY: "auto", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, boxShadow: "0 16px 40px rgba(0,0,0,0.3)", padding: "4px 0" }}>
          {item("", t("prod.allCats"))}
          {cats.map((c) => item(c.id, c.name))}
        </div>
      )}
    </div>
  );
}

function SummaryCard({ Icon, color, soft, label, value }: { Icon: any; color: string; soft: string; label: string; value: number }) {
  return (
    <div className="card" style={{ padding: "15px 18px", display: "flex", alignItems: "center", gap: 14 }}>
      <div style={{ width: 42, height: 42, flex: "none", borderRadius: 11, background: soft, color, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Icon size={22} weight="fill" />
      </div>
      <div>
        <div className="tabular" style={{ fontSize: 24, fontWeight: 800, lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>{label}</div>
      </div>
    </div>
  );
}

interface ImportRow { name: string; category?: string; buy: number; sell: number; stock: number; barcode?: string }

function ImportWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState(1);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ total: number; new: number; existing: number; error: number; sample: { name: string; article: string; category: string; status: string }[]; rows: ImportRow[] } | null>(null);
  const [imported, setImported] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();

  const SAMPLE = "Coca-Cola 2L;Ichimliklar;90;130;60\nLipton 0.5L;Ichimliklar;50;75;40\nSnickers;Shirinliklar;60;90;100";

  function parseRows(): ImportRow[] {
    return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
      const [name, category, buy, sell, stock, barcode] = l.split(/[;\t]/).map((s) => (s || "").trim());
      return { name: name || "", category: category || undefined, buy: +buy || 0, sell: +sell || 0, stock: +stock || 0, barcode: barcode || undefined };
    });
  }
  async function goPreview() {
    setBusy(true); setErr("");
    try { const rows = parseRows(); const pv = await post<any>("/products/import/preview", { rows }); setPreview({ ...pv, rows }); setStep(2); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function commit() {
    if (!preview) return;
    setBusy(true); setErr("");
    try { const r = await post<{ imported: number }>("/products/import/commit", { rows: preview.rows }); setImported(r.imported); setStep(3); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const ST: Record<string, [string, string, string]> = { new: [t("prod.new"), "var(--ok-soft)", "var(--ok)"], existing: [t("prod.existing"), "var(--border)", "var(--muted)"], error: [t("common.error"), "var(--danger-soft)", "var(--danger)"] };

  return (
    <Modal onClose={onClose} width={560}>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, fontSize: 12.5, fontWeight: 700 }}>
        <span style={{ color: step >= 1 ? "var(--accent-strong)" : "var(--muted)" }}>1 · {t("prod.file")}</span>›
        <span style={{ color: step >= 2 ? "var(--accent-strong)" : "var(--muted)" }}>2 · {t("prod.check")}</span>›
        <span style={{ color: step >= 3 ? "var(--accent-strong)" : "var(--muted)" }}>3 · {t("prod.import")}</span>
      </div>

      {step === 1 && (
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>{t("prod.importTitle")}</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>{t("prod.eachRow")} <b>{t("prod.importFormat")}</b> {t("prod.semicolonSep")}</div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE} style={{ width: "100%", height: 160, padding: 12, border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 13, fontFamily: "monospace", outline: "none", boxSizing: "border-box", resize: "vertical", background: "var(--card)", color: "var(--text)" }} />
          <button onClick={() => setText(SAMPLE)} style={{ marginTop: 8, border: "none", background: "none", color: "var(--accent)", cursor: "pointer", fontWeight: 600, fontSize: 13 }}>{t("prod.fillSample")}</button>
          {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
            <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !text.trim()} onClick={goPreview}>{busy ? "..." : t("prod.continue")}</button>
          </div>
        </div>
      )}

      {step === 2 && preview && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
            {[[t("prod.total"), preview.total, "var(--text3)"], [t("prod.new"), preview.new, "var(--ok)"], [t("prod.existing"), preview.existing, "var(--muted)"], [t("common.error"), preview.error, "var(--danger)"]].map(([l, v, c]) => (
              <div key={l as string} style={{ background: "var(--surface)", borderRadius: 12, padding: 12, textAlign: "center" }}>
                <div className="tabular" style={{ fontSize: 20, fontWeight: 800, color: c as string }}>{v as number}</div>
                <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{l as string}</div>
              </div>
            ))}
          </div>
          <div style={{ maxHeight: 220, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 12 }}>
            {preview.sample.map((r, i) => {
              const s = ST[r.status] || ["?", "var(--surface)", "var(--muted)"];
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderTop: i ? "1px solid var(--border-soft)" : "none", fontSize: 13 }}>
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 8, background: s[1], color: s[2] }}>{s[0]}</span>
                </div>
              );
            })}
          </div>
          {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setStep(1)}>{t("prod.back")}</button>
            <button className="btn btn-primary" style={{ flex: 2 }} disabled={busy} onClick={commit}>{busy ? "..." : t("prod.importN", { n: preview.new })}</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ textAlign: "center", padding: "10px 0" }}>
          <div style={{ width: 66, height: 66, margin: "0 auto 8px", borderRadius: "50%", background: "var(--ok-soft)", color: "var(--ok)", display: "flex", alignItems: "center", justifyContent: "center" }}><Plus size={32} weight="bold" /></div>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>{t("prod.importDone")}</div>
          <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 6 }}>{t("prod.importedN", { n: imported })}</div>
          <button className="btn btn-primary" style={{ width: "100%", marginTop: 20, height: 48 }} onClick={onDone}>{t("prod.openList")}</button>
        </div>
      )}
    </Modal>
  );
}

function EditModal({ productId, cats, onClose, onSaved }: { productId: string; cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const detail = useGet<Product & { created_by_name: string; created_at: string }>(`/products/${productId}`);
  const d = detail.data;
  const [name, setName] = useState("");
  const [cat, setCat] = useState("");
  const [buy, setBuy] = useState("");
  const [sell, setSell] = useState("");
  const [min, setMin] = useState("");
  const [expiry, setExpiry] = useState("");
  const [weighed, setWeighed] = useState(false);
  const [plu, setPlu] = useState("");
  const [sync, setSync] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (d && !loaded) {
    setName(d.name); setCat(d.category_id || ""); setBuy(String(d.base_buy_price));
    setSell(String(d.base_sell_price)); setMin(String(d.min_stock || "")); setExpiry(d.expiry_date || "");
    setWeighed(!!d.is_weighted); setPlu(d.plu_code || ""); setSync(d.scale_sync !== false);
    setLoaded(true);
  }

  async function save() {
    if (weighed && !plu.trim()) { setErr(t("prod2.pluUnique")); return; }
    setBusy(true); setErr("");
    try {
      await api(`/products/${productId}`, { method: "PATCH", body: JSON.stringify({ name, category_id: cat, buy_price: +buy || 0, sell_price: +sell || 0, min_qty: +min || 0, expiry_date: expiry || "", is_weighted: weighed, plu_code: weighed ? plu : "", scale_sync: weighed ? sync : false, ...(weighed ? { unit_code: "kg" } : {}) }) });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(t("cust.deleteConfirm", { name }))) return;
    setBusy(true); setErr("");
    try { await api(`/products/${productId}`, { method: "DELETE" }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{t("prod.editProduct")}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)" }} className="tabular">{d?.article_code || ""}</div>
      {d && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 16px", padding: "8px 12px", background: "var(--surface)", borderRadius: 9 }}>
          {t("prod.addedBy")} <b style={{ color: "var(--text2)" }}>{d.created_by_name}</b>{d.created_at ? ` · ${new Date(d.created_at).toLocaleDateString("ru-RU")}` : ""}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("prod.namePlaceholder")} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          <option value="">{t("prod.pickCategory")}</option>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.arrivalPrice")} style={inputStyle} />
          <input value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.salePricePh")} style={inputStyle} />
        </div>
        <SaleTypeSection t={t} weighed={weighed} setWeighed={setWeighed} plu={plu} setPlu={setPlu} sync={sync} setSync={setSync} />
        <div style={{ display: "flex", gap: 10 }}>
          <input value={min} onChange={(e) => setMin(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.minStock")} style={inputStyle} />
          <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} style={inputStyle} />
        </div>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>{t("prod.delete")}</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function SaleTypeSection({ t, weighed, setWeighed, plu, setPlu, sync, setSync }: { t: (k: string, v?: any) => string; weighed: boolean; setWeighed: (v: boolean) => void; plu: string; setPlu: (v: string) => void; sync: boolean; setSync: (v: boolean) => void }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 14, background: "var(--surface)" }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text3)", marginBottom: 10 }}>{t("prod2.saleType")}</div>
      <div style={{ display: "flex", gap: 8 }}>
        {([["unit", t("prod2.byUnit")], ["weight", t("prod2.byWeight")]] as const).map(([k, l]) => {
          const on = (k === "weight") === weighed;
          return <button key={k} type="button" onClick={() => setWeighed(k === "weight")} style={{ flex: 1, height: 42, borderRadius: 10, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, border: `1.5px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent-soft)" : "var(--card)", color: on ? "var(--accent-strong)" : "var(--muted)" }}>{l}</button>;
        })}
      </div>
      {weighed && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          <div>
            <label style={{ fontSize: 12, color: "var(--text3)", fontWeight: 600 }}>{t("prod2.plu")}</label>
            <input value={plu} onChange={(e) => setPlu(e.target.value.replace(/\D/g, ""))} placeholder="123" style={{ ...inputStyle, marginTop: 5 }} />
          </div>
          <div style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.4 }}>{t("prod2.priceIsPerKg")}</div>
          <label style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
            <input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} style={{ width: 16, height: 16, accentColor: "var(--accent)" }} />
            <span style={{ fontSize: 13, color: "var(--text2)", fontWeight: 500 }}>{t("prod2.syncToScaleHint")}</span>
          </label>
        </div>
      )}
    </div>
  );
}

// ═══ TO'LIQ MA'LUMOT SAHIFASI (mobiledagidek: narxlar + statistika + harakatlar) ═══
interface FullD {
  id: string; name: string; sku: string | null; article_code: string; category_id: string | null;
  base_buy_price: number; base_sell_price: number; profit_unit: number; margin_pct: number;
  stock: number; min_stock: number; unit_code: string | null; expiry_date: string | null;
  sales_7d: { qty: number; revenue: number; profit: number };
  sales_30d: { qty: number; revenue: number; profit: number };
  last_sold_at: string | null; month_in: number; month_out: number;
  is_weighted: boolean; plu_code: string | null; barcodes: string[]; created_by_name: string;
}
interface MoveR { type: string; direction: string; qty: number; at: string | null; employee?: string }

function FullDetail({ productId, catName, onBack, onEdit, editModal }: {
  productId: string; catName: (id: string | null) => string;
  onBack: () => void; onEdit: () => void; editModal: React.ReactNode;
}) {
  const t = useT();
  const detail = useGet<FullD>(`/products/${productId}`);
  const moves = useGet<MoveR[]>(`/inventory/movements?limit=30&product_id=${productId}`);
  const d = detail.data;

  const Stat = ({ label, value, color }: { label: string; value: string; color?: string }) => (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{label}</div>
      <div className="tabular" style={{ fontSize: 19, fontWeight: 800, marginTop: 5, color: color || "var(--text)" }}>{value}</div>
    </div>
  );
  const StatBlock = ({ title, s }: { title: string; s: { qty: number; revenue: number; profit: number } }) => (
    <div className="card" style={{ padding: "14px 18px" }}>
      <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 10 }}>{title}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
        <div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("prod.sold")}</div><div className="tabular" style={{ fontSize: 16, fontWeight: 800, marginTop: 3 }}>{s.qty}</div></div>
        <div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("prod.revenue")}</div><div className="tabular" style={{ fontSize: 16, fontWeight: 800, marginTop: 3 }}>{fmt(s.revenue)}</div></div>
        <div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("prod.profit")}</div><div className="tabular" style={{ fontSize: 16, fontWeight: 800, marginTop: 3, color: s.profit >= 0 ? "var(--ok)" : "var(--danger)" }}>{fmt(s.profit)}</div></div>
      </div>
    </div>
  );

  return (
    <main className="main">
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
          <button className="btn btn-ghost" onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 7, height: 42, flex: "none" }}>
            <ArrowLeft size={17} weight="bold" />{t("prod.back")}
          </button>
          <div style={{ minWidth: 0 }}>
            <div className="h1" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d?.name || "…"}</div>
            <div className="sub tabular">SKU {d?.sku || "—"} · {d?.article_code || ""} · {catName(d?.category_id || null)}</div>
          </div>
        </div>
        <button className="btn btn-primary" onClick={onEdit} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <PencilSimple size={17} />{t("cust.edit")}
        </button>
      </header>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {!d ? (
          <div style={{ color: "var(--muted)" }}>{t("common.loading")}</div>
        ) : (
          <div style={{ maxWidth: 980, display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
              <Stat label={t("prod.buyPrice")} value={fmt(d.base_buy_price)} />
              <Stat label={t("prod.sellPrice")} value={fmt(d.base_sell_price)} color="var(--accent-strong)" />
              <Stat label={t("prod.profitUnit")} value={fmt(d.profit_unit)} color={d.profit_unit >= 0 ? "var(--ok)" : "var(--danger)"} />
              <Stat label={t("prod.margin")} value={`${d.margin_pct}%`} color={d.profit_unit >= 0 ? "var(--ok)" : "var(--danger)"} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
              <Stat label={t("prod.stockInWarehouse")} value={`${d.stock} ${unitL(t, d.unit_code)}`} color={d.stock <= 0 ? "var(--danger)" : undefined} />
              <Stat label={t("prod.stockValue")} value={fmt(d.stock * d.base_buy_price)} />
              <Stat label={t("prod.monthIn")} value={`+${d.month_in}`} color="var(--ok)" />
              <Stat label={t("prod.monthOut")} value={`−${d.month_out}`} color="var(--danger)" />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <StatBlock title={t("prod.stat30")} s={d.sales_30d} />
              <StatBlock title={t("prod.stat7")} s={d.sales_7d} />
            </div>
            {d.last_sold_at && (
              <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("prod.lastSold")}: {new Date(d.last_sold_at).toLocaleString("ru-RU")}</div>
            )}
            {d.barcodes.length > 0 && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {d.barcodes.map((b) => (
                  <span key={b} className="tabular" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "5px 10px", borderRadius: 8, background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text3)" }}>
                    <Barcode size={14} />{b}
                  </span>
                ))}
                {d.is_weighted && d.plu_code && <span style={{ fontSize: 12, fontWeight: 700, padding: "5px 10px", borderRadius: 8, background: "var(--accent-soft)", color: "var(--accent-strong)" }}>PLU {d.plu_code}</span>}
              </div>
            )}
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "16px 20px 10px", fontSize: 15, fontWeight: 700 }}>{t("prod.movements")}</div>
              {(moves.data || []).length === 0 ? (
                <div style={{ padding: "10px 20px 20px", color: "var(--muted)", fontSize: 13 }}>{t("prod.noMoves")}</div>
              ) : (
                <div>
                  {(moves.data || []).map((m, i) => {
                    const incoming = m.direction === "in";
                    return (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 20px", borderTop: "1px solid var(--border-soft)", fontSize: 13 }}>
                        <span style={{ color: incoming ? "var(--ok)" : "var(--danger)", fontWeight: 800 }}>{incoming ? "↓" : "↑"}</span>
                        <span style={{ flex: 1 }}>{m.type}</span>
                        {m.employee && <span style={{ color: "var(--muted)", fontSize: 12 }}>{m.employee}</span>}
                        <span className="tabular" style={{ fontWeight: 700, color: incoming ? "var(--ok)" : "var(--danger)" }}>{incoming ? "+" : "−"}{m.qty}</span>
                        <span className="tabular" style={{ color: "var(--faint)", fontSize: 12, width: 118, textAlign: "right" }}>{m.at ? new Date(m.at).toLocaleString("ru-RU") : ""}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--faint)" }}>{t("prod.addedBy")} {d.created_by_name}</div>
          </div>
        )}
      </div>
      {editModal}
    </main>
  );
}

// ═══ QO'LDA KIRIM — ALOHIDA SAHIFA (qatorli jadval: har qator to'ldirilib ✓ bilan tasdiqlanadi) ═══
interface RRow {
  key: number; confirmed: boolean; productId: string | null;
  name: string; barcode: string; catId: string; cost: string; sell: string; qty: string; unit: string;
  stock: number | null;
}
const UNITS = ["dona", "kg", "litr", "upak"];
const emptyRow = (key: number): RRow => ({ key, confirmed: false, productId: null, name: "", barcode: "", catId: "", cost: "", sell: "", qty: "", unit: "dona", stock: null });

export function FullReceiving({ cats, products, suppliers, onBack, onSaved }: {
  cats: Category[]; products: Product[]; suppliers: { id: string; name: string }[];
  onBack: () => void; onSaved: () => void;
}) {
  const t = useT();
  const [supplierId, setSupplierId] = useState("");
  const [payment, setPayment] = useState<"cash" | "credit">("cash");
  const [rows, setRows] = useState<RRow[]>([]);
  const [seq, setSeq] = useState(1);
  const [focusKey, setFocusKey] = useState<number | null>(null); // nom-autocomplete uchun faol qator
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Kirim payti yangi yetkazib beruvchi qo'shish (inline)
  const [extraSups, setExtraSups] = useState<{ id: string; name: string }[]>([]);
  const [newSupOpen, setNewSupOpen] = useState(false);
  const [newSupName, setNewSupName] = useState("");
  const allSups = [...suppliers, ...extraSups];
  async function addSupplier() {
    const nm = newSupName.trim();
    if (!nm) return;
    try {
      const s = await post<{ id: string; name: string }>("/suppliers", { name: nm });
      setExtraSups((e) => [...e, { id: s.id, name: s.name }]);
      setSupplierId(s.id);
      setNewSupName(""); setNewSupOpen(false);
    } catch (e: any) { setErr(e.message); }
  }

  const catName = (id: string) => cats.find((c) => c.id === id)?.name || "—";
  const setRow = (key: number, patch: Partial<RRow>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRow = () => { setRows((rs) => [...rs, emptyRow(seq)]); setSeq((s) => s + 1); };
  const removeRow = (key: number) => setRows((rs) => rs.filter((r) => r.key !== key));

  // Qator faqat to'liq to'lganda tasdiqlanadi (barcha maydon shart; barcode "Avtomatik" bo'lishi mumkin)
  function confirmRow(key: number) {
    const r = rows.find((x) => x.key === key)!;
    if (!r.name.trim()) return setErr(t("recv.needName"));
    if (!r.catId) return setErr(t("recv.needCat"));
    if (!(+r.cost > 0)) return setErr(t("recv.needBuy"));
    if (!(+r.sell > 0)) return setErr(t("recv.needSell"));
    if (!(+r.qty > 0)) return setErr(t("recv.needQty"));
    setErr("");
    setRow(key, { confirmed: true });
  }

  // Skanerlangan/terilgan barcode: mavjud bo'lsa avto-to'ldiradi
  function onBarcode(key: number, v: string) {
    const c = v.replace(/\D/g, "");
    const hit = c.length >= 6 ? products.find((p) => (p.barcodes || []).includes(c)) || null : null;
    if (hit) fillFrom(key, hit, c);
    else setRow(key, { barcode: c, productId: null });
  }
  // Mavjud mahsulotdan avto-to'ldirish (nom, kategoriya, narxlar, qoldiq + BARCODE)
  function fillFrom(key: number, p: Product, keepBarcode = "") {
    setRow(key, {
      productId: p.id, name: p.name, catId: p.category_id || "",
      cost: p.base_buy_price ? String(Math.round(p.base_buy_price)) : "",
      sell: p.base_sell_price ? String(Math.round(p.base_sell_price)) : "",
      unit: p.unit_code || "dona", stock: p.stock,
      // Skanerlangan kod bo'lsa o'sha; aks holda mahsulotning mavjud barkodi (bo'lsa)
      barcode: keepBarcode || (p.barcodes && p.barcodes[0]) || "",
    });
    setFocusKey(null);
  }

  const total = rows.filter((r) => r.confirmed).reduce((s, r) => s + (+r.qty || 0) * (+r.cost || 0), 0);

  async function save() {
    const ready = rows.filter((r) => r.confirmed);
    if (!ready.length) { setErr(t("recv.needItems")); return; }
    setBusy(true); setErr("");
    try {
      await post("/receiving/commit", {
        items: ready.map((r) => ({
          product_id: r.productId || null,
          new_name: r.productId ? null : r.name.trim(),
          new_sell_price: r.sell !== "" ? +r.sell : null,
          new_category_id: !r.productId && r.catId ? r.catId : null,
          new_barcode: r.barcode || null,
          qty: +r.qty || 0, unit_cost: +r.cost || 0, unit: r.unit,
        })),
        supplier_id: supplierId || null, payment, source: "manual", client_uuid: crypto.randomUUID(),
      });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const cellIn: React.CSSProperties = { width: "100%", boxSizing: "border-box", background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border-input)", borderRadius: 9, padding: "9px 10px", font: "inherit", fontSize: 13, outline: "none" };
  const GRID = "1.8fr 1.4fr 1.2fr .95fr .95fr .7fr .95fr 72px";

  return (
    <main className="main">
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button className="btn btn-ghost" onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 7, height: 42 }}>
            <ArrowLeft size={17} weight="bold" />{t("prod.back")}
          </button>
          <div><div className="h1">{t("recv.title")}</div><div className="sub">{t("prod.sub")}</div></div>
        </div>
      </header>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {/* Yetkazib beruvchi — tanlash yoki inline yangi qo'shish */}
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--muted)" }}>{t("recv.supplier")}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 6, marginBottom: 22, alignItems: "center", flexWrap: "wrap" }}>
          {!newSupOpen ? (
            <>
              <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} style={{ ...cellIn, width: 300, height: 44 }}>
                <option value="">{t("recv.notSelected")}</option>
                {allSups.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <button onClick={() => setNewSupOpen(true)} className="btn btn-ghost" style={{ height: 44, display: "flex", alignItems: "center", gap: 6 }}>
                <Plus size={16} weight="bold" />{t("purch.newSupplier")}
              </button>
            </>
          ) : (
            <>
              <input value={newSupName} autoFocus placeholder={t("purch.name")}
                onChange={(e) => setNewSupName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") addSupplier(); if (e.key === "Escape") { setNewSupOpen(false); setNewSupName(""); } }}
                style={{ ...cellIn, width: 300, height: 44 }} />
              <button onClick={addSupplier} className="btn btn-primary" style={{ height: 44 }}>{t("common.save")}</button>
              <button onClick={() => { setNewSupOpen(false); setNewSupName(""); }} className="btn btn-ghost" style={{ height: 44 }}>{t("common.cancel")}</button>
            </>
          )}
        </div>

        {/* Jadval — overflow visible: nom-autocomplete taklifi kesilmasin */}
        <div style={{ border: "1px solid var(--border)", borderRadius: 13 }}>
          <div style={{ display: "grid", gridTemplateColumns: GRID, background: "var(--card-alt)", borderRadius: "12px 12px 0 0" }}>
            {[t("prod.namePlaceholder"), "Barcode", t("audit.f_category"), t("prod.buyPrice"), t("prod.sellPrice"), t("recv.qty"), t("recv.unit"), ""].map((h, i) => (
              <div key={i} style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)", padding: "12px 11px", textAlign: i >= 3 && i <= 5 ? "right" : "left" }}>{h}</div>
            ))}
          </div>

          {rows.length === 0 && (
            <div style={{ padding: "30px 0", textAlign: "center", color: "var(--muted)", fontSize: 13.5, borderTop: "1px solid var(--border)" }}>{t("recv.noProducts")}</div>
          )}

          {rows.map((r) => {
            if (r.confirmed) {
              // Tasdiqlangan qator — matn ko'rinishi + qalamcha (tahrirlash) + o'chirish
              return (
                <div key={r.key} style={{ display: "grid", gridTemplateColumns: GRID, borderTop: "1px solid var(--border)", background: "rgba(53,208,138,0.05)", alignItems: "center" }}>
                  <div style={{ padding: "11px 11px", fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                    {!r.productId && <span style={{ fontSize: 9.5, fontWeight: 700, color: "var(--accent-strong)", background: "var(--accent-soft)", padding: "1px 6px", borderRadius: 6, flex: "none" }}>{t("prod.new")}</span>}
                  </div>
                  <div style={{ padding: "11px 11px", fontSize: 12, fontFamily: "monospace", color: r.barcode ? "var(--text3)" : "var(--faint)", fontStyle: r.barcode ? "normal" : "italic" }}>{r.barcode || t("recv.auto")}</div>
                  <div style={{ padding: "11px 11px", fontSize: 12.5, color: "var(--text3)" }}>{catName(r.catId)}</div>
                  <div style={{ padding: "11px 11px", fontSize: 13, textAlign: "right" }} className="tabular">{fmt(+r.cost)}</div>
                  <div style={{ padding: "11px 11px", fontSize: 13, textAlign: "right" }} className="tabular">{fmt(+r.sell)}</div>
                  <div style={{ padding: "11px 11px", fontSize: 13, textAlign: "right", fontWeight: 700 }} className="tabular">{r.qty}</div>
                  <div style={{ padding: "11px 11px", fontSize: 12.5, color: "var(--text3)" }}>{unitL(t, r.unit)}</div>
                  <div style={{ padding: "8px 8px", display: "flex", gap: 4, justifyContent: "center" }}>
                    <button onClick={() => setRow(r.key, { confirmed: false })} title={t("cust.edit")} style={{ width: 30, height: 30, border: "none", background: "var(--surface)", borderRadius: 8, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><PencilSimple size={15} /></button>
                    <button onClick={() => removeRow(r.key)} title={t("prod.delete")} style={{ width: 30, height: 30, border: "none", background: "var(--surface)", borderRadius: 8, cursor: "pointer", color: "var(--faint)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={14} /></button>
                  </div>
                </div>
              );
            }
            // Tahrirlanayotgan qator — inputlar + ✓ tasdiqlash + ✕
            const q = r.name.trim().toLowerCase();
            const sug = focusKey === r.key && !r.productId && q.length >= 2 ? products.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 7) : [];
            return (
              <div key={r.key} style={{ display: "grid", gridTemplateColumns: GRID, borderTop: "1px solid var(--border)", alignItems: "center" }}>
                <div style={{ padding: "8px 8px", position: "relative" }}>
                  <input value={r.name} placeholder={t("recv.namePh")} style={cellIn}
                    onFocus={() => setFocusKey(r.key)} onBlur={() => setTimeout(() => setFocusKey((k) => (k === r.key ? null : k)), 150)}
                    onChange={(e) => {
                      const v = e.target.value;
                      // Skaner kursor nom maydonida bo'lsa ham ishlasin: sof raqam (8+ xona) -> barcode
                      if (/^\d{8,}$/.test(v.trim())) { onBarcode(r.key, v.trim()); return; }
                      setRow(r.key, { name: v, productId: null, stock: null });
                    }} />
                  {sug.length > 0 && (
                    <div className="no-sb" style={{ position: "absolute", left: 8, right: 8, top: "100%", zIndex: 40, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "0 14px 34px rgba(0,0,0,0.28)", maxHeight: 260, overflowY: "auto" }}>
                      {sug.map((p) => (
                        <div key={p.id} onMouseDown={() => fillFrom(r.key, p)} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "9px 12px", cursor: "pointer", fontSize: 13, borderTop: "1px solid var(--border-soft)" }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
                          <span className="tabular" style={{ color: "var(--muted)", flex: "none" }}>{fmt(p.base_sell_price)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {r.stock !== null && <div style={{ fontSize: 11, color: "var(--ok)", fontWeight: 600, marginTop: 3, paddingLeft: 2 }}>{t("recv.stock")}: {r.stock}</div>}
                </div>
                <div style={{ padding: "8px 8px" }}>
                  <input value={r.barcode} placeholder={t("recv.auto")} inputMode="numeric" onChange={(e) => onBarcode(r.key, e.target.value)}
                    style={{ ...cellIn, fontFamily: "monospace", fontSize: 12 }} />
                </div>
                <div style={{ padding: "8px 8px" }}>
                  <select value={r.catId} onChange={(e) => setRow(r.key, { catId: e.target.value })} style={cellIn}>
                    <option value="">{t("prod.pickCategory")}</option>
                    {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div style={{ padding: "8px 8px" }}><input value={r.cost} onChange={(e) => setRow(r.key, { cost: e.target.value.replace(/\D/g, "") })} placeholder="0" style={{ ...cellIn, textAlign: "right" }} /></div>
                <div style={{ padding: "8px 8px" }}><input value={r.sell} onChange={(e) => setRow(r.key, { sell: e.target.value.replace(/\D/g, "") })} placeholder="0" style={{ ...cellIn, textAlign: "right" }} /></div>
                <div style={{ padding: "8px 8px" }}><input value={r.qty} onChange={(e) => setRow(r.key, { qty: e.target.value.replace(/[^\d.]/g, "") })} placeholder="0" style={{ ...cellIn, textAlign: "right" }} /></div>
                <div style={{ padding: "8px 8px" }}>
                  <select value={r.unit} onChange={(e) => setRow(r.key, { unit: e.target.value })} style={cellIn}>
                    {UNITS.map((u) => <option key={u} value={u}>{unitL(t, u)}</option>)}
                  </select>
                </div>
                <div style={{ padding: "8px 8px", display: "flex", gap: 4, justifyContent: "center" }}>
                  <button onClick={() => confirmRow(r.key)} title={t("recv.confirm")} style={{ width: 32, height: 32, border: "none", background: "var(--ok)", borderRadius: 9, cursor: "pointer", color: "#06231a", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 3px 10px rgba(53,208,138,0.35)" }}><Check size={16} weight="bold" /></button>
                  <button onClick={() => removeRow(r.key)} style={{ width: 30, height: 30, border: "none", background: "var(--surface)", borderRadius: 8, cursor: "pointer", color: "var(--faint)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={14} /></button>
                </div>
              </div>
            );
          })}
        </div>

        <button onClick={addRow}
          style={{ marginTop: 12, width: "100%", border: "1.5px dashed var(--accent-border)", background: "var(--surface)", color: "var(--accent-ink)", borderRadius: 12, padding: "13px", cursor: "pointer", fontWeight: 700, fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, font: "inherit" }}>
          <Plus size={18} weight="bold" />{t("recv.addProduct")}
        </button>

        <div style={{ marginTop: 14, fontSize: 12.5, color: "var(--muted)" }}>💡 {t("recv.hint")}</div>
        {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 10, fontWeight: 600 }}>{err}</div>}

        {/* Pastki panel */}
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 8 }}>
            {(["cash", "credit"] as const).map((k) => {
              const on = payment === k;
              return <button key={k} onClick={() => setPayment(k)} style={{ height: 44, padding: "0 18px", borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 700, border: `1.5px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent-soft)" : "var(--card)", color: on ? "var(--accent-strong)" : "var(--muted)" }}>{k === "cash" ? t("recv.paid") : t("recv.credit")}</button>;
            })}
          </div>
          <div style={{ flex: 1 }} />
          <div className="tabular" style={{ fontSize: 22, fontWeight: 800 }}>{fmt(total)}</div>
        </div>
        <button className="btn btn-primary" disabled={busy || total === 0} onClick={save} style={{ marginTop: 12, width: "100%", height: 50, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 15 }}>
          <Check size={19} weight="bold" />{busy ? "..." : t("recv.save")}
        </button>
      </div>
    </main>
  );
}
