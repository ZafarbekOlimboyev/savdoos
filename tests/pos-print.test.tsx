import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { POSKassa } from "@/screens/POSKassa";
import { PrintStatus, printErrorReason, usePrintDoc, type PrintTarget } from "@/components/PrintStatus";
import { translate } from "@/lib/i18n";
import { useLang, type Lang } from "@/store/lang";
import { routes as posAppRoutes } from "../apps/pos/src/App";
import { Sotuvlarim } from "@/screens/Sotuvlarim";
import { Sales } from "@/screens/Sales";
import { Returns } from "@/screens/Returns";
import { ReturnsOversight } from "@/screens/ReturnsOversight";
import { _resetPrintRuntime, docKey, listJobs, printDoc } from "@/lib/printing";
import { readPrinterConfig } from "@/lib/printerConfig";
import { _resetSyncTimers, flushOutbox, submitSale, syncTick } from "@/lib/sync";
import { CACHE, cacheSet, nsKey, outboxAdd, outboxAll } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { BUILTIN_TEMPLATE, docToText, provisionalSaleReceipt, type ReceiptDTO } from "@/receipt";
import type { VirtualPrintRequest } from "@/print/bridge";
import { returnDto, saleDto, smallDto, tpl } from "./__golden__/receipt/fixtures";
import { mockApi, renderApp, type Call } from "./util";

// Phase 5F F4: POS/Manager ekranlarining chek chop etishi. Asosiy invariant: chop etish SOTUVDAN
// KEYINGI yon ta'sir — printer xatosi sotuv holatini/savatni o'zgartirmaydi, sotuvni qayta yubormaydi,
// "Yangi savdo"ni to'smaydi. Onlayn chek SERVER DTO'sidan, oflayn — aynan yuborilgan payload'dan.

const SALE_ID = saleDto().doc.id as string;
const ORIGINAL_EXISTS = "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting";

const NON: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 2, article: "A-1" };
const POMIDOR: CartLine = { id: "p2", name: "Pomidor", price: 12000, qty: 0.352, weighted: true, article: "A-2" };
const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona" },
  { id: "p2", article_code: "A-2", name: "Pomidor", category_id: null, base_sell_price: 12000, stock: 50, unit_code: "kg", is_weighted: true },
];
const TOTAL = 12224; // 2×4000 + 0.352×12000

/** Server DTO: kassa ekranidan FARQLI kassir nomi — chek serverdan chizilganini isbotlaydi. */
function serverDto(payments: ReceiptDTO["payments"]): ReceiptDTO {
  const d = smallDto();
  return {
    ...d, logo: null, barcode: null, qr: null, customer: null, payments,
    actor: { cashier: "Dilnoza Karimova (server)", till_code: "K-01", terminal: null },
    template: tpl(),
  };
}

const profile = (over: Record<string, unknown> = {}) => ({
  etag: "etag-pos", branch_id: "b1",
  effective: { ...BUILTIN_TEMPLATE, printer: null, logo_id: null, qr_url: null, ...over },
  store: { name: "Fayzan Market", branch_name: "Chilonzor filiali", address: null, phone: null, stir: null },
  logo: null, store_qr: null,
});

let settings: Record<string, unknown> = {};
let serverJobs = new Map<string, any>();
let printed: VirtualPrintRequest[] = [];
let printerAnswer: (req: VirtualPrintRequest) => any = () => ({ ok: true });

function jobOut(body: any) {
  const prev = serverJobs.get(body.id);
  const copy = prev?.copy ?? body.copy ?? "ORIGINAL";
  const docId = prev?.doc_id ?? body.doc_id;
  const copyNo = prev?.copy_no ?? (copy === "REPRINT"
    ? [...serverJobs.values()].filter((j) => j.doc_id === docId && j.copy === "REPRINT").length + 1 : 0);
  const out = {
    id: body.id, doc_type: prev?.doc_type ?? body.doc_type, doc_id: docId, copy, copy_no: copyNo,
    status: body.status ?? prev?.status ?? "PENDING", attempts: Math.max(prev?.attempts ?? 0, body.attempts ?? 0),
    error: body.error ?? null, printer: null, transport: body.transport ?? null,
    created_at: "2026-09-19T09:40:00+00:00", updated_at: "2026-09-19T09:40:00+00:00", printed_at: null,
  };
  serverJobs.set(body.id, out);
  return out;
}

/** mockApi + server `X-Error-Code` (chop etish jurnali qarori matn emas, KOD bo'yicha). */
function server(routes: [RegExp, any][]): Call[] {
  const calls = mockApi(routes);
  const inner = globalThis.fetch;
  vi.stubGlobal("fetch", async (url: string, opts?: RequestInit) => {
    const res = await inner(url, opts);
    if (res.status < 400) return res;
    const text = await res.text();
    const detail = (() => { try { return JSON.parse(text).detail; } catch { return ""; } })();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (detail === ORIGINAL_EXISTS) headers["X-Error-Code"] = "PRINT_ORIGINAL_EXISTS";
    return new Response(text, { status: res.status, headers });
  });
  return calls;
}

/** POS ekrani uchun marshrutlar; `over` — birinchi mos keladi. */
function posRoutes(over: [RegExp, any][] = []): [RegExp, any][] {
  return [
    ...over,
    [/\/products\?include_archived=1/, PRODUCTS],
    [/\/categories/, []],
    [/\/settings$/, () => settings],
    [/\/customers$/, [{ id: "cu1", code: "M-1", full_name: "Aliyev Vali", phone: null }]],
    [/\/receipt\/profile/, profile()],
    [/\/sales\/[^/?]+\/receipt/, serverDto([{ method: "cash", amount: "12224.00", given: "12224.00", change: "0.00" }])],
    [/\/sales$/, { id: SALE_ID, receipt_no: "#1288", uid: "2609191288", sold_at: "2026-09-19T09:32:11+00:00" }],
    [/\/print-jobs\?/, []],
    [/\/print-jobs\/[^/?]+$/, (c: Call) => jobOut({ ...c.body, id: c.url.split("/").pop() })],
    [/\/print-jobs$/, (c: Call) => jobOut(c.body)],
  ];
}

const writes = (calls: Call[], re: RegExp) => calls.filter((c) => c.method !== "GET" && re.test(c.url));
const text = (req: VirtualPrintRequest) => docToText(req.doc).join("\n");
/** Bo'shliqsiz matn: ikki barobar (size 2) satr "J A M I" bo'lib chiqadi — solishtirish oson bo'lsin. */
const flat = (req: VirtualPrintRequest) => text(req).replace(/\s+/g, "");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function setCart(items: CartLine[]) {
  useCart.setState({ carts: [items], active: 0, items });
}

function mountPos(strict = false) {
  const ui = strict ? <StrictMode><POSKassa /></StrictMode> : <POSKassa />;
  return renderApp(ui);
}

type Method = "cash" | "card" | "qr" | "credit";
const CHIP: Record<Method, string> = { cash: "Naqd", card: "Karta", qr: "QR to‘lov", credit: "Qarz" };

/** To'lov oynasi orqali sotuvni yakunlaydi (UI oqimi, kassir bosganidek). */
async function pay(user: ReturnType<typeof userEvent.setup>, methods: Method[], amounts?: Partial<Record<Method, string>>) {
  await user.click(await screen.findByRole("button", { name: /TO‘LOVNI YAKUNLASH/ }));
  for (const m of methods) await user.click(screen.getByRole("button", { name: CHIP[m] }));
  if (amounts) {
    const inputs = screen.getAllByPlaceholderText("0");
    for (const [i, m] of methods.entries()) {
      const v = amounts[m];
      if (v === undefined) continue;
      await user.click(inputs[i]); // fokusda maydon tozalanadi
      await user.type(inputs[i], v);
    }
  }
  if (methods.includes("credit")) await user.click(await screen.findByRole("button", { name: /Aliyev Vali/ }));
  const finish = methods.length === 1 && methods[0] === "credit" ? "Nasiyaga yozish" : "To‘lovni yakunlash";
  await user.click(screen.getByRole("button", { name: finish }));
}

beforeEach(() => {
  _resetPrintRuntime();
  _resetSyncTimers();
  serverJobs = new Map();
  printed = [];
  printerAnswer = () => ({ ok: true });
  settings = {};
  useAuth.setState({
    token: "tok",
    employee: {
      id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir", status: "active",
      branch_name: "Chilonzor filiali", permissions: ["kassa.sell", "sotuvlar.view", "qaytarishlar.create"],
    },
  });
  setCart([NON, POMIDOR]);
  window.__BINOS_VIRTUAL_PRINTER__ = (req) => {
    printed.push(req);
    return printerAnswer(req);
  };
});

afterEach(() => {
  delete window.__BINOS_VIRTUAL_PRINTER__;
  delete window.savdoosPrint;
  useAuth.setState({ token: null, employee: null });
  setCart([]);
});

describe("POS muvaffaqiyat ekrani — chek chop etish", () => {
  it("qo'lda: server DTO'sidan ASL chek; keyingi bosish NUSXA (tugma yozuvi va qog'ozdagi banner)", async () => {
    const user = userEvent.setup();
    const calls = server(posRoutes());
    mountPos();
    await pay(user, ["cash"]);
    expect(await screen.findByText("Savdo muvaffaqiyatli yakunlandi")).toBeInTheDocument();
    expect(printed).toHaveLength(0); // auto_print o'chiq — o'zi chop etmaydi

    await user.click(screen.getByTestId("pos-print"));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Chek chop etildi"));
    expect(printed).toHaveLength(1);
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    expect(printed[0].html).toContain("#1288");
    // Chek SERVERdan: kassir nomi server DTO'sidagi (ekrandagi "Dilnoza" emas).
    expect(text(printed[0])).toContain("Dilnoza Karimova (server)");
    expect(calls.some((c) => c.method === "GET" && c.url.endsWith(`/sales/${SALE_ID}/receipt`))).toBe(true);
    // ASL chek qog'ozdan OLDIN serverda band qilinadi (PENDING), keyin yakuniy holat (PRINTED).
    const pj = writes(calls, /\/print-jobs/);
    expect(pj[0]).toMatchObject({ method: "POST", body: { doc_type: "SALE", doc_id: SALE_ID, copy: "ORIGINAL", status: "PENDING" } });
    expect(pj[pj.length - 1].body).toMatchObject({ status: "PRINTED" });

    const btn = screen.getByTestId("pos-print");
    expect(btn).toHaveTextContent("Nusxa chop etish");
    await user.click(btn);
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Nusxa #1 chop etildi"));
    expect(printed).toHaveLength(2);
    expect(printed[1].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(text(printed[1])).toContain("*** NUSXA #1 ***");
    // "E-chek" — o'sha chop etish (yangi funksiya o'ylab topilmagan): yana nusxa.
    await user.click(screen.getByTestId("pos-echek"));
    await waitFor(() => expect(printed).toHaveLength(3));
    expect(printed[2].copy).toEqual({ kind: "REPRINT", no: 2 });
    expect(writes(calls, /\/sales$/)).toHaveLength(1); // sotuv BIR marta yuborilgan
  });

  it("auto_print: StrictMode ikki marta mount — chek BIR marta, server jurnalida bitta ASL yozuv", async () => {
    const user = userEvent.setup();
    const calls = server(posRoutes([[/\/receipt\/profile/, profile({ auto_print: true })]]));
    mountPos(true);
    await pay(user, ["cash"]);
    await waitFor(() => expect(printed).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Chek chop etildi"));
    await sleep(50);
    expect(printed).toHaveLength(1);
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    const posts = writes(calls, /\/print-jobs$/);
    expect(posts).toHaveLength(1); // bitta ASL band (qog'ozdan oldin), yakuniy holat — PATCH
    expect(posts[0].body).toMatchObject({ copy: "ORIGINAL", status: "PENDING", doc_id: SALE_ID });
    const id = posts[0].body.id;
    await waitFor(() => expect(writes(calls, new RegExp(`/print-jobs/${id}$`)).map((c) => c.body.status)).toContain("PRINTED"));
    expect(listJobs()).toHaveLength(1);
  });

  it("auto_print: kassir darhol 'Yangi savdo' bossa ham AYNAN o'sha sotuv cheki chiqadi", async () => {
    const user = userEvent.setup();
    server(posRoutes([[/\/receipt\/profile/, profile({ auto_print: true })]]));
    let release: (v: unknown) => void = () => undefined;
    printerAnswer = () => new Promise((r) => { release = r; });
    mountPos();
    await pay(user, ["cash"]);
    await user.click(await screen.findByRole("button", { name: /Yangi savdo/ }));
    expect(screen.queryByText("Savdo muvaffaqiyatli yakunlandi")).toBeNull();
    await waitFor(() => expect(printed).toHaveLength(1));
    release({ ok: true });
    await waitFor(() => expect(listJobs()[0]?.status).toBe("PRINTED"));
    expect(listJobs()).toHaveLength(1);
    expect(listJobs()[0]).toMatchObject({ doc_id: SALE_ID, copy: "ORIGINAL" });
  });

  it("printer xatosi: sotuv yakunlangan, savat yopilgan, sotuv qayta yuborilmaydi; 'Qayta urinish' AYNAN o'sha asl chek", async () => {
    const user = userEvent.setup();
    const calls = server(posRoutes());
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "paper end" });
    mountPos();
    await pay(user, ["cash"]);
    await user.click(await screen.findByTestId("pos-print"));
    const status = screen.getByTestId("print-status");
    await waitFor(() => expect(status).toHaveTextContent("Xato: printerda qog'oz tugagan"));
    // Sotuv holati o'zgarmagan: muvaffaqiyat ekrani, savat bo'sh, outbox bo'sh, POST /sales bitta.
    expect(screen.getByText("Savdo muvaffaqiyatli yakunlandi")).toBeInTheDocument();
    expect(useCart.getState().items).toEqual([]);
    expect(outboxAll()).toEqual([]);
    expect(writes(calls, /\/sales$/)).toHaveLength(1);
    expect(screen.getByTestId("pos-print")).toHaveTextContent("Chekni chop etish"); // hali chop etilmagan

    printerAnswer = () => ({ ok: true });
    await user.click(within(status).getByRole("button", { name: "Qayta urinish" }));
    await waitFor(() => expect(status).toHaveTextContent("Chek chop etildi"));
    expect(printed.map((p) => p.copy)).toEqual([{ kind: "ORIGINAL" }, { kind: "ORIGINAL" }]);
    const jobs = listJobs();
    expect(jobs).toHaveLength(1);
    expect(jobs[0]).toMatchObject({ copy: "ORIGINAL", status: "PRINTED", attempts: 2 });
    expect(writes(calls, /\/sales$/)).toHaveLength(1);
  });

  it("osilib qolgan printer 'Yangi savdo'ni to'smaydi", async () => {
    const user = userEvent.setup();
    server(posRoutes());
    let release: (v: unknown) => void = () => undefined;
    printerAnswer = () => new Promise((r) => { release = r; });
    mountPos();
    await pay(user, ["cash"]);
    await user.click(await screen.findByTestId("pos-print"));
    await waitFor(() => expect(printed).toHaveLength(1));
    expect(screen.getByTestId("print-status")).toHaveTextContent("Chop etilmoqda…");
    await user.click(screen.getByRole("button", { name: /Yangi savdo/ }));
    expect(screen.queryByText("Savdo muvaffaqiyatli yakunlandi")).toBeNull();
    expect(screen.getByRole("button", { name: /TO‘LOVNI YAKUNLASH/ })).toBeDisabled(); // savat bo'sh
    release({ ok: true });
    await waitFor(() => expect(listJobs()[0]?.status).toBe("PRINTED"));
  });

  it.each([
    {
      name: "naqd (ortiqcha berildi → qaytim)", methods: ["cash"] as Method[], amounts: { cash: "20000" },
      body: { payment_method: "cash", given_amount: 20000, expected_total: TOTAL },
      dto: [{ method: "cash", amount: "12224.00", given: "20000.00", change: "7776.00" }],
      expect: ["Naqd12224", "Berildi20000", "Qaytim7776"],
    },
    {
      name: "karta", methods: ["card"] as Method[], body: { payment_method: "card", given_amount: null },
      dto: [{ method: "card", amount: "12224.00", given: null, change: null }], expect: ["Karta12224"],
    },
    {
      name: "QR", methods: ["qr"] as Method[], body: { payment_method: "qr", given_amount: null },
      dto: [{ method: "qr", amount: "12224.00", given: null, change: null }], expect: ["QR12224"],
    },
    {
      name: "qarz (nasiya)", methods: ["credit"] as Method[], body: { payment_method: "credit", customer_id: "cu1" },
      dto: [{ method: "credit", amount: "12224.00", given: null, change: null }], expect: ["Nasiya12224"],
    },
    {
      name: "aralash (naqd + karta)", methods: ["cash", "card"] as Method[], amounts: { cash: "5000", card: "7224" },
      body: { payment_method: "cash", payments: [{ method: "cash", amount: 5000 }, { method: "card", amount: 7224 }], given_amount: null },
      dto: [{ method: "cash", amount: "5000.00", given: null, change: null }, { method: "card", amount: "7224.00", given: null, change: null }],
      expect: ["Naqd5000", "Karta7224"],
    },
  ])("$name: payload to'g'ri, qog'ozda SERVER DTO to'lovlari", async (c) => {
    const user = userEvent.setup();
    const calls = server(posRoutes([[/\/sales\/[^/?]+\/receipt/, serverDto(c.dto as ReceiptDTO["payments"])]]));
    mountPos();
    await pay(user, c.methods, c.amounts);
    expect(await screen.findByText("Savdo muvaffaqiyatli yakunlandi")).toBeInTheDocument();
    const sale = writes(calls, /\/sales$/);
    expect(sale).toHaveLength(1);
    expect(sale[0].body).toMatchObject({ ...c.body, expected_total: TOTAL });
    if (c.methods.length === 1) expect(sale[0].body.payments).toBeUndefined();
    await user.click(screen.getByTestId("pos-print"));
    await waitFor(() => expect(printed).toHaveLength(1));
    const f = flat(printed[0]);
    for (const e of c.expect) expect(f).toContain(e);
    expect(f).toContain("JAMI12224so'm");
    // Qog'ozdagi to'lovlar yig'indisi = sotuv jami (server kafolati, chek shuni ko'rsatadi).
    const sum = (c.dto as { amount: string }[]).reduce((s, p) => s + Number(p.amount), 0);
    expect(sum).toBe(TOTAL);
  });
});

describe("oflayn sotuv — vaqtinchalik chek AYNAN yuborilgan payload'dan", () => {
  it("aralash (naqd+karta) oflayn: OFFLINE-raqam, banner, payload qiymatlari; server so'rovi yo'q", async () => {
    const user = userEvent.setup();
    settings = { payments: { offline_card: true } };
    cacheSet(CACHE.settings, settings);
    const calls = server(posRoutes([[/\/sales$/, () => { throw new TypeError("Failed to fetch"); }]]));
    mountPos();
    await pay(user, ["cash", "card"], { cash: "5000", card: "7224" });
    expect(await screen.findByText("Oflayn saqlandi")).toBeInTheDocument();
    expect(useCart.getState().items).toEqual([]);
    const queued = outboxAll();
    expect(queued).toHaveLength(1);
    const payload = queued[0].payload as any;
    expect(payload).toMatchObject({
      expected_total: TOTAL, payment_method: "cash",
      payments: [{ method: "cash", amount: 5000 }, { method: "card", amount: 7224 }],
      items: [{ product_id: "p1", qty: 2, unit_price: 4000 }, { product_id: "p2", qty: 0.352, unit_price: 12000 }],
    });

    await user.click(screen.getByTestId("pos-print"));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Chek chop etildi · vaqtinchalik oflayn chek"));
    expect(printed).toHaveLength(1);
    const cu = String(payload.client_uuid);
    const number = "OFFLINE-" + cu.replace(/-/g, "").slice(0, 8).toUpperCase();
    const t = text(printed[0]);
    expect(t).toContain(number);
    expect(t).toContain("OFLAYN — VAQTINCHALIK CHEK");
    expect(t).toContain("Non oq"); // nom — savatdan
    expect(t).toMatch(/2 dona × 4 000\s+8 000/);
    expect(t).toMatch(/0,352 kg × 12 000\s+4 224/);
    const f = flat(printed[0]);
    expect(f).toContain("Naqd5000");
    expect(f).toContain("Karta7224");
    expect(f).toContain("JAMI12224so'm");
    expect(f).not.toContain("Berildi"); // aralashda naqd berildi/qaytim noma'lum — to'qilmaydi
    // Server DTO so'ralmagan (id yo'q), jurnal hisoboti ham yo'q (server id'si hali yo'q).
    expect(calls.some((c) => /\/receipt$/.test(c.url))).toBe(false);
    expect(writes(calls, /\/print-jobs/)).toEqual([]);
    expect(listJobs()[0]).toMatchObject({ doc_id: null, client_uuid: cu, provisional: true, status: "PRINTED" });
  });

  it("naqd oflayn: berildi/qaytim server qoidasi bo'yicha (given_amount → qaytim)", async () => {
    const user = userEvent.setup();
    server(posRoutes([[/\/sales$/, () => { throw new TypeError("Failed to fetch"); }]]));
    mountPos();
    await pay(user, ["cash"], { cash: "20000" });
    expect(await screen.findByText("Oflayn saqlandi")).toBeInTheDocument();
    expect((outboxAll()[0].payload as any).given_amount).toBe(20000);
    await user.click(screen.getByTestId("pos-print"));
    await waitFor(() => expect(printed).toHaveLength(1));
    const f = flat(printed[0]);
    expect(f).toContain("Naqd12224");
    expect(f).toContain("Berildi20000");
    expect(f).toContain("Qaytim7776");
  });
});

describe("rad etilgan cheklar oynasi", () => {
  it("summa payload'dagi expected_total'dan (ilgari doim 0 edi)", async () => {
    const user = userEvent.setup();
    server(posRoutes());
    localStorage.setItem(nsKey("savdoos_outbox_failed"), JSON.stringify([{
      client_uuid: "f-1", created_at: "2026-09-19T09:00:00.000Z", error: "validation",
      payload: { client_uuid: "f-1", expected_total: 12224, items: [] },
    }]));
    mountPos();
    await user.click(await screen.findByTestId("failed-badge"));
    const row = await screen.findByTestId("failed-row");
    expect(row.textContent).toMatch(/12\s224/);
  });
});

describe("Sotuvlarim / Manager Sotuvlar — qayta chop etish server DTO'sidan", () => {
  const ROW = { id: SALE_ID, receipt_no: "#1288", sold_at: "2026-09-19T09:32:11+00:00", method: "cash", item_count: 2, total: TOTAL, cashier: "Dilnoza", first_item: "Non oq" };
  const DETAIL = { id: SALE_ID, receipt_no: "#1288", uid: "2609191288", total: TOTAL, sold_at: ROW.sold_at, items: [{ name_snapshot: "Non oq", qty: 2, unit_price: 4000, line_total: 8000 }] };
  const listRoutes = (over: [RegExp, any][] = []): [RegExp, any][] => [
    ...over,
    [/\/sales\/summary/, { count: 1, total: TOTAL, by_method: { cash: TOTAL } }],
    [/\/sales\/cashiers/, ["Dilnoza"]],
    ...posRoutes().filter(([re]) => !/sales\$/.test(String(re))),
    [/\/sales\/[^/?]+$/, DETAIL],
    [/\/sales\?/, [ROW]],
  ];

  it("POS kassada asl chek chiqqan → Sotuvlarim'da NUSXA (banner bilan)", async () => {
    const user = userEvent.setup();
    const calls = server(listRoutes());
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "cu-1", mode: "manual" });
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    renderApp(<Sotuvlarim />);
    const btn = await screen.findByTestId("sotuvlarim-print");
    expect(btn).toHaveTextContent("Nusxa chop etish");
    expect(screen.getByTestId("print-status")).toHaveTextContent("Chek chop etildi");
    await user.click(btn);
    await waitFor(() => expect(printed).toHaveLength(2));
    expect(printed[1].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(text(printed[1])).toContain("*** NUSXA #1 ***");
    expect(text(printed[1])).toContain("Dilnoza Karimova (server)");
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Nusxa #1 chop etildi"));
    expect(calls.filter((c) => c.url.endsWith(`/sales/${SALE_ID}/receipt`))).toHaveLength(2);
  });

  it("Manager: bu kompyuterda yozuv yo'q, server jurnalida ASL bor → NUSXA", async () => {
    const user = userEvent.setup();
    const calls = server(listRoutes([[/\/print-jobs\?/, [{ id: "srv-orig", copy: "ORIGINAL", status: "PRINTED", attempts: 1 }]]]));
    renderApp(<Sales />);
    await user.click(await screen.findByText("#1288"));
    const btn = await screen.findByTestId("sales-print");
    expect(btn).toHaveTextContent("Chop etish");
    await user.click(btn);
    await waitFor(() => expect(printed).toHaveLength(1));
    expect(printed[0].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(text(printed[0])).toContain("NUSXA #1");
    const pj = writes(calls, /\/print-jobs/);
    expect(pj[0].body).toMatchObject({ doc_type: "SALE", doc_id: SALE_ID, copy: "REPRINT" });
    await waitFor(() => expect(screen.getByTestId("sales-print")).toHaveTextContent("Nusxa chop etish"));
  });

  it("server DTO xatosi (404) → 'Xato', hech narsa chop etilmaydi", async () => {
    const user = userEvent.setup();
    server(listRoutes([[/\/sales\/[^/?]+\/receipt/, { __status: 404, detail: "Chek topilmadi" }]]));
    renderApp(<Sotuvlarim />);
    await user.click(await screen.findByTestId("sotuvlarim-print"));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent(/^Xato: /));
    expect(printed).toHaveLength(0);
    expect(within(screen.getByTestId("print-status")).getByRole("button", { name: "Qayta urinish" })).toBeInTheDocument();
  });
});

describe("qaytarish cheki", () => {
  const RET = { ...returnDto(), doc: { ...returnDto().doc, id: "r-1", number: "QAY-7" } };
  const FOUND = {
    id: SALE_ID, receipt_no: "#1288", uid: "2609191288", method: "cash", sold_at: "2026-09-19T09:32:11+00:00",
    cashier: "Dilnoza", total: TOTAL,
    items: [{ product_id: "p1", name: "Non oq", qty: 2, returned: 0, returnable: 2, unit_price: 4000, barcode: "" }],
  };
  const retRoutes = (over: [RegExp, any][] = []): [RegExp, any][] => [
    ...over,
    [/\/sales\/find/, FOUND],
    [/\/sales\?limit=8/, []],
    [/\/returns\/r-1\/receipt/, RET],
    [/\/returns$/, { id: "r-1", return_no: "QAY-7", total: 4000 }],
    ...posRoutes(),
  ];

  async function doReturn(user: ReturnType<typeof userEvent.setup>) {
    renderApp(<Returns />);
    const input = screen.getByPlaceholderText("Chek shtrix kodi yoki ID...");
    await user.type(input, "#1288{Enter}");
    await user.click(await screen.findByRole("button", { name: "+" }));
    await user.click(screen.getByRole("button", { name: /Qaytarishni tasdiqlash/ }));
    expect(await screen.findByText("Qaytarish yakunlandi")).toBeInTheDocument();
  }

  it("POS: qaytarishdan keyin chek serverdan; qayta bosish — NUSXA", async () => {
    const user = userEvent.setup();
    const calls = server(retRoutes());
    await doReturn(user);
    expect(printed).toHaveLength(0);
    const btn = screen.getByTestId("returns-print");
    expect(btn).toHaveTextContent("Qaytarish chekini chop etish");
    await user.click(btn);
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Chek chop etildi"));
    expect(text(printed[0])).toContain("QAY-7");
    expect(calls.some((c) => c.url.endsWith("/returns/r-1/receipt"))).toBe(true);
    expect(writes(calls, /\/print-jobs$/)[0].body).toMatchObject({ doc_type: "RETURN", doc_id: "r-1", copy: "ORIGINAL" });
    await user.click(screen.getByTestId("returns-print"));
    await waitFor(() => expect(printed).toHaveLength(2));
    expect(printed[1].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(writes(calls, /\/returns$/)).toHaveLength(1); // qaytarish BIR marta
  });

  it("POS: auto_print — qaytarish cheki o'zi, BIR marta (StrictMode)", async () => {
    const user = userEvent.setup();
    server(retRoutes([[/\/receipt\/profile/, profile({ auto_print: true })]]));
    renderApp(<StrictMode><Returns /></StrictMode>);
    const input = screen.getByPlaceholderText("Chek shtrix kodi yoki ID...");
    await user.type(input, "#1288{Enter}");
    await user.click(await screen.findByRole("button", { name: "+" }));
    await user.click(screen.getByRole("button", { name: /Qaytarishni tasdiqlash/ }));
    await waitFor(() => expect(printed).toHaveLength(1));
    await sleep(50);
    expect(printed).toHaveLength(1);
    expect(listJobs()[0]).toMatchObject({ doc_type: "RETURN", doc_id: "r-1", copy: "ORIGINAL", status: "PRINTED" });
  });

  it("Manager nazorati: qaytarish chekini qayta chop etish (server jurnalida asl bor → NUSXA)", async () => {
    const user = userEvent.setup();
    const ROWRET = {
      id: "r-1", return_no: "QAY-7", at: "2026-09-19T11:05:40+00:00", cashier: "Dilnoza", receipt_no: "#1288",
      customer: null, note: null, reason: "customer", refund_method: "cash", total: 4000, restock: true,
      items: [{ name: "Non oq", qty: 1, unit_price: 4000, line_total: 4000 }],
    };
    const calls = server(retRoutes([
      [/\/returns\?period=/, { kpi: { count: 1, total: 4000, restocked: 1, writeoff: 0 }, returns: [ROWRET] }],
      [/\/print-jobs\?/, [{ id: "srv-r", copy: "ORIGINAL", status: "PRINTED", attempts: 1 }]],
    ]));
    renderApp(<ReturnsOversight />);
    await user.click(await screen.findByText("QAY-7"));
    await user.click(await screen.findByTestId("ret-print"));
    await waitFor(() => expect(printed).toHaveLength(1));
    expect(printed[0].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(text(printed[0])).toContain("QAY-7");
    expect(calls.some((c) => c.url.includes("/print-jobs?doc_type=RETURN&doc_id=r-1"))).toBe(true);
  });
});

describe("sync.ts — sotuv id'si, oflayn chekni bog'lash, sinxron sikli", () => {
  it("submitSale: onlayn — id va sold_at qaytadi; oflayn — id yo'q, sold_at = navbat vaqti", async () => {
    let down = false;
    server([[/\/sales$/, () => {
      if (down) throw new TypeError("Failed to fetch");
      return { id: SALE_ID, receipt_no: "#9", uid: "2609199", sold_at: "2026-09-19T10:00:00+00:00" };
    }]]);
    const on = await submitSale({ client_uuid: "c-on", items: [] });
    expect(on).toEqual({ ok: true, offline: false, receipt_no: "#9", uid: "2609199", id: SALE_ID, sold_at: "2026-09-19T10:00:00+00:00" });
    down = true;
    const off = await submitSale({ client_uuid: "c-off", items: [] });
    expect(off.offline).toBe(true);
    expect(off.id).toBeUndefined();
    expect(off.sold_at).toBe(outboxAll()[0].created_at);
  });

  const provisional = (cu: string) => provisionalSaleReceipt({
    client_uuid: cu, lines: [{ name: "Non oq", qty: "2", unit_price: "4000", weighted: false }],
    payments: [{ method: "cash", amount: "8000" }], total: "8000",
    store: { name: "Fayzan Market", branch_name: null, address: null, phone: null, stir: null },
    cashier: "Dilnoza", issued_at_local: "19.09.2026 14:40", template: { ...BUILTIN_TEMPLATE },
  });

  it("flushOutbox: /sync/push `id` → oflayn chek yozuvi server hujjatiga bog'lanadi va darhol hisobot qilinadi", async () => {
    const CU = "abcdef12-3456-4789-8abc-def012345678";
    const calls = server([
      [/\/sync\/push/, (c: Call) => ({ accepted: 1, failed: 0, results: c.body.sales.map((s: any) => ({ client_uuid: s.client_uuid, ok: true, receipt_no: "#1300", id: SALE_ID })) })],
      ...posRoutes(),
    ]);
    const job = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(CU), mode: "auto" });
    expect(job).toMatchObject({ doc_id: null, status: "PRINTED", reported: false });
    outboxAdd({ client_uuid: CU, payload: { client_uuid: CU, items: [] }, created_at: "2026-09-19T09:00:00.000Z", owner_id: "emp-1" });
    await flushOutbox();
    expect(outboxAll()).toEqual([]);
    expect(listJobs({ key: docKey("SALE", SALE_ID) })[0]).toMatchObject({ id: job.id, doc_id: SALE_ID, client_uuid: CU });
    await waitFor(() => expect(listJobs()[0].reported).toBe(true));
    const pj = writes(calls, /\/print-jobs$/);
    expect(pj).toHaveLength(1);
    expect(pj[0].body).toMatchObject({ id: job.id, doc_id: SALE_ID, copy: "ORIGINAL", status: "PRINTED" });
  });

  it("eski server (`id` yo'q): sotuv navbatdan chiqadi, chek yozuvi bog'lanmay qoladi (hech narsa buzilmaydi)", async () => {
    const CU = "11111111-2222-4333-8444-555555555555";
    const calls = server([
      [/\/sync\/push/, (c: Call) => ({ results: c.body.sales.map((s: any) => ({ client_uuid: s.client_uuid, ok: true, receipt_no: "#1" })) })],
      ...posRoutes(),
    ]);
    await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(CU), mode: "auto" });
    outboxAdd({ client_uuid: CU, payload: { client_uuid: CU }, created_at: "2026-09-19T09:00:00.000Z", owner_id: "emp-1" });
    await flushOutbox();
    expect(outboxAll()).toEqual([]);
    expect(listJobs()[0].doc_id).toBeNull();
    expect(writes(calls, /\/print-jobs/)).toEqual([]);
  });

  it("syncTick: navbatdan KEYIN hisobot berilmagan chek yozuvlari yuboriladi", async () => {
    let down = true;
    const calls = server(posRoutes([[/\/print-jobs$/, (c: Call) => {
      if (down) throw new TypeError("Failed to fetch");
      return jobOut(c.body);
    }]]));
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(listJobs()[0].reported).toBe(false); // tarmoq xatosi — keyinroq
    down = false;
    await syncTick(1_000_000_000_000);
    expect(listJobs()[0]).toMatchObject({ reported: true, copy_no: 0, status: "PRINTED" });
    // Tarmoq yo'q: band qilish (PENDING) va yakuniy hisobot yiqildi; sikl yakuniy holatni yubordi.
    const posts = writes(calls, /\/print-jobs$/);
    expect(posts).toHaveLength(3);
    expect(posts[0].body).toMatchObject({ doc_id: SALE_ID, status: "PENDING" });
    expect(posts[2].body).toMatchObject({ doc_id: SALE_ID, status: "PRINTED" });
  });

  it("syncTick profil chastotasi: 5 daqiqada bir marta, ruxsatsiz xodimda umuman yo'q", async () => {
    const calls = server(posRoutes([[/\/receipt\/profile/, { __status: 503, detail: "x" }]]));
    const n = () => calls.filter((c) => /\/receipt\/profile/.test(c.url)).length;
    const t0 = 1_000_000_000_000;
    await syncTick(t0);
    await waitFor(() => expect(n()).toBe(1));
    await syncTick(t0 + 60_000);
    await syncTick(t0 + 299_000);
    await sleep(20);
    expect(n()).toBe(1); // xato bo'lsa ham har 30s so'rov yog'dirmaydi
    await syncTick(t0 + 300_000);
    await waitFor(() => expect(n()).toBe(2));

    _resetSyncTimers();
    useAuth.setState({ employee: { ...useAuth.getState().employee!, permissions: ["hisobot.view"] } });
    await syncTick(t0 + 900_000);
    await sleep(20);
    expect(n()).toBe(2);
  });
});

describe("eski (5F'dan oldingi) server — onlayn sotuv cheki o'z suratidan (#6/#17)", () => {
  // FastAPI marshrut topmasa — standart 404 "Not Found" (kodsiz). 5F server o'z 404'ida "Chek topilmadi" deydi.
  const NOT_FOUND = { __status: 404, detail: "Not Found" };

  it("chek marshruti YO'Q: server raqami bilan, oflayn bannersiz, 5F'dan oldingidek (manzil/izoh umumiy sozlamalardan)", async () => {
    const user = userEvent.setup();
    settings = { store_info: { name: "Fayzan Market", address: "Chilonzor 5-uy", phone: "+998 71 200 00 00" }, receipt: { footer: "Xaridingiz uchun rahmat!" } };
    cacheSet(CACHE.settings, settings);
    const calls = server(posRoutes([
      [/\/sales\/[^/?]+\/receipt/, NOT_FOUND], [/\/receipt\/profile/, NOT_FOUND], [/\/print-jobs/, NOT_FOUND],
    ]));
    mountPos();
    await pay(user, ["cash"], { cash: "20000" });
    expect(await screen.findByText("Savdo muvaffaqiyatli yakunlandi")).toBeInTheDocument();
    await user.click(screen.getByTestId("pos-print"));
    const status = screen.getByTestId("print-status");
    await waitFor(() => expect(status).toHaveTextContent("Chek chop etildi"));
    expect(status).not.toHaveTextContent("vaqtinchalik");
    expect(printed).toHaveLength(1);
    // Avval server so'raldi (marshrut bo'lsa chek doim server DTO'sidan).
    expect(calls.some((c) => c.method === "GET" && c.url.endsWith(`/sales/${SALE_ID}/receipt`))).toBe(true);
    const t = text(printed[0]);
    expect(printed[0].html).toContain("#1288");
    expect(t).not.toContain("OFLAYN");
    expect(t).not.toContain("OFFLINE-");
    expect(flat(printed[0])).toContain("FayzanMarket"); // do'kon nomi ikki barobar harfda
    expect(t).toContain("Chilonzor 5-uy");
    expect(t).toContain("Xaridingiz uchun rahmat!");
    expect(t).toContain("Dilnoza"); // kassir — shu kassadagi xodim
    expect(t).toMatch(/2 dona × 4 000\s+8 000/);
    expect(t).toMatch(/0,352 kg × 12 000\s+4 224/);
    const f = flat(printed[0]);
    expect(f).toContain("JAMI12224so'm");
    expect(f).toContain("Berildi20000");
    expect(f).toContain("Qaytim7776");
    expect(listJobs()[0]).toMatchObject({ doc_id: SALE_ID, status: "PRINTED", provisional: false });
    expect(writes(calls, /\/sales$/)).toHaveLength(1);
  });

  it("marshrut BOR, lekin hujjat topilmadi (5F server'ning o'z 404'i) — zaxira ISHLATILMAYDI: xato, hech narsa chop etilmaydi", async () => {
    const user = userEvent.setup();
    server(posRoutes([[/\/sales\/[^/?]+\/receipt/, { __status: 404, detail: "Chek topilmadi" }]]));
    mountPos();
    await pay(user, ["cash"]);
    await user.click(await screen.findByTestId("pos-print"));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent(/^Xato: /));
    expect(printed).toHaveLength(0);
  });
});

describe("tarozi: qo'lda kiritilgan vazn 0.001 kg ga — server qoidasi (#12)", () => {
  async function weigh(user: ReturnType<typeof userEvent.setup>, typed: string) {
    await user.click(await screen.findByRole("button", { name: /Pomidor/ }));
    const input = screen.getByPlaceholderText("0.000 kg");
    await user.type(input, typed);
    return input;
  }

  it("0,3525 kg × 12 000 → 0,353 kg: kassa jami, payload va vaqtinchalik chek bir xil 4 236 ('Yaxlitlash' to'qilmaydi)", async () => {
    const user = userEvent.setup();
    setCart([]);
    server(posRoutes([[/\/sales$/, () => { throw new TypeError("Failed to fetch"); }]]));
    mountPos();
    const input = await weigh(user, "0,3525");
    expect(input.parentElement).toHaveTextContent(/4\s236/); // oldindan ko'rinadigan summa ham 0,353 dan
    await user.keyboard("{Enter}");
    expect(useCart.getState().items).toEqual([expect.objectContaining({ id: "p2", qty: 0.353, weighted: true })]);

    await pay(user, ["cash"]);
    expect(await screen.findByText("Oflayn saqlandi")).toBeInTheDocument();
    const payload = outboxAll()[0].payload as any;
    expect(payload.items).toEqual([{ product_id: "p2", qty: 0.353, unit_price: 12000 }]);
    expect(payload.expected_total).toBe(4236); // server qayta o'ynaganda ham 0.353 × 12 000 = 4 236

    await user.click(screen.getByTestId("pos-print"));
    await waitFor(() => expect(printed).toHaveLength(1));
    const t = text(printed[0]);
    expect(t).toMatch(/0,353 kg × 12 000\s+4 236/);
    expect(t).not.toContain("Yaxlitlash");
    expect(flat(printed[0])).toContain("JAMI4236so'm");
  });

  it("float chegarasi: 0,5005 kg → 0,501 (ROUND_HALF_UP; Math.round(kg*1000) bu yerda 0,500 berardi)", async () => {
    const user = userEvent.setup();
    setCart([]);
    server(posRoutes());
    mountPos();
    await weigh(user, "0,5005");
    await user.keyboard("{Enter}");
    expect(useCart.getState().items).toEqual([expect.objectContaining({ id: "p2", qty: 0.501 })]);
  });
});

describe("chop etish xatosi — printer sozlamasiga havola va tarjima (#9, #37)", () => {
  function Harness({ target }: { target: PrintTarget }) {
    const st = usePrintDoc(target);
    return (
      <>
        <button type="button" onClick={() => void st.print("manual")}>chop</button>
        <PrintStatus state={st} />
      </>
    );
  }
  const TARGET: PrintTarget = { doc_type: "SALE", doc_id: SALE_ID };

  function mountHarness(lang: Lang = "uz") {
    useLang.getState().set(lang);
    return render(<MemoryRouter><Harness target={TARGET} /></MemoryRouter>);
  }

  // Printer faqat shu kompyuterda "XP-80C" tanlangach chop etadi (virtual printer sozlamani o'qiydi).
  function pickedPrinterOnly() {
    window.savdoosPrint = {
      listPrinters: vi.fn(async () => [{ name: "XP-80C", displayName: "XP-80C", isDefault: false }]),
      print: vi.fn(), printHtml: vi.fn(), printEscPos: vi.fn(),
    } as never;
    printerAnswer = () => (readPrinterConfig().printer === "XP-80C"
      ? { ok: true } : { ok: false, code: "NO_PRINTER", error: "printer tanlanmagan" });
  }

  async function fixPrinterInDialog(user: ReturnType<typeof userEvent.setup>, router: ReturnType<typeof createMemoryRouter>, path: string) {
    const status = screen.getByTestId("print-status");
    await waitFor(() => expect(status).toHaveTextContent("Xato: printer topilmadi yoki tanlanmagan"));
    // Havola EMAS — tugma: sozlama shu ekranda, oynada ochiladi.
    expect(within(status).queryByRole("link")).toBeNull();
    const open = within(status).getByRole("button", { name: "Printer sozlamasi" });
    await user.click(open);
    const dialog = await screen.findByRole("dialog", { name: "Ushbu kompyuter printeri" });
    expect(router.state.location.pathname).toBe(path);
    await user.selectOptions(await within(dialog).findByLabelText("Printer"), "XP-80C");
    expect(readPrinterConfig().printer).toBe("XP-80C");
    // Escape oynani yopadi (orqadagi to'lov oynasini EMAS), fokus ochgan tugmaga qaytadi.
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(open).toHaveFocus());
    expect(router.state.location.pathname).toBe(path);
    return status;
  }

  it("POS kassa: printer topilmadi → «Printer sozlamasi» OYNADA; printer tanlanib yopilgach 'Qayta urinish' AYNAN o'sha asl chekni shu ekranda chop etadi", async () => {
    const user = userEvent.setup();
    const calls = server(posRoutes());
    pickedPrinterOnly();
    useLang.getState().set("uz");
    const router = createMemoryRouter(posAppRoutes, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);
    await pay(user, ["cash"]);
    await user.click(await screen.findByTestId("pos-print"));
    const status = await fixPrinterInDialog(user, router, "/");
    expect(screen.getByText("Savdo muvaffaqiyatli yakunlandi")).toBeInTheDocument(); // muvaffaqiyat ekrani joyida
    await user.click(within(status).getByRole("button", { name: "Qayta urinish" }));
    await waitFor(() => expect(status).toHaveTextContent("Chek chop etildi"));
    expect(printed.map((p) => p.copy)).toEqual([{ kind: "ORIGINAL" }, { kind: "ORIGINAL" }]);
    expect(text(printed[1])).toContain("Dilnoza Karimova (server)");
    expect(listJobs()).toHaveLength(1);
    expect(listJobs()[0]).toMatchObject({ doc_id: SALE_ID, copy: "ORIGINAL", status: "PRINTED", attempts: 2 });
    expect(writes(calls, /\/sales$/)).toHaveLength(1);
  });

  it("POS qaytarish: qaytarish cheki xatosi → oynada printer tuzatiladi → 'Qayta urinish' o'sha RETURN asl chekini chop etadi", async () => {
    const user = userEvent.setup();
    const RET = { ...returnDto(), doc: { ...returnDto().doc, id: "r-1", number: "QAY-7" } };
    const FOUND = {
      id: SALE_ID, receipt_no: "#1288", uid: "2609191288", method: "cash", sold_at: "2026-09-19T09:32:11+00:00",
      cashier: "Dilnoza", total: TOTAL,
      items: [{ product_id: "p1", name: "Non oq", qty: 2, returned: 0, returnable: 2, unit_price: 4000, barcode: "" }],
    };
    const calls = server([
      [/\/sales\/find/, FOUND], [/\/sales\?limit=8/, []], [/\/returns\/r-1\/receipt/, RET],
      [/\/returns$/, { id: "r-1", return_no: "QAY-7", total: 4000 }], ...posRoutes(),
    ]);
    pickedPrinterOnly();
    useLang.getState().set("uz");
    const router = createMemoryRouter(posAppRoutes, { initialEntries: ["/qaytarishlar"] });
    render(<RouterProvider router={router} />);
    await user.type(await screen.findByPlaceholderText("Chek shtrix kodi yoki ID..."), "#1288{Enter}");
    await user.click(await screen.findByRole("button", { name: "+" }));
    await user.click(screen.getByRole("button", { name: /Qaytarishni tasdiqlash/ }));
    expect(await screen.findByText("Qaytarish yakunlandi")).toBeInTheDocument();
    await user.click(screen.getByTestId("returns-print"));
    const status = await fixPrinterInDialog(user, router, "/qaytarishlar");
    expect(screen.getByText("Qaytarish yakunlandi")).toBeInTheDocument();
    await user.click(within(status).getByRole("button", { name: "Qayta urinish" }));
    await waitFor(() => expect(status).toHaveTextContent("Chek chop etildi"));
    expect(printed.map((p) => p.copy)).toEqual([{ kind: "ORIGINAL" }, { kind: "ORIGINAL" }]);
    expect(text(printed[1])).toContain("QAY-7");
    expect(listJobs()[0]).toMatchObject({ doc_type: "RETURN", doc_id: "r-1", copy: "ORIGINAL", status: "PRINTED" });
    expect(writes(calls, /\/returns$/)).toHaveLength(1); // qaytarish BIR marta
  });

  it.each(["OFFLINE", "REJECTED", "TIMEOUT", "PAPER_OUT"])("Manager: %s → havola Sozlamalar'ga (sozlamalar.view ruxsati bilan)", async (code) => {
    const user = userEvent.setup();
    server(posRoutes());
    useAuth.setState({ employee: { ...useAuth.getState().employee!, permissions: ["sotuvlar.view", "sozlamalar.view"] } });
    printerAnswer = () => ({ ok: false, code, error: "x" });
    mountHarness();
    await user.click(screen.getByRole("button", { name: "chop" }));
    const status = screen.getByTestId("print-status");
    await waitFor(() => expect(status).toHaveAttribute("data-status", "FAILED"));
    expect(within(status).getByRole("link", { name: "Printer sozlamasi" })).toHaveAttribute("href", "/sozlamalar?tab=receipt");
  });

  it("Manager: sozlamalar ruxsati yo'q yoki sabab printer emas (FAILED) — havola yo'q", async () => {
    const user = userEvent.setup();
    server(posRoutes());
    printerAnswer = () => ({ ok: false, code: "NO_PRINTER", error: "x" });
    const { unmount } = mountHarness();
    await user.click(screen.getByRole("button", { name: "chop" }));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveAttribute("data-status", "FAILED"));
    expect(screen.queryByRole("link")).toBeNull(); // kassirda sozlamalar.view yo'q
    unmount();

    useAuth.setState({ employee: { ...useAuth.getState().employee!, permissions: ["sotuvlar.view", "sozlamalar.view"] } });
    printerAnswer = () => ({ ok: false, code: "FAILED", error: "Print job failed" });
    mountHarness();
    await user.click(screen.getByRole("button", { name: "chop" }));
    await waitFor(() => expect(screen.getByTestId("print-status")).toHaveTextContent("Xato: noma'lum xato"));
    expect(screen.queryByRole("link")).toBeNull();
  });

  it.each([
    { lang: "ru" as Lang, shown: "Ошибка: неизвестная ошибка" },
    { lang: "uzc" as Lang, shown: "Хато: номаълум хато" },
    { lang: "ky" as Lang, shown: "Ката: белгисиз ката" },
  ])("$lang: qurilmaning xom inglizcha matni ('Print job failed') ekranda emas — tarjima, xom matn faqat title'da", async ({ lang, shown }) => {
    const user = userEvent.setup();
    server(posRoutes());
    printerAnswer = () => ({ ok: false, code: "FAILED", error: "Print job failed" });
    mountHarness(lang);
    await user.click(screen.getByRole("button", { name: "chop" }));
    const status = screen.getByTestId("print-status");
    await waitFor(() => expect(status).toHaveTextContent(shown));
    expect(status).not.toHaveTextContent("Print job failed");
    expect(within(status).getByText(shown)).toHaveAttribute("title", "Print job failed");
  });

  it("printErrorReason: kod yo'q/FAILED + ichki lotincha matn → umumiy tarjima; tarmoq va chek ma'lumoti saqlanadi", () => {
    const t = (k: string, v?: Record<string, string | number>) => translate("ru", k, v);
    expect(printErrorReason(t, { code: "FAILED", error: "noto'g'ri javob" })).toBe("неизвестная ошибка");
    expect(printErrorReason(t, { code: null, error: "print: kutilmagan" })).toBe("неизвестная ошибка");
    expect(printErrorReason(t, { code: "FAILED", error: "Failed to fetch" })).toBe("нет связи с сервером");
    expect(printErrorReason(t, { code: "NO_DATA", error: "Chek topilmadi" })).toBe("нет данных чека");
    expect(printErrorReason(t, { code: "OFFLINE", error: "ECONNREFUSED" })).toBe("принтер не отвечает — проверьте сеть и питание");
  });
});
