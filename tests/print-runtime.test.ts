import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  _resetPrintRuntime, bindDocId, bindDocIds, docKey, flushPrintReports, getReceiptProfile, listJobs, printDoc,
  printTestReceipt, retryJob, usePrintJobs, BRIDGE_TIMEOUT_MS, PRINT_JOBS_KEY, type LocalPrintJob,
} from "@/lib/printing";
import {
  PRINTER_CONFIG_KEY, defaultPrinterConfig, effectiveProfile, effectiveWidth, readPrinterConfig, sanitizePrinterConfig,
  writePrinterConfig,
} from "@/lib/printerConfig";
import { cacheGet, cacheSet, nsKey, outboxAdd, outboxAll } from "@/lib/offline";
import { flushOutbox } from "@/lib/sync";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";
import { BUILTIN_TEMPLATE, docHeightMm, layoutReceipt, provisionalSaleReceipt, sampleReceipt, type ReceiptDTO } from "@/receipt";
import type { VirtualPrintRequest } from "@/print/bridge";
import { LOGO_64x16, QR_MATRIX_1288, saleDto } from "./__golden__/receipt/fixtures";
import { mockApi, type Call } from "./util";

// Phase 5F F2: renderer chop etish runtime'i — navbat holat mashinasi, asl/nusxa, qayta urinish, oflayn
// vaqtinchalik chek, server jurnali hisobotlari (409 bilan) va sinov chekining YOZMASLIGI.

const SALE = saleDto();
const SALE_ID = SALE.doc.id as string;
const ORIGINAL_EXISTS = "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting";
const JOB_FINAL = "Chop etish holati yakunlangan — o'zgartirib bo'lmaydi";
/** G1 (5F.2 R0): boshqa qurilmaning jonli bandi — matn sinovda o'zimizniki, qaror faqat KOD bo'yicha. */
const JOB_BUSY = "Chek hozir boshqa qurilmada chop etilmoqda";
/** FastAPI'ning marshrut yo'q 404 i (5F dan oldingi server). */
const ROUTE_MISSING = { __status: 404, detail: "Not Found" };

const PROFILE = {
  etag: "etag-1",
  branch_id: "b1",
  effective: { ...BUILTIN_TEMPLATE, printer: null, logo_id: SALE.logo!.id, qr_url: null },
  store: SALE.store,
  logo: { id: SALE.logo!.id, sha256: SALE.logo!.sha256, variants: { "58": LOGO_64x16, "80": LOGO_64x16 } },
  store_qr: null,
};

/** Soddalashtirilgan server jurnali: id bo'yicha holat, nusxa raqami = hujjat nusxalari soni. */
let serverJobs = new Map<string, any>();
function jobOut(body: any) {
  const prev = serverJobs.get(body.id);
  const copy = prev?.copy ?? body.copy ?? "ORIGINAL";
  const docId = prev?.doc_id ?? body.doc_id ?? SALE_ID;
  const copyNo = prev?.copy_no ?? (copy === "REPRINT"
    ? [...serverJobs.values()].filter((j) => j.doc_id === docId && j.copy === "REPRINT").length + 1 : 0);
  const out = {
    id: body.id, doc_type: prev?.doc_type ?? body.doc_type ?? "SALE", doc_id: docId, copy, copy_no: copyNo,
    status: body.status ?? prev?.status ?? "PENDING", attempts: Math.max(prev?.attempts ?? 0, body.attempts ?? 0),
    error: body.error ?? null, printer: body.printer ?? null, transport: body.transport ?? null,
    created_at: "2026-09-19T09:40:00+00:00", updated_at: "2026-09-19T09:40:00+00:00", printed_at: null,
  };
  serverJobs.set(body.id, out);
  return out;
}

/**
 * `mockApi` + server `X-Error-Code` sarlavhasi (mockApi faqat `detail` qaytaradi): chop etish jurnali
 * qarorini matn emas, KOD bo'yicha qiladi.
 */
function server(routes: [RegExp, any][]): Call[] {
  const calls = mockApi(routes);
  const inner = globalThis.fetch;
  vi.stubGlobal("fetch", async (url: string, opts?: RequestInit) => {
    // So'rov muddati (AbortController) — osilib qolgan marshrut `api()` muddatida uziladi.
    const sig = opts?.signal;
    const aborted = new Promise<never>((_, reject) => {
      const fail = () => reject(new DOMException("The operation was aborted.", "AbortError"));
      if (sig?.aborted) fail();
      sig?.addEventListener("abort", fail);
    });
    const res = await Promise.race([inner(url, opts), aborted]);
    if (res.status < 400) return res;
    const text = await res.text();
    const detail = (() => { try { return JSON.parse(text).detail; } catch { return ""; } })();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (detail === ORIGINAL_EXISTS) headers["X-Error-Code"] = "PRINT_ORIGINAL_EXISTS";
    if (detail === JOB_FINAL) headers["X-Error-Code"] = "PRINT_JOB_FINAL";
    if (detail === JOB_BUSY) headers["X-Error-Code"] = "PRINT_JOB_BUSY";
    return new Response(text, { status: res.status, headers });
  });
  return calls;
}

/**
 * Serverning `/print-jobs` qoidalari (jobs.py): id takrori — holat o'tishi; PRINTED → boshqa — 409
 * PRINT_JOB_FINAL; hujjatga ikkinchi ASL — 409 PRINT_ORIGINAL_EXISTS; nusxa raqami — hujjat nusxalari soni.
 * 5F.2 (G1 shartnomasi): ASL band `claim_token` bilan; jonli (PENDING) bandni BOSHQA token bilan PENDING
 * yoki FAILED qilish — 409 PRINT_JOB_BUSY. Bir nechta "qurilma" (mahalliy jurnal) ayni server holatini ko'radi.
 */
function journal() {
  const rows = new Map<string, any>();
  const transition = (row: any, b: any) => {
    if (row.status === "PRINTED") {
      if (b.status === undefined || b.status === "PRINTED") return row;
      return { __status: 409, detail: JOB_FINAL };
    }
    if (row.copy === "ORIGINAL" && row.status === "PENDING" && row.claim_token &&
        (b.status === "PENDING" || b.status === "FAILED") && b.claim_token !== row.claim_token) {
      return { __status: 409, detail: JOB_BUSY };
    }
    if (b.status === "PENDING" && b.claim_token !== undefined) row.claim_token = b.claim_token;
    if (b.status) row.status = b.status;
    if (typeof b.attempts === "number") row.attempts = Math.max(row.attempts, b.attempts);
    return row;
  };
  const create = (c: Call) => {
    const b = c.body;
    const prev = rows.get(b.id);
    if (prev) return transition(prev, b);
    const same = [...rows.values()].filter((r) => r.doc_id === b.doc_id && r.doc_type === b.doc_type);
    if (b.copy === "ORIGINAL" && same.some((r) => r.copy === "ORIGINAL")) return { __status: 409, detail: ORIGINAL_EXISTS };
    const row = {
      id: b.id, doc_type: b.doc_type, doc_id: b.doc_id, copy: b.copy,
      copy_no: b.copy === "REPRINT" ? same.filter((r) => r.copy === "REPRINT").length + 1 : 0,
      status: b.status ?? "PENDING", attempts: b.attempts ?? 0, claim_token: b.claim_token ?? null,
    };
    rows.set(b.id, row);
    return row;
  };
  const patch = (c: Call) => {
    const row = rows.get(c.url.split("/").pop() as string);
    return row ? transition(row, c.body) : { __status: 404, detail: "Chop etish so'rovi noto'g'ri" };
  };
  const list = (c: Call) => {
    const q = new URL(c.url).searchParams;
    return [...rows.values()].filter((r) => r.doc_id === q.get("doc_id") && r.doc_type === q.get("doc_type"));
  };
  const routes: [RegExp, any][] = [[/\/print-jobs\?/, list], [/\/print-jobs\/[^/?]+$/, patch], [/\/print-jobs$/, create]];
  return { rows, routes };
}

/** Qurilma almashtirish: har qurilmaning O'Z localStorage'i (jurnal, xarita), server holati umumiy. */
const devices: Record<string, [string, string][]> = {};
let device = "pos";
function onDevice(name: string, emp: { id: string; full_name: string; permissions: string[] }) {
  const cur: [string, string][] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i) as string;
    cur.push([k, localStorage.getItem(k) as string]);
  }
  devices[device] = cur;
  localStorage.clear();
  for (const [k, v] of devices[name] ?? []) localStorage.setItem(k, v);
  device = name;
  _resetPrintRuntime();
  useAuth.setState({
    token: `tok-${emp.id}`,
    employee: { ...emp, role_code: "kassir", role_name: "Kassir", status: "active" },
  });
}
const CASHIER = { id: "emp-1", full_name: "Dilnoza", permissions: ["kassa.sell"] };
const MANAGER = { id: "emp-9", full_name: "Manager", permissions: ["sotuvlar.view"] };

const printJobCalls = (calls: Call[]) => calls.filter((c) => /\/print-jobs/.test(c.url));
const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

let printed: VirtualPrintRequest[] = [];
/** Haqiqatan qog'ozga chiqqanlar (printer ok qaytargan). */
let paper: VirtualPrintRequest[] = [];
let printerAnswer: (req: VirtualPrintRequest) => any = () => ({ ok: true });

beforeEach(() => {
  _resetPrintRuntime();
  for (const k of Object.keys(devices)) delete devices[k];
  device = "pos";
  serverJobs = new Map();
  printed = [];
  paper = [];
  printerAnswer = () => ({ ok: true });
  useLang.getState().set("uz");
  useAuth.setState({
    token: "tok",
    employee: { id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir", status: "active", permissions: ["kassa.sell"] },
  });
  window.__BINOS_VIRTUAL_PRINTER__ = (req) => {
    printed.push(req);
    const r = printerAnswer(req);
    // Sekin printer (va'da) — qog'oz javob kelganda chiqqan hisoblanadi.
    if (r && typeof r.then === "function") return r.then((v: any) => { if (v && v.ok === true) paper.push(req); return v; });
    if (r && r.ok === true) paper.push(req);
    return r;
  };
});

afterEach(() => {
  delete window.__BINOS_VIRTUAL_PRINTER__;
  delete window.savdoosPrint;
  useAuth.setState({ token: null, employee: null });
});

const baseRoutes = (over: [RegExp, any][] = []): [RegExp, any][] => [
  ...over,
  [/\/sales\/[^/]+\/receipt/, SALE],
  [/\/receipt\/profile/, PROFILE],
  [/\/print-jobs\?/, []],
  [/\/print-jobs\/[^/?]+$/, (c: Call) => jobOut({ ...c.body, id: c.url.split("/").pop() })],
  [/\/print-jobs$/, (c: Call) => jobOut(c.body)],
];

describe("printDoc — asl chek bitta, avto chop etish takrorlanmaydi", () => {
  it("StrictMode: ikki parallel auto → bitta chop etish, bitta ASL yozuv; uchinchi auto ham chop etmaydi", async () => {
    const calls = server(baseRoutes());
    const req = { doc_type: "SALE" as const, doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" as const };
    const [a, b] = await Promise.all([printDoc(req), printDoc(req)]);
    expect(printed).toHaveLength(1);
    expect(a.id).toBe(b.id);
    expect(a).toMatchObject({ copy: "ORIGINAL", status: "PRINTED", attempts: 1, reported: true, copy_no: 0, transport: "virtual", provisional: false });
    const again = await printDoc(req);
    expect(again.id).toBe(a.id);
    expect(printed).toHaveLength(1);
    expect(listJobs()).toHaveLength(1);
    // Chek SERVER DTO'sidan: raqam, logo (profil keshidan), ASL — banner yo'q.
    expect(printed[0].kind).toBe("html");
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    expect(printed[0].html).toContain("#1288");
    expect(printed[0].html).toContain('src="data:image/png;base64,');
    expect(printed[0].html).not.toContain("NUSXA");
    const pj = printJobCalls(calls);
    // ASL chek qog'ozdan OLDIN serverda band qilinadi (PENDING), keyin yakuniy holat.
    expect(pj.map((c) => c.method)).toEqual(["POST", "PATCH"]);
    expect(pj[0].body).toMatchObject({ id: a.id, doc_type: "SALE", doc_id: SALE_ID, copy: "ORIGINAL", status: "PENDING", attempts: 0 });
    expect(calls.indexOf(pj[0])).toBeLessThan(calls.findIndex((c) => /\/receipt$/.test(c.url)));
    expect(pj[1].url).toMatch(new RegExp(`/print-jobs/${a.id}$`));
    expect(pj[1].body).toMatchObject({ status: "PRINTED", attempts: 1, transport: "virtual", error: null });
    // 5F.2 R0: band — tasodifiy token; yakuniy hisobot AYNI token bilan (yozuvda saqlanadi).
    expect(pj[0].body.claim_token).toMatch(/^[0-9a-f-]{36}$/);
    expect(pj[1].body.claim_token).toBe(pj[0].body.claim_token);
    expect(a.claim_token).toBe(pj[0].body.claim_token);
  });

  it("auto ishlayotganda qo'lda bosish o'sha va'dani oladi (ikki qog'oz chiqmaydi)", async () => {
    server(baseRoutes());
    const p1 = printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    const p2 = printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    const [a, b] = await Promise.all([p1, p2]);
    expect(a.id).toBe(b.id);
    expect(printed).toHaveLength(1);
  });

  it("qo'lda: asl chek → keyingi bosish NUSXA; nusxa raqami chop etishdan OLDIN serverdan, qog'ozda banner", async () => {
    const calls = server(baseRoutes());
    const orig = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(orig).toMatchObject({ copy: "ORIGINAL", status: "PRINTED" });
    // Bu qurilmada yozuv yo'q edi — avval server jurnali so'raldi.
    expect(printJobCalls(calls)[0]).toMatchObject({ method: "GET" });
    expect(printJobCalls(calls)[0].url).toContain(`doc_type=SALE&doc_id=${SALE_ID}`);

    calls.length = 0;
    const rep = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(rep).toMatchObject({ copy: "REPRINT", copy_no: 1, status: "PRINTED", reported: true });
    expect(rep.id).not.toBe(orig.id);
    const order = calls.map((c) => `${c.method} ${c.url.replace(/^.*\/api\/v1/, "").split("?")[0]}`);
    expect(order).toEqual([
      "POST /print-jobs", `GET /sales/${SALE_ID}/receipt`, `PATCH /print-jobs/${rep.id}`,
    ]);
    expect(calls[0].body).toMatchObject({ id: rep.id, copy: "REPRINT", status: "PENDING", attempts: 0 });
    expect(calls[2].body).toMatchObject({ status: "PRINTED", attempts: 1 });
    expect(calls[0].body).not.toHaveProperty("claim_token"); // nusxa band qilinmaydi
    expect(calls[2].body).not.toHaveProperty("claim_token");
    expect(printed[1].copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(printed[1].html).toContain("*** NUSXA #1 ***");
    expect(listJobs({ key: docKey("SALE", SALE_ID) }).map((j) => j.copy)).toEqual(["ORIGINAL", "REPRINT"]);
  });

  it("boshqa qurilmada ASL chop etilgan (server jurnali) → bu yerda NUSXA", async () => {
    server(baseRoutes([[/\/print-jobs\?/, [{ id: "srv-orig", copy: "ORIGINAL", status: "PRINTED", attempts: 1 }]]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j.copy).toBe("REPRINT");
    expect(printed[0].html).toContain("NUSXA");
  });

  it("server ASL yozuvi FAILED → AYNAN o'sha id bilan qayta uriniladi (nusxa emas)", async () => {
    const calls = server(baseRoutes([[/\/print-jobs\?/, [{ id: "srv-1", copy: "ORIGINAL", status: "FAILED", attempts: 2 }]]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j).toMatchObject({ id: "srv-1", copy: "ORIGINAL", status: "PRINTED", attempts: 3, reported: true });
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    const patches = printJobCalls(calls).filter((c) => c.method === "PATCH");
    // Avval band qilish (PENDING), keyin yakuniy holat — ikkalasi AYNAN o'sha id.
    expect(patches.map((c) => c.body.status)).toEqual(["PENDING", "PRINTED"]);
    for (const c of patches) expect(c.url).toMatch(/\/print-jobs\/srv-1$/);
    expect(patches[1].body).toMatchObject({ status: "PRINTED", attempts: 3 });
  });
});

describe("xato, qayta urinish, uzilib qolgan yozuv", () => {
  it("printer xatosi → FAILED (kod bilan); qo'lda bosish AYNAN o'sha ASL yozuvni qayta chop etadi", async () => {
    const calls = server(baseRoutes());
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(bad).toMatchObject({ status: "FAILED", code: "PAPER_OUT", error: "qog'oz tugagan", attempts: 1, reported: true });
    expect(printJobCalls(calls)[0].body).toMatchObject({ status: "PENDING", copy: "ORIGINAL" }); // band qilish
    expect(printJobCalls(calls)[1].body).toMatchObject({ status: "FAILED", error: "PAPER_OUT: qog'oz tugagan" });

    // Avto — ASL yozuv bor (FAILED) — qayta chop ETMAYDI.
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(printed).toHaveLength(1);

    printerAnswer = () => ({ ok: true });
    const ok = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(ok.id).toBe(bad.id);
    expect(ok).toMatchObject({ copy: "ORIGINAL", status: "PRINTED", attempts: 2, error: null, code: null });
    expect(printed).toHaveLength(2);
    expect(printed[1].copy).toEqual({ kind: "ORIGINAL" });
    const patch = printJobCalls(calls).filter((c) => c.method === "PATCH").pop();
    expect(patch?.body).toMatchObject({ status: "PRINTED", attempts: 2, error: null });
  });

  it("retryJob: FAILED → o'sha id; PRINTED → qayta chop etmaydi", async () => {
    server(baseRoutes());
    printerAnswer = () => ({ ok: false, code: "OFFLINE", error: "ECONNREFUSED" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    printerAnswer = () => ({ ok: true });
    const ok = await retryJob(bad.id);
    expect(ok).toMatchObject({ id: bad.id, status: "PRINTED", attempts: 2 });
    const same = await retryJob(bad.id);
    expect(same.status).toBe("PRINTED");
    expect(printed).toHaveLength(2);
    await expect(retryJob("yoq")).rejects.toThrow();
  });

  it("uzilib qolgan PENDING (ilova yopilgan) → qo'lda bosish o'sha yozuvni davom ettiradi", async () => {
    server(baseRoutes());
    const stale: LocalPrintJob = {
      id: "stale-1", key: docKey("SALE", SALE_ID), doc_type: "SALE", doc_id: SALE_ID, client_uuid: null, copy: "ORIGINAL",
      copy_no: null, status: "PENDING", attempts: 1, error: null, code: null, transport: "virtual", printer: null,
      created_at: "2026-09-19T09:00:00.000Z", updated_at: "2026-09-19T09:00:00.000Z", printed_at: null, reported: false, provisional: false,
    };
    cacheSet(PRINT_JOBS_KEY, [stale]);
    const auto = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(auto.id).toBe("stale-1");
    expect(printed).toHaveLength(0);
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j).toMatchObject({ id: "stale-1", status: "PRINTED", attempts: 2, copy: "ORIGINAL" });
  });

  it("DTO: 503 ikki marta → uchinchi urinishda chiqadi; 404 → darhol FAILED, chop etilmaydi", async () => {
    let n = 0;
    const calls = server(baseRoutes([[/\/sales\/[^/]+\/receipt/, () => (++n <= 2 ? { __status: 503, detail: "x" } : SALE)]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.status).toBe("PRINTED");
    expect(calls.filter((c) => /\/receipt$/.test(c.url))).toHaveLength(3);

    _resetPrintRuntime();
    localStorage.clear();
    printed = [];
    const calls2 = server(baseRoutes([[/\/sales\/[^/]+\/receipt/, { __status: 404, detail: "Chek topilmadi" }]]));
    const f = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    // Chek ma'lumoti yo'q — printer aybsiz: barqaror kod NO_DATA (ekran "chek ma'lumoti olinmadi" deydi).
    expect(f).toMatchObject({ status: "FAILED", code: "NO_DATA" });
    expect(f.error).toBeTruthy();
    expect(calls2.filter((c) => /\/receipt$/.test(c.url))).toHaveLength(1);
    expect(printed).toHaveLength(0);
  }, 10_000);

  it("qaytarish cheki `/returns/{id}/receipt` dan", async () => {
    const ret: ReceiptDTO = { ...SALE, kind: "RETURN", doc: { ...SALE.doc, id: "r-1", number: "QAY-7" }, payments: [], refund: { method: "cash", amount: SALE.totals.total } };
    const calls = server(baseRoutes([[/\/returns\/r-1\/receipt/, ret]]));
    const j = await printDoc({ doc_type: "RETURN", doc_id: "r-1", mode: "manual" });
    expect(j).toMatchObject({ doc_type: "RETURN", status: "PRINTED", key: "RETURN:r-1" });
    expect(calls.some((c) => /\/returns\/r-1\/receipt$/.test(c.url))).toBe(true);
    expect(printed[0].html).toContain("QAY-7");
  });

  it("argument xatolari", async () => {
    await expect(printDoc({ doc_type: "SALE", mode: "auto" })).rejects.toThrow();
    await expect(printDoc({ doc_type: "X" as never, doc_id: "a", mode: "auto" })).rejects.toThrow();
  });
});

describe("oflayn sotuv va serverga hisobot", () => {
  const CU = "abcdef12-3456-4789-8abc-def012345678";
  const provisional = () => provisionalSaleReceipt({
    client_uuid: CU,
    lines: [{ name: "Non", qty: "2", unit_price: "4000", weighted: false }, { name: "Pomidor", qty: "0.352", unit_price: "12000", weighted: true, unit: "kg" }],
    payments: [{ method: "cash", amount: "12224" }],
    given: "20000", change: "7776", total: "12224",
    store: SALE.store, cashier: "Dilnoza", issued_at_local: "19.09.2026 14:40", template: { ...BUILTIN_TEMPLATE },
  });

  it("vaqtinchalik DTO: OFFLINE-raqam + banner; server id'siz hisobot yo'q; bindDocId → flush POST", async () => {
    const calls = server(baseRoutes());
    const j = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", provisional: true, reported: false, doc_id: null, key: `SALE:${CU}` });
    expect(printed[0].html).toContain("OFFLINE-ABCDEF12");
    expect(printed[0].html).toContain("OFLAYN");
    expect(printJobCalls(calls)).toEqual([]);
    expect(calls.some((c) => /\/sales\//.test(c.url))).toBe(false); // server DTO so'ralmaydi (id yo'q)

    await flushPrintReports();
    expect(printJobCalls(calls)).toEqual([]);

    bindDocId(CU, SALE_ID);
    const bound = listJobs({ key: `SALE:${CU}` });
    expect(bound).toHaveLength(1);
    expect(bound[0]).toMatchObject({ doc_id: SALE_ID, key: docKey("SALE", SALE_ID), reported: false });
    await flushPrintReports();
    const pj = printJobCalls(calls);
    expect(pj).toHaveLength(1);
    expect(pj[0]).toMatchObject({ method: "POST" });
    expect(pj[0].body).toMatchObject({ id: j.id, doc_id: SALE_ID, copy: "ORIGINAL", status: "PRINTED", attempts: 1 });
    expect(listJobs()[0].reported).toBe(true);
    await flushPrintReports();
    expect(printJobCalls(calls)).toHaveLength(1); // yuborilgani qayta ketmaydi
  });

  it("oflayn DTO ilova qayta ishga tushganidan keyin ham saqlanadi: printer xatosi → restart → Qayta urinish", async () => {
    server(baseRoutes());
    printerAnswer = () => ({ ok: false, code: "OFFLINE", error: "ECONNREFUSED" });
    const j = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "auto" });
    expect(j).toMatchObject({ status: "FAILED", code: "OFFLINE", provisional: true });
    // Ilova qayta ishga tushdi: modul xotirasi bo'shadi, localStorage qoldi.
    _resetPrintRuntime();
    printerAnswer = () => ({ ok: true });
    const r = await retryJob(j.id);
    expect(r).toMatchObject({ id: j.id, status: "PRINTED", attempts: 2, provisional: true });
    expect(printed.at(-1)!.html).toContain("OFFLINE-ABCDEF12");
    // Muvaffaqiyatdan keyin saqlangan DTO o'chiriladi (localStorage o'smaydi).
    expect(Object.keys(localStorage).some((k) => k.startsWith("savdoos_print_dtos") && localStorage.getItem(k) !== "{}")).toBe(false);
  });

  it("409 PRINT_ORIGINAL_EXISTS qog'ozdan KEYIN (o'z sotuvi, band qilish tarmoqsiz o'tgan) → qayd etiladi, qayta chop etilmaydi", async () => {
    let claimDown = true;
    const calls = server(baseRoutes([[/\/print-jobs$/, (c: Call) => {
      if (claimDown && c.body.status === "PENDING") { claimDown = false; throw new TypeError("Failed to fetch"); }
      return { __status: 409, detail: ORIGINAL_EXISTS };
    }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", reported: true, code: "PRINT_ORIGINAL_EXISTS", error: "PRINT_ORIGINAL_EXISTS", copy: "ORIGINAL" });
    expect(printed).toHaveLength(1);
    await flushPrintReports();
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(2); // band qilish + hisobot
  });

  it("409 PRINT_ORIGINAL_EXISTS band qilishda (qog'ozdan OLDIN) → ASL chiqmaydi, NUSXA (server raqami bilan); avto qayta chiqarmaydi", async () => {
    const j0 = journal();
    j0.rows.set("boshqa", { id: "boshqa", doc_type: "SALE", doc_id: SALE_ID, copy: "ORIGINAL", copy_no: 0, status: "PRINTED", attempts: 1 });
    const calls = server(baseRoutes([...j0.routes]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(j).toMatchObject({ copy: "REPRINT", copy_no: 1, status: "PRINTED", reported: true });
    expect(printed.map((p) => p.copy)).toEqual([{ kind: "REPRINT", no: 1 }]);
    expect(printed[0].html).toContain("NUSXA #1");
    // Band qilish rad etildi — mahalliy ASL yozuv yaratilmagan, serverda ASL bitta.
    expect(listJobs().map((x) => x.copy)).toEqual(["REPRINT"]);
    expect([...j0.rows.values()].filter((r) => r.copy === "ORIGINAL")).toHaveLength(1);
    // Avto (StrictMode qayta mount) — hech narsa chiqarmaydi.
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(printed).toHaveLength(1);
    expect(printJobCalls(calls).filter((c) => c.method === "POST" && c.body.copy === "ORIGINAL")).toHaveLength(1);
  });

  it("tarmoq xatosi → reported:false; keyingi flush yuboradi (id o'sha — server takrorni PATCH deb qabul qiladi)", async () => {
    let down = true;
    const calls = server(baseRoutes([[/\/print-jobs$/, (c: Call) => {
      if (down) throw new TypeError("Failed to fetch");
      return jobOut(c.body);
    }]]));
    // O'z sotuvi (client_uuid): band qilib bo'lmasa ham ASL chiqadi (hisobot keyinroq).
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" });
    expect(j).toMatchObject({ status: "PRINTED", reported: false, copy: "ORIGINAL" });
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    down = false;
    await flushPrintReports();
    const posts = printJobCalls(calls).filter((c) => c.method === "POST");
    expect(posts.map((c) => c.body.status)).toEqual(["PENDING", "PRINTED", "PRINTED"]); // band, hisobot, flush
    expect(posts[2].body.id).toBe(j.id);
    expect(listJobs()[0]).toMatchObject({ reported: true, copy_no: 0 });
  });

  it("poyga: flush eski PENDING holatni yuborayotganda chop etish tugasa — yakuniy holat ham yuboriladi", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => { release = r; });
    let first = true;
    const calls = server(baseRoutes([[/\/print-jobs$/, async (c: Call) => {
      if (first) { first = false; await held; }
      return jobOut(c.body);
    }]]));
    const stale: LocalPrintJob = {
      id: "race-1", key: docKey("SALE", SALE_ID), doc_type: "SALE", doc_id: SALE_ID, client_uuid: null, copy: "ORIGINAL",
      copy_no: null, status: "PENDING", attempts: 1, error: null, code: null, transport: "virtual", printer: null,
      created_at: "2026-09-19T09:00:00.000Z", updated_at: "2026-09-19T09:00:00.000Z", printed_at: null, reported: false, provisional: false,
    };
    cacheSet(PRINT_JOBS_KEY, [stale]);
    const flush = flushPrintReports(); // POST (PENDING) — server javobi ushlab turiladi
    const printing = printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    await waitFor(() => expect(printed).toHaveLength(1));
    release();
    const j = await printing;
    await flush;
    expect(j).toMatchObject({ id: "race-1", status: "PRINTED", attempts: 2, reported: true, copy_no: 0 });
    const pj = printJobCalls(calls).filter((c) => c.method !== "GET");
    // flush (eski PENDING), band qilish (PENDING — flush javobini kutmaydi), yakuniy PRINTED — oxirgisi.
    expect(pj.map((c) => [c.method, c.body.status])).toEqual([["POST", "PENDING"], ["POST", "PENDING"], ["PATCH", "PRINTED"]]);
  });

  it("5xx hisobot → keyinroq; 404 (hujjat ko'rinmaydi, EGASI olgan) → doimiy, qayta yuborilmaydi", async () => {
    const calls = server(baseRoutes([[/\/print-jobs$/, { __status: 404, detail: "Chek topilmadi" }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.reported).toBe(true);
    const n = printJobCalls(calls).filter((c) => c.method === "POST").length; // band qilish + hisobot
    await flushPrintReports();
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(n);
  });

  it("jurnal: 300 dan oshsa eski HISOBOT BERILGANLAR o'chadi, hisobot berilmaganlar saqlanadi", async () => {
    const mk = (i: number, reported: boolean, status: LocalPrintJob["status"] = "PRINTED"): LocalPrintJob => ({
      id: `j-${i}`, key: `SALE:d-${i}`, doc_type: "SALE", doc_id: `d-${i}`, client_uuid: null, copy: "ORIGINAL", copy_no: 0,
      status, attempts: 1, error: null, code: null, transport: "virtual", printer: null,
      created_at: new Date(Date.UTC(2026, 8, 1, 0, 0, i)).toISOString(), updated_at: "2026-09-01T00:00:00.000Z",
      printed_at: null, reported, provisional: false,
    });
    const old = [mk(0, false, "FAILED"), mk(1, false, "PENDING"), mk(2, false, "PRINTED")];
    const rest = Array.from({ length: 320 }, (_, i) => mk(i + 3, true));
    const offline = { ...mk(999, false), id: "off", doc_id: null, client_uuid: "cu-x", key: "SALE:cu-x" };
    cacheSet(PRINT_JOBS_KEY, [...old, ...rest, offline]);
    bindDocId("cu-x", "s-x"); // saqlash → kesish
    const all = listJobs();
    expect(all).toHaveLength(300);
    for (const id of ["j-0", "j-1", "j-2", "off"]) expect(all.some((j) => j.id === id), id).toBe(true);
    expect(all.some((j) => j.id === "j-3")).toBe(false); // eng eski hisobot berilgani ketdi
  });
});

describe("printTestReceipt — hech narsa YOZMAYDI", () => {
  it("server namunasi: faqat GET, jurnal bo'sh, TEST banneri", async () => {
    const sample = { ...sampleReceipt("sale", SALE.store), logo: null };
    const calls = server(baseRoutes([[/\/receipt\/sample/, sample]]));
    const r = await printTestReceipt("sale");
    expect(r).toEqual({ ok: true });
    expect(writes(calls)).toEqual([]);
    expect(calls.some((c) => /\/receipt\/sample\?kind=sale/.test(c.url))).toBe(true);
    expect(listJobs()).toEqual([]);
    expect(cacheGet(PRINT_JOBS_KEY, null)).toBeNull();
    expect(printed[0].html).toContain("*** TEST PRINT ***");
    expect(printed[0].copy).toBeNull();
  });

  it("server yiqilsa — mahalliy namuna (profil keshidagi do'kon nomi bilan), baribir faqat GET", async () => {
    const calls = server(baseRoutes([[/\/receipt\/sample/, { __status: 503, detail: "x" }]]));
    await getReceiptProfile();
    const r = await printTestReceipt("mixed");
    expect(r.ok).toBe(true);
    expect(writes(calls)).toEqual([]);
    expect(printed[0].html).toContain("TEST PRINT");
    expect(printed[0].html).toContain("Fayzan Market");
    // Mahalliy namunada logo havolasi yo'q — kassa (shu filial) profilining logosi.
    expect(printed[0].doc.blocks.some((b) => b.t === "logo")).toBe(true);
  });

  // Filial profili: o'z logosi va do'kon QR'i bor (xodimning filiali ustamasi).
  const BRANCH_PROFILE = {
    ...PROFILE,
    effective: { ...PROFILE.effective, qr_mode: "store_url" as const, qr_url: "https://fayzan.uz" },
    store_qr: { payload: "2609191288", size: 21, matrix: QR_MATRIX_1288 },
  };

  it("5F.2 R2/R9: kompaniya namunasi (logo:null, qr:null) — xodim FILIALI logosi/QR'i qog'ozga TUSHMAYDI", async () => {
    const companySample: ReceiptDTO = {
      ...sampleReceipt("sale", SALE.store), logo: null, qr: null,
      template: { ...BUILTIN_TEMPLATE, show_logo: true, qr_mode: "store_url" },
    };
    const calls = server(baseRoutes([[/\/receipt\/profile/, BRANCH_PROFILE], [/\/receipt\/sample/, companySample]]));
    await getReceiptProfile(); // kassa keshida filial profili (logo + store_qr)
    const r = await printTestReceipt("sale", { scope: "company" });
    expect(r).toEqual({ ok: true });
    expect(calls.some((c) => /\/receipt\/sample\?kind=sale&scope=company/.test(c.url))).toBe(true);
    const kinds = printed[0].doc.blocks.map((b) => b.t);
    expect(kinds).not.toContain("logo");
    expect(kinds).not.toContain("qr");
    // Filial doirasidagi server namunasi ham — logo faqat `dto.logo` havolasi bo'yicha.
    printed = [];
    server(baseRoutes([[/\/receipt\/profile/, BRANCH_PROFILE], [/\/receipt\/sample/, { ...companySample, logo: SALE.logo }]]));
    await printTestReceipt("sale", { branch_id: "b1" });
    expect(printed[0].doc.blocks.map((b) => b.t)).toContain("logo");
  });

  it("5F.2 R2: kompaniya doirasi, server namunasi yo'q (403/oflayn) — mahalliy namuna FILIAL profilisiz", async () => {
    server(baseRoutes([[/\/receipt\/profile/, BRANCH_PROFILE], [/\/receipt\/sample/, { __status: 403, detail: "Ruxsat yo'q" }]]));
    await getReceiptProfile();
    const r = await printTestReceipt("sale", { scope: "company" });
    expect(r.ok).toBe(true);
    const kinds = printed[0].doc.blocks.map((b) => b.t);
    expect(kinds).not.toContain("logo");
    expect(kinds).not.toContain("qr");
    expect(printed[0].html).toContain("TEST PRINT");
  });

  it("5F.2 R10: `opts.dto` — AYNAN o'sha DTO chop etiladi (TEST majburiy), server namunasi so'ralmaydi, hech narsa yozilmaydi", async () => {
    const calls = server(baseRoutes([[/\/receipt\/profile/, BRANCH_PROFILE], [/\/receipt\/sample/, SALE]]));
    await getReceiptProfile();
    calls.length = 0;
    const base = sampleReceipt("sale", SALE.store);
    const dto: ReceiptDTO = {
      ...base, test: false, logo: null, qr: null,
      doc: { ...base.doc, number: "#PREVIEW-42" },
      template: { ...BUILTIN_TEMPLATE, footer: "Oldindan korish bilan bir xil", qr_mode: "store_url" },
    };
    const r = await printTestReceipt("sale", { scope: "company", dto });
    expect(r).toEqual({ ok: true });
    expect(calls.filter((c) => /\/receipt\/sample/.test(c.url))).toEqual([]);
    expect(writes(calls)).toEqual([]);
    expect(listJobs()).toEqual([]);
    expect(printed).toHaveLength(1);
    expect(printed[0].copy).toBeNull();
    expect(printed[0].html).toContain("#PREVIEW-42");
    expect(printed[0].html).toContain("Oldindan korish bilan bir xil");
    expect(printed[0].html).toContain("*** TEST PRINT ***");
    const kinds = printed[0].doc.blocks.map((b) => b.t);
    expect(kinds).not.toContain("logo"); // DTO'da logo yo'q — profil logosi qo'shilmaydi
    expect(kinds).not.toContain("qr");
    // DTO'dagi logo havolasi profil logosiga mos — o'sha rasm (qo'shimcha so'rovsiz).
    printed = [];
    await printTestReceipt("sale", { dto: { ...dto, logo: SALE.logo } });
    expect(printed[0].doc.blocks.map((b) => b.t)).toContain("logo");
    expect(calls.filter((c) => /\/receipt\/(sample|logos)/.test(c.url))).toEqual([]);
    // Buzilgan DTO — hech narsa chop etilmaydi (boshqa narsa jimgina chiqmasin).
    printed = [];
    expect(await printTestReceipt("sale", { dto: { schema: "x" } as never })).toMatchObject({ ok: false, code: "FAILED" });
    expect(printed).toEqual([]);
  });

  it("server `test:false` qaytarsa ham TEST banneri majburiy (sotuv cheki bilan adashmasin)", async () => {
    server(baseRoutes([[/\/receipt\/sample/, SALE]]));
    await printTestReceipt("sale");
    expect(printed[0].html).toContain("TEST PRINT");
  });

  it("printer xatosi natijada qaytadi", async () => {
    server(baseRoutes([[/\/receipt\/sample/, sampleReceipt("sale")]]));
    printerAnswer = () => ({ ok: false, code: "NO_PRINTER", error: "x" });
    expect(await printTestReceipt()).toMatchObject({ ok: false, code: "NO_PRINTER" });
  });
});

describe("uzatish: Electron ko'prigi va brauzer", () => {
  function bridge(over: Record<string, any> = {}) {
    const b = {
      listPrinters: vi.fn(async () => [{ name: "XP-80C" }]),
      print: vi.fn(async () => ({ ok: true })),
      printHtml: vi.fn(async () => ({ ok: true })),
      printEscPos: vi.fn(async () => ({ ok: true })),
      ...over,
    };
    window.savdoosPrint = b as never;
    delete window.__BINOS_VIRTUAL_PRINTER__;
    return b;
  }

  it("ESC/POS LAN: renderer BAYT yubormaydi — bloklar + profil + manzil; nusxa/kesish shablondan", async () => {
    server(baseRoutes());
    const b = bridge();
    writePrinterConfig({ transport: "escpos_lan", host: "192.168.1.50", port: 9101, profile_id: "epson80" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", transport: "escpos_lan", printer: "192.168.1.50:9101" });
    expect(b.printEscPos).toHaveBeenCalledTimes(1);
    const req = b.printEscPos.mock.calls[0][0] as any;
    expect(Object.keys(req).sort()).toEqual(["copies", "cut", "doc", "profile", "target"]);
    expect(req.target).toEqual({ kind: "lan", host: "192.168.1.50", port: 9101 });
    expect(req.profile).toMatchObject({ id: "epson80", width_mm: 80, cols: 48 });
    expect(req.copies).toBe(SALE.template.copies);
    expect(req.cut).toBe(SALE.template.auto_cut);
    expect(Array.isArray(req.doc.blocks)).toBe(true);
    const logo = req.doc.blocks.find((x: any) => x.t === "logo");
    expect(logo).toBeTruthy();
    expect(logo.png_data_uri).toBeUndefined(); // main'ga faqat raster bitlari
    expect(b.printHtml).not.toHaveBeenCalled();
  });

  it("ESC/POS LAN manzili yo'q → NO_PRINTER (ko'prik chaqirilmaydi)", async () => {
    server(baseRoutes());
    const b = bridge();
    writePrinterConfig({ transport: "escpos_lan", profile_id: "generic80" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "FAILED", code: "NO_PRINTER" });
    expect(b.printEscPos).not.toHaveBeenCalled();
  });

  it("tizim printeri: printHtml (printer, 58 mm, nusxalar); xato kodi jurnalga yoziladi", async () => {
    server(baseRoutes());
    const b = bridge({ printHtml: vi.fn(async () => ({ ok: false, code: "NO_PRINTER", error: "printer topilmadi: XP-80C" })) });
    writePrinterConfig({ transport: "system", printer: "XP-80C", width_mm: 58, profile_id: "generic80" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "FAILED", code: "NO_PRINTER", transport: "system", printer: "XP-80C" });
    const req = b.printHtml.mock.calls[0][0] as any;
    expect(req).toMatchObject({ printer: "XP-80C", widthMm: 58, copies: 1, pageMode: "exact" });
    // Sahifa balandligi — chekning o'zi (+3 mm), main `pageSize` ga aylantiradi (5F.1 #28).
    const doc = layoutReceipt(SALE, { width_mm: 58, lang: "uz", template: SALE.template, logo: LOGO_64x16, copy: { kind: "ORIGINAL" } });
    expect(req.heightMm).toBe(Math.ceil(docHeightMm(doc)) + 3);
    expect(Number.isInteger(req.heightMm) && req.heightMm >= 20 && req.heightMm <= 3276).toBe(true);
  });

  it("HTML sahifa rejimi: sozlamada 'driver' → pageMode driver; noma'lum/eski sozlama → exact", async () => {
    server(baseRoutes());
    const b = bridge();
    writePrinterConfig({ transport: "system", printer: "XP-80C", profile_id: "generic80", page_size: "driver" });
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(b.printHtml.mock.calls[0][0]).toMatchObject({ pageMode: "driver" });
    // 5F.2 R4/R14: "driver" — CSS `@page` da ham o'lcham YO'Q, balandlik yuborilmaydi (5F'dan oldingi xulq).
    const drv = b.printHtml.mock.calls[0][0] as any;
    expect(drv).not.toHaveProperty("heightMm");
    expect(drv.html).toContain("@page { margin: 0 }");
    expect(drv.html).not.toMatch(/@page\s*\{[^}]*size:/);
    // "exact" — CSS o'lcham AYNAN Electron pageSize bilan bir xil.
    writePrinterConfig({ transport: "system", printer: "XP-80C", profile_id: "generic80", page_size: "exact" });
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    const ex = b.printHtml.mock.calls[1][0] as any;
    expect(ex).toMatchObject({ pageMode: "exact", widthMm: 80 });
    expect(ex.html).toContain(`@page { size: 80mm ${ex.heightMm}mm; margin: 0 }`);
    expect(sanitizePrinterConfig({ transport: "system", profile_id: "generic80" }).page_size).toBe("exact");
    expect(sanitizePrinterConfig({ transport: "system", profile_id: "generic80", page_size: "A4" }).page_size).toBe("exact");
    expect(sanitizePrinterConfig({ transport: "system", profile_id: "generic80", page_size: "driver" }).page_size).toBe("driver");
  });

  it("ESC/POS: '(58 mm)' printer modeli + 80 mm shablon → 58 mm / 32 ustun (layout va profil bir xil)", async () => {
    server(baseRoutes());
    const b = bridge();
    expect(SALE.template.width_mm).toBe(80);
    writePrinterConfig({ transport: "escpos_lan", host: "192.168.1.50", port: 9100, profile_id: "xprinter58" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.status).toBe("PRINTED");
    const req = b.printEscPos.mock.calls[0][0] as any;
    expect(req.profile).toMatchObject({ id: "xprinter58", width_mm: 58, cols: 32, dots: 384 });
    expect(req.doc).toMatchObject({ width_mm: 58, cols: 32 });
    const cfg = readPrinterConfig();
    expect(effectiveWidth(cfg, 80)).toBe(58);
    expect(effectiveProfile(cfg, 80)).toMatchObject({ width_mm: 58, cols: 32 });
    // Qo'lda tanlangan kenglik ustun; tizim printeri — shablon kengligi; noma'lum model — shablon.
    expect(effectiveWidth({ ...cfg, width_mm: 80 }, 58)).toBe(80);
    expect(effectiveWidth({ ...cfg, transport: "system" }, 80)).toBe(80);
    expect(effectiveWidth({ ...cfg, transport: "escpos_spooler", profile_id: "epson80" }, 58)).toBe(80);
    expect(effectiveWidth({ transport: "escpos_lan", profile_id: "yoq" }, 58)).toBe(58);
  });

  it("5F.2 R7: standart model 'generic' — kenglik shablondan: 58 mm shablon + LAN (model tanlanmagan) → 58 mm / 32 ustun", async () => {
    const s58: ReceiptDTO = { ...SALE, template: { ...SALE.template, width_mm: 58 } };
    server(baseRoutes([[/\/sales\/[^/]+\/receipt/, s58]]));
    const b = bridge();
    // PrinterSetup'da faqat ulanish turi va IP o'zgartirildi — model/kenglik standartda qoldi.
    writePrinterConfig({ ...defaultPrinterConfig(), transport: "escpos_lan", host: "192.168.1.50" });
    const cfg = readPrinterConfig();
    expect(cfg).toMatchObject({ profile_id: "generic" });
    expect(cfg.width_mm ?? null).toBeNull();
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.status).toBe("PRINTED");
    const req = b.printEscPos.mock.calls[0][0] as any;
    expect(req.profile).toMatchObject({ width_mm: 58, cols: 32, dots: 384 });
    expect(req.doc).toMatchObject({ width_mm: 58, cols: 32 });
    // Shablon 80 bo'lsa — 80 (model kenglikka bog'lanmagan); qo'lda kenglik — ustun.
    expect(effectiveWidth(cfg, 80)).toBe(80);
    expect(effectiveProfile(cfg, 80)).toMatchObject({ width_mm: 80, cols: 48 });
    expect(effectiveWidth({ ...cfg, width_mm: 58 }, 80)).toBe(58);
    // Aniq tanlangan model saqlanadi (generic80 ham — tanlanganmi, bilib bo'lmaydi); yo'q/noma'lum → generic.
    expect(effectiveWidth({ transport: "escpos_lan", profile_id: "generic80" }, 58)).toBe(80);
    expect(sanitizePrinterConfig({ transport: "escpos_lan", profile_id: "generic80" }).profile_id).toBe("generic80");
    expect(sanitizePrinterConfig({ transport: "escpos_lan" }).profile_id).toBe("generic");
    expect(sanitizePrinterConfig({ transport: "escpos_lan", profile_id: "yoq" }).profile_id).toBe("generic");
    expect(defaultPrinterConfig().profile_id).toBe("generic");
  });

  it("5F.2 R6: Chromium chegarasidan (3276 mm) uzun chek → shu chek 'driver' rejimida (pageSize ham, CSS o'lcham ham yo'q)", async () => {
    const item = SALE.lines[0];
    const long: ReceiptDTO = { ...SALE, lines: Array.from({ length: 900 }, (_, i) => ({ ...item, name: `Mahsulot ${i + 1}` })) };
    server(baseRoutes([[/\/sales\/[^/]+\/receipt/, long]]));
    const b = bridge();
    writePrinterConfig({ transport: "system", printer: "XP-80C", profile_id: "generic", page_size: "exact" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.status).toBe("PRINTED");
    const req = b.printHtml.mock.calls[0][0] as any;
    const doc = layoutReceipt(long, { width_mm: 80, lang: "uz", template: long.template, logo: LOGO_64x16, copy: { kind: "ORIGINAL" } });
    expect(docHeightMm(doc)).toBeGreaterThan(3276);
    expect(req.pageMode).toBe("driver");
    expect(req).not.toHaveProperty("heightMm");
    expect(req.html).not.toMatch(/@page\s*\{[^}]*size:/);
    // Oddiy (qisqa) chek ayni sozlamada — hamon aniq o'lcham.
    server(baseRoutes());
    await printDoc({ doc_type: "SALE", doc_id: "11111111-2222-4333-8444-555555555555", mode: "auto" });
    const short = b.printHtml.mock.calls.at(-1)![0] as any;
    expect(short).toMatchObject({ pageMode: "exact" });
    expect(short.heightMm).toBeLessThan(3276);
  });

  it("5F.2 R14: eski ko'prik (printHtml yo'q, pageSize bermaydi) — HTML ham o'lchamsiz", async () => {
    server(baseRoutes());
    const b = bridge({ printHtml: undefined });
    writePrinterConfig({ transport: "system", printer: "XP-80C", profile_id: "generic", page_size: "exact" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.status).toBe("PRINTED");
    expect(b.print).toHaveBeenCalledTimes(1);
    const html = (b.print.mock.calls[0] as unknown as [string])[0];
    expect(html).toContain("#1288");
    expect(html).not.toMatch(/@page\s*\{[^}]*size:/);
  });

  it("Electron ko'prigi javob bermasa (IPC osilgan) → 90 s da FAILED/TIMEOUT; navbat bo'shaydi, keyingi chek chiqadi", async () => {
    server(baseRoutes([[/\/returns\/r-2\/receipt/, { ...SALE, kind: "RETURN", doc: { ...SALE.doc, id: "r-2", number: "QAY-9" }, payments: [], refund: { method: "cash", amount: SALE.totals.total } }]]));
    let hang = true;
    const b = bridge({
      printHtml: vi.fn(() => (hang ? new Promise(() => undefined) : Promise.resolve({ ok: true }))),
    });
    writePrinterConfig({ transport: "system", profile_id: "generic80" });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const a = printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
      await vi.waitFor(() => expect(b.printHtml).toHaveBeenCalledTimes(1), { interval: 5, timeout: 2000 });
      hang = false;
      const next = printDoc({ doc_type: "RETURN", doc_id: "r-2", mode: "auto" }); // navbatda kutadi
      await vi.advanceTimersByTimeAsync(BRIDGE_TIMEOUT_MS - 1000);
      expect(listJobs({ key: docKey("SALE", SALE_ID) })[0].status).toBe("PENDING");
      await vi.advanceTimersByTimeAsync(2000);
      const ja = await a;
      expect(ja).toMatchObject({ status: "FAILED", code: "TIMEOUT" });
      vi.useRealTimers();
      const jb = await next;
      expect(jb).toMatchObject({ status: "PRINTED", doc_type: "RETURN" });
      expect(b.printHtml).toHaveBeenCalledTimes(2);
      // Qayta urinish ham ishlaydi (osilgan va'da qaytarilmaydi).
      const again = await retryJob(ja.id);
      expect(again).toMatchObject({ status: "PRINTED" });
    } finally {
      vi.useRealTimers();
    }
  }, 20_000);

  it("brauzer (Electron yo'q, virtual printer yo'q): yashirin iframe → PRINTED, transport browser", async () => {
    server(baseRoutes());
    delete window.__BINOS_VIRTUAL_PRINTER__;
    const printSpy = vi.fn();
    const orig = document.body.appendChild.bind(document.body);
    let frame: HTMLIFrameElement | null = null;
    vi.spyOn(document.body, "appendChild").mockImplementation((node: any) => {
      const r = orig(node);
      if (node instanceof HTMLIFrameElement) {
        frame = node;
        (node.contentWindow as any).print = printSpy;
        (node.contentWindow as any).focus = vi.fn(); // jsdom'da focus() yo'q
      }
      return r;
    });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", transport: "browser", error: null });
    expect(printSpy).toHaveBeenCalledTimes(1);
    expect(frame!.contentWindow!.document.body.textContent).toContain("#1288");
    expect(readPrinterConfig().transport).toBe("browser");
  });

  it("boshqa filial logosi (profilda yo'q) → GET /receipt/logos/{id} (bir marta, keshlanadi)", async () => {
    const other = { ...SALE, logo: { id: "logo-b2", sha256: "b".repeat(64) } };
    // O'sha filialning O'Z logosi (profildagi LOGO_64x16 dan farqli bitlar) — qog'ozda aynan u.
    const B2_LOGO = { ...LOGO_64x16, raster_b64: Buffer.alloc(128, 0xa5).toString("base64") };
    const calls = server(baseRoutes([
      [/\/sales\/[^/]+\/receipt/, other],
      [/\/receipt\/logos\/logo-b2/, { id: "logo-b2", variants: { "58": B2_LOGO, "80": B2_LOGO } }],
    ]));
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(calls.filter((c) => /\/receipt\/logos\//.test(c.url))).toHaveLength(1);
    expect(printed[0].html).toContain("data:image/png;base64,");
    const logoOf = (i: number) => printed[i].doc.blocks.find((b) => b.t === "logo") as { raster_b64: string } | undefined;
    expect(logoOf(0)?.raster_b64).toBe(B2_LOGO.raster_b64);
    expect(logoOf(1)?.raster_b64).toBe(B2_LOGO.raster_b64);
    // 5F.2 R9: ilova qayta ishga tushdi (xotira bo'sh) — logo localStorage keshidan, qayta so'ralmaydi.
    _resetPrintRuntime();
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(calls.filter((c) => /\/receipt\/logos\//.test(c.url))).toHaveLength(1);
    expect(logoOf(2)?.raster_b64).toBe(B2_LOGO.raster_b64);
  });

  it("logo olinmasa (403/404/oflayn) — chek logosiz, jimgina (ogohlantirish bilan), xato EMAS (5F.2 R9)", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    try {
      for (const [id, answer] of [
        ["logo-403", { __status: 403, detail: "Ruxsat yo'q" }],
        ["logo-404", { __status: 404, detail: "Logo topilmadi" }],
        ["logo-off", () => { throw new TypeError("Failed to fetch"); }],
      ] as const) {
        _resetPrintRuntime();
        localStorage.clear();
        printed = [];
        const dto = { ...sampleReceipt("sale", SALE.store), logo: { id, sha256: "c".repeat(64) } };
        server(baseRoutes([[/\/receipt\/logos\//, answer]]));
        const r = await printTestReceipt("sale", { dto });
        expect(r, id).toMatchObject({ ok: true, warnings: ["logo_unavailable"] });
        expect(printed[0].doc.blocks.some((b) => b.t === "logo"), id).toBe(false);
      }
      expect(warn).toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});

describe("profil keshi va React hook", () => {
  it("etag: 5 daqiqa ichida qayta so'ralmaydi; force → known_etag; unchanged → kesh; boshqa xodim keshi ishlatilmaydi", async () => {
    let unchanged = false;
    const calls = server([[/\/receipt\/profile/, () => (unchanged ? { etag: "etag-1", unchanged: true } : PROFILE)]]);
    const p1 = await getReceiptProfile();
    expect(p1?.etag).toBe("etag-1");
    await getReceiptProfile();
    expect(calls).toHaveLength(1);
    unchanged = true;
    const p2 = await getReceiptProfile({ force: true });
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain("known_etag=etag-1");
    expect(p2?.logo?.id).toBe(PROFILE.logo.id);
    useAuth.setState({ employee: { ...useAuth.getState().employee!, id: "emp-2" } });
    unchanged = false;
    await getReceiptProfile();
    expect(calls).toHaveLength(3);
    expect(calls[2].url).not.toContain("known_etag"); // boshqa (do'kon kodi noma'lum) xodimning keshi ishlatilmaydi
  });

  it("ayni do'konning boshqa kassiri: kesh ishlatiladi (oflayn chekda logo qoladi), lekin yangilanadi; boshqa do'kon — yo'q", async () => {
    let offline = false;
    const calls = server([[/\/receipt\/profile/, () => { if (offline) throw new TypeError("Failed to fetch"); return PROFILE; }]]);
    useAuth.setState({ employee: { ...useAuth.getState().employee!, company_code: "fayzan1" } });
    await getReceiptProfile();
    expect(calls).toHaveLength(1);
    offline = true;
    useAuth.setState({ employee: { ...useAuth.getState().employee!, id: "emp-2" } });
    const p = await getReceiptProfile(); // boshqa kassir → eskirgan: so'raydi, tarmoq yo'q → kesh
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain("known_etag=etag-1");
    expect(p?.logo?.id).toBe(PROFILE.logo.id);
    useAuth.setState({ employee: { ...useAuth.getState().employee!, company_code: "boshqa" } });
    expect(await getReceiptProfile()).toBeNull();
  });

  it("usePrintJobs: jurnal o'zgarsa qayta chiziladi (oflayn kalit bilan ham)", async () => {
    server(baseRoutes());
    const { result } = renderHook(() => usePrintJobs(docKey("SALE", SALE_ID)));
    expect(result.current).toEqual([]);
    await act(async () => {
      await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    });
    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].status).toBe("PRINTED");
  });
});

describe("qurilma printeri sozlamasi", () => {
  it("printer sozlamasi qurilmada (server nom maydonisiz kalit)", () => {
    writePrinterConfig({ transport: "browser", profile_id: "generic58" });
    expect(localStorage.getItem(PRINTER_CONFIG_KEY)).toContain("generic58");
  });
});

// ── 5F.1: ikki bannersiz ASL chek hech qachon chiqmaydi (#0, #1) ─────────────
describe("ASL chek serverda qog'ozdan OLDIN band qilinadi (5F.1 #0/#1)", () => {
  const origs = () => paper.filter((p) => p.copy?.kind === "ORIGINAL");

  it("S1: POS FAILED → Manager o'zlashtirib ASL chop etdi → POS qo'lda / Qayta urinish → NUSXA (ikkinchi ASL yo'q)", async () => {
    const j0 = journal();
    const calls = server(baseRoutes([...j0.routes]));
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(bad).toMatchObject({ copy: "ORIGINAL", status: "FAILED", reported: true });
    expect(j0.rows.get(bad.id)).toMatchObject({ copy: "ORIGINAL", status: "FAILED" });

    onDevice("manager", MANAGER);
    printerAnswer = () => ({ ok: true });
    const m = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(m).toMatchObject({ id: bad.id, copy: "ORIGINAL", status: "PRINTED" }); // o'zlashtirildi
    expect(j0.rows.get(bad.id)?.status).toBe("PRINTED");
    expect(origs()).toHaveLength(1);

    onDevice("pos", CASHIER);
    calls.length = 0;
    const p1 = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" });
    expect(p1).toMatchObject({ copy: "REPRINT", copy_no: 1, status: "PRINTED" });
    expect(origs()).toHaveLength(1); // ikkinchi bannersiz ASL YO'Q
    expect(printed.at(-1)!.html).toContain("NUSXA #1");
    // Band qilish rad etildi (PRINTED → PENDING = PRINT_JOB_FINAL) — mahalliy ASL qayta hech qachon ASL emas.
    const claim = printJobCalls(calls).find((c) => c.method === "PATCH" && c.body.status === "PENDING");
    expect(claim?.url).toMatch(new RegExp(`/print-jobs/${bad.id}$`));
    expect(listJobs().find((x) => x.id === bad.id)).toMatchObject({ code: "PRINT_ORIGINAL_EXISTS", reported: true, status: "FAILED" });

    // PrintStatus "Qayta urinish" (retryJob) ham — faqat NUSXA, band qilish so'rovisiz.
    calls.length = 0;
    const p2 = await retryJob(bad.id);
    expect(p2).toMatchObject({ copy: "REPRINT", copy_no: 2, status: "PRINTED" });
    expect(origs()).toHaveLength(1);
    expect(printJobCalls(calls).some((c) => c.body?.copy === "ORIGINAL" || c.body?.status === "PENDING" && c.method === "PATCH")).toBe(false);
  });

  it("S1 teskari: Manager Qayta urinish (retryJob) ham band qilishdan o'tadi — POS allaqachon chop etgan bo'lsa NUSXA", async () => {
    const j0 = journal();
    server(baseRoutes([...j0.routes]));
    printerAnswer = () => ({ ok: false, code: "OFFLINE", error: "x" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    onDevice("manager", MANAGER);
    const m = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" }); // o'zlashtirdi, yana xato
    expect(m).toMatchObject({ id: bad.id, status: "FAILED" });
    onDevice("pos", CASHIER);
    printerAnswer = () => ({ ok: true });
    expect(await retryJob(bad.id)).toMatchObject({ copy: "ORIGINAL", status: "PRINTED" });
    onDevice("manager", MANAGER);
    const again = await retryJob(bad.id);
    expect(again).toMatchObject({ copy: "REPRINT", status: "PRINTED" });
    expect(origs()).toHaveLength(1);
  });

  /** Ayni server jurnali + ixtiyoriy tarmoq uzilishi (qaysi qurilma/so'rov). */
  const via = (j0: ReturnType<typeof journal>, drop: (c: Call) => boolean) => (c: Call) => {
    if (drop(c)) throw new TypeError("Failed to fetch");
    return j0.routes.find(([re]) => re.test(c.url))![1](c);
  };

  it("5F.2 R0: Manager o'zlashtirib ASL chop etdi, PRINTED hisoboti YO'QOLDI → POS Qayta urinish/qo'lda → NUSXA (PRINT_JOB_BUSY)", async () => {
    const j0 = journal();
    let managerReportLost = false;
    const calls = server(baseRoutes([[/\/print-jobs/, via(j0, (c) =>
      managerReportLost && device === "manager" && c.method === "PATCH" && c.body?.status === "PRINTED")]]));
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(j0.rows.get(bad.id)).toMatchObject({ status: "FAILED", claim_token: bad.claim_token });

    onDevice("manager", MANAGER);
    printerAnswer = () => ({ ok: true });
    managerReportLost = true;
    const m = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(m).toMatchObject({ id: bad.id, copy: "ORIGINAL", status: "PRINTED", reported: false });
    expect(m.claim_token).toBeTruthy();
    expect(m.claim_token).not.toBe(bad.claim_token);
    // Server hali "chop etilmoqda" deb biladi: Manager bandi jonli.
    expect(j0.rows.get(bad.id)).toMatchObject({ status: "PENDING", claim_token: m.claim_token });
    expect(origs()).toHaveLength(1);

    onDevice("pos", CASHIER);
    calls.length = 0;
    const p1 = await retryJob(bad.id);
    expect(p1).toMatchObject({ copy: "REPRINT", copy_no: 1, status: "PRINTED" });
    expect(origs()).toHaveLength(1); // ikkinchi bannersiz ASL YO'Q
    expect(printed.at(-1)!.html).toContain("NUSXA #1");
    const claim = printJobCalls(calls).find((c) => c.method === "PATCH" && c.body?.status === "PENDING");
    expect(claim?.url).toMatch(new RegExp(`/print-jobs/${bad.id}$`));
    expect(claim?.body.claim_token).toBeTruthy();
    expect(claim?.body.claim_token).not.toBe(m.claim_token);
    expect(listJobs().find((x) => x.id === bad.id)).toMatchObject({ code: "PRINT_ORIGINAL_EXISTS", reported: true, status: "FAILED" });
    // Endi bu ASL yozuv hech qachon ASL emas: qo'lda ham, qayta urinish ham — NUSXA, band so'rovisiz.
    calls.length = 0;
    expect(await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" })).toMatchObject({ copy: "REPRINT", copy_no: 2 });
    expect(await retryJob(bad.id)).toMatchObject({ copy: "REPRINT", copy_no: 3 });
    expect(printJobCalls(calls).some((c) => c.method === "PATCH" && c.body?.status === "PENDING")).toBe(false);
    expect(origs()).toHaveLength(1);

    // Manager hisoboti keyinroq yetib boradi (o'z tokeni bilan) — server bitta ASL, PRINTED.
    onDevice("manager", MANAGER);
    managerReportLost = false;
    await flushPrintReports();
    expect(j0.rows.get(bad.id)?.status).toBe("PRINTED");
    expect([...j0.rows.values()].filter((r) => r.copy === "ORIGINAL")).toHaveLength(1);
  });

  it("5F.2 R0: POS Qayta urinish Manager hali chop ETAYOTGANDA (band jonli) → NUSXA; Manager ASL'i yakunlanadi", async () => {
    const j0 = journal();
    server(baseRoutes([...j0.routes]));
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });

    onDevice("manager", MANAGER);
    let release: () => void = () => undefined;
    const slow = new Promise<void>((r) => { release = r; });
    printerAnswer = () => slow.then(() => ({ ok: true })); // HTML/spooler chop etish hali tugamagan
    const m = printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    await waitFor(() => expect(printed).toHaveLength(2));
    expect(j0.rows.get(bad.id)).toMatchObject({ status: "PENDING" });

    onDevice("pos", CASHIER);
    printerAnswer = () => ({ ok: true });
    const p = await retryJob(bad.id);
    expect(p).toMatchObject({ copy: "REPRINT", status: "PRINTED" });
    expect(printed.at(-1)!.copy).toEqual({ kind: "REPRINT", no: 1 });

    onDevice("manager", MANAGER);
    release();
    expect(await m).toMatchObject({ id: bad.id, copy: "ORIGINAL", status: "PRINTED", reported: true });
    expect(j0.rows.get(bad.id)?.status).toBe("PRINTED");
    expect(origs()).toHaveLength(1);
    expect(paper.map((x) => x.copy?.kind)).toEqual(["REPRINT", "ORIGINAL"]);
  });

  it("5F.2 R0: o'z xatosi (FAILED) hisoboti yo'qolgan → qayta urinishda avval ESKI token bilan FAILED, keyin yangi band → ASL", async () => {
    const j0 = journal();
    let down = false;
    const calls = server(baseRoutes([[/\/print-jobs/, via(j0, () => down)]]));
    // Band o'tdi, printer xato berdi va shu payt tarmoq uzildi — FAILED hisoboti serverga yetmadi.
    printerAnswer = () => { down = true; return { ok: false, code: "PAPER_OUT", error: "x" }; };
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(bad).toMatchObject({ status: "FAILED", reported: false });
    expect(j0.rows.get(bad.id)).toMatchObject({ status: "PENDING", claim_token: bad.claim_token }); // bandimiz ochiq

    down = false;
    printerAnswer = () => ({ ok: true });
    calls.length = 0;
    const ok = await retryJob(bad.id);
    expect(ok).toMatchObject({ id: bad.id, copy: "ORIGINAL", status: "PRINTED", reported: true });
    const seq = printJobCalls(calls).map((c) => [c.method, c.body?.status, c.body?.claim_token]);
    expect(seq[0]).toEqual(["PATCH", "FAILED", bad.claim_token]);
    expect(seq[1][0]).toBe("PATCH");
    expect(seq[1][1]).toBe("PENDING");
    expect(seq[1][2]).not.toBe(bad.claim_token);
    expect(seq[2]).toEqual(["PATCH", "PRINTED", seq[1][2]]);
    expect(origs()).toHaveLength(1);
  });

  it("S2: POS xatosi serverga yetmagan, Manager ASL chiqargan → POS flush 409 → POS qo'lda bosish NUSXA", async () => {
    const j0 = journal();
    let posDown = true;
    server(baseRoutes([[/\/print-jobs/, (c: Call) => {
      if (posDown && device === "pos") throw new TypeError("Failed to fetch");
      const r = j0.routes.find(([re]) => re.test(c.url))!;
      return r[1](c);
    }]]));
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "x" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(bad).toMatchObject({ status: "FAILED", reported: false });
    onDevice("manager", MANAGER);
    printerAnswer = () => ({ ok: true });
    expect(await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" })).toMatchObject({ copy: "ORIGINAL", status: "PRINTED" });
    onDevice("pos", CASHIER);
    posDown = false;
    await flushPrintReports();
    expect(listJobs().find((x) => x.id === bad.id)).toMatchObject({ code: "PRINT_ORIGINAL_EXISTS", reported: true });
    const p = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" });
    expect(p.copy).toBe("REPRINT");
    expect(origs()).toHaveLength(1);
  });

  it("Manager: server jurnali 503 → ASL EMAS, NUSXA (yopiq xato); ASL band qilish so'rovi ham yuborilmaydi", async () => {
    const calls = server(baseRoutes([[/\/print-jobs\?/, { __status: 503, detail: "x" }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j).toMatchObject({ copy: "REPRINT", status: "PRINTED" });
    expect(printed.map((p) => p.copy?.kind)).toEqual(["REPRINT"]);
    expect(printed[0].html).toContain("NUSXA");
    expect(printJobCalls(calls).some((c) => c.body?.copy === "ORIGINAL")).toBe(false);
  });

  it("Manager: server jurnali javob bermaydi (4 s muddat) → NUSXA", async () => {
    const calls = server(baseRoutes([[/\/print-jobs\?/, () => new Promise(() => undefined)]]));
    const t0 = Date.now();
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(Date.now() - t0).toBeGreaterThanOrEqual(3900);
    expect(j).toMatchObject({ copy: "REPRINT", status: "PRINTED" });
    expect(origs()).toHaveLength(0);
    expect(printJobCalls(calls).some((c) => c.body?.copy === "ORIGINAL")).toBe(false);
  }, 15_000);

  it("server jurnalida FAQAT nusxa (asl hisobot kechikkan) → NUSXA, ASL emas", async () => {
    server(baseRoutes([[/\/print-jobs\?/, [{ id: "rep-1", copy: "REPRINT", copy_no: 1, status: "PRINTED", attempts: 1 }]]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j.copy).toBe("REPRINT");
    expect(origs()).toHaveLength(0);
  });

  it("server jurnalida band qilingan (PENDING) ASL → NUSXA", async () => {
    server(baseRoutes([[/\/print-jobs\?/, [{ id: "o-1", copy: "ORIGINAL", copy_no: 0, status: "PENDING", attempts: 0 }]]]));
    expect((await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" })).copy).toBe("REPRINT");
    expect(origs()).toHaveLength(0);
  });

  it("jurnal bo'sh, lekin band qilishda 409 (poyga — boshqa oyna birinchi) → NUSXA", async () => {
    const calls = server(baseRoutes([[/\/print-jobs$/, (c: Call) =>
      (c.body.copy === "ORIGINAL" ? { __status: 409, detail: ORIGINAL_EXISTS } : jobOut(c.body))]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(j).toMatchObject({ copy: "REPRINT", copy_no: 1, status: "PRINTED" });
    expect(origs()).toHaveLength(0);
    expect(listJobs().map((x) => x.copy)).toEqual(["REPRINT"]);
    expect(printJobCalls(calls).filter((c) => c.body?.copy === "ORIGINAL")).toHaveLength(1);
  });

  it("band qilish 503: boshqa joy (client_uuid'siz, qo'lda) → NUSXA; o'z sotuvi (client_uuid) → ASL (keyin hisobot)", async () => {
    server(baseRoutes([[/\/print-jobs$/, (c: Call) =>
      (c.body.copy === "ORIGINAL" && c.body.status === "PENDING" ? { __status: 503, detail: "x" } : jobOut(c.body))]]));
    const other = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(other.copy).toBe("REPRINT");
    expect(origs()).toHaveLength(0);

    _resetPrintRuntime();
    localStorage.clear();
    serverJobs = new Map();
    printed = [];
    const own = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" });
    expect(own).toMatchObject({ copy: "ORIGINAL", status: "PRINTED", reported: true }); // hisobot POST o'tdi
    expect(origs()).toHaveLength(1);
  });

  it("mahalliy ASL `PRINT_ORIGINAL_EXISTS` kodi bilan — hech qachon qayta ASL bo'lmaydi (band qilish so'ralmaydi ham)", async () => {
    const calls = server(baseRoutes());
    const stale: LocalPrintJob = {
      id: "x-1", key: docKey("SALE", SALE_ID), doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", copy: "ORIGINAL",
      copy_no: null, status: "FAILED", attempts: 1, error: "PRINT_ORIGINAL_EXISTS", code: "PRINT_ORIGINAL_EXISTS",
      transport: "virtual", printer: null, created_at: "2026-09-19T09:00:00.000Z", updated_at: "2026-09-19T09:00:00.000Z",
      printed_at: null, reported: true, provisional: false,
    };
    cacheSet(PRINT_JOBS_KEY, [stale]);
    expect((await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "manual" })).copy).toBe("REPRINT");
    expect((await retryJob("x-1")).copy).toBe("REPRINT");
    expect(origs()).toHaveLength(0);
    expect(printJobCalls(calls).some((c) => c.body?.copy === "ORIGINAL" || /x-1$/.test(c.url))).toBe(false);
  });
});

// ── 5F.1: eski server (marshrut yo'q) — zaxira DTO (#6, #17) ─────────────────
describe("eski (5F dan oldingi) server: faqat marshrut yo'q bo'lsa zaxira DTO (5F.1 #6/#17)", () => {
  const fallback = (): ReceiptDTO => ({ ...SALE, doc: { ...SALE.doc, number: "#7777" }, provisional: true });
  const legacyRoutes = (over: [RegExp, any][] = []): [RegExp, any][] => [
    ...over,
    [/\/sales\/[^/]+\/receipt/, ROUTE_MISSING],
    [/\/receipt\/profile/, ROUTE_MISSING],
    [/\/print-jobs/, ROUTE_MISSING],
  ];

  it("GET /sales/{id}/receipt → 404 'Not Found' → zaxira DTO'dan chop etiladi (vaqtinchalik EMAS), hisobot aylanmaydi", async () => {
    const calls = server(legacyRoutes());
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", fallbackDto: fallback(), mode: "manual" });
    expect(j).toMatchObject({ status: "PRINTED", copy: "ORIGINAL", provisional: false, transport: "virtual", reported: true });
    expect(printed[0].html).toContain("#7777");
    expect(printed[0].html).not.toContain("OFLAYN");
    expect(printed[0].copy).toEqual({ kind: "ORIGINAL" });
    expect(calls.filter((c) => /\/receipt$/.test(c.url))).toHaveLength(1); // 4xx — qayta urinilmaydi
    const n = printJobCalls(calls).length;
    await flushPrintReports();
    expect(printJobCalls(calls)).toHaveLength(n); // 404 marshrut — yakuniy, sikl yo'q
  });

  it("rus tilida ham (xato matni tarjima qilinmaydi) marshrut yo'qligi aniqlanadi", async () => {
    useLang.getState().set("ru");
    server(legacyRoutes());
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", fallbackDto: fallback(), mode: "auto" });
    expect(j.status).toBe("PRINTED");
  });

  it("ilova 404 ('Chek topilmadi'), 403 va tarmoq xatosi — zaxira ISHLATILMAYDI (NO_DATA)", async () => {
    for (const answer of [
      { __status: 404, detail: "Chek topilmadi" },
      { __status: 403, detail: "Ruxsat yo'q" },
      () => { throw new TypeError("Failed to fetch"); },
    ]) {
      _resetPrintRuntime();
      localStorage.clear();
      printed = [];
      server(baseRoutes([[/\/sales\/[^/]+\/receipt/, answer]]));
      const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", fallbackDto: fallback(), mode: "manual" });
      expect(j).toMatchObject({ status: "FAILED", code: "NO_DATA" });
      expect(printed).toHaveLength(0);
    }
  }, 15_000);

  it("zaxira qayta urinishda ham saqlanadi (ilova qayta ishga tushsa ham)", async () => {
    server(legacyRoutes());
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "x" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", fallbackDto: fallback(), mode: "manual" });
    expect(j.status).toBe("FAILED");
    _resetPrintRuntime();
    printerAnswer = () => ({ ok: true });
    expect(await retryJob(j.id)).toMatchObject({ status: "PRINTED", provisional: false });
    expect(printed.at(-1)!.html).toContain("#7777");
  });

  it("/receipt/profile 404 'Not Found' → profil null; 5 daqiqa ichida qayta so'ralmaydi", async () => {
    const calls = server(legacyRoutes());
    expect(await getReceiptProfile()).toBeNull();
    expect(await getReceiptProfile()).toBeNull();
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", fallbackDto: fallback(), mode: "manual" });
    expect(calls.filter((c) => /\/receipt\/profile/.test(c.url))).toHaveLength(1);
    await getReceiptProfile({ force: true });
    expect(calls.filter((c) => /\/receipt\/profile/.test(c.url))).toHaveLength(2);
  });
});

// ── 5F.1: oflayn sotuv → server id xaritasi (#16, #20, #21) ─────────────────
describe("sinxronlangan oflayn sotuv: client_uuid → server id xaritasi (5F.1 #16/#20/#21)", () => {
  const CU = "abcdef12-3456-4789-8abc-def012345678";
  const provisional = () => provisionalSaleReceipt({
    client_uuid: CU,
    lines: [{ name: "Non", qty: "2", unit_price: "4000", weighted: false }],
    payments: [{ method: "cash", amount: "8000" }], total: "8000",
    store: SALE.store, cashier: "Dilnoza", issued_at_local: "19.09.2026 14:40", template: { ...BUILTIN_TEMPLATE },
  });

  it("sinxronlash chop etishdan OLDIN → chek SERVER DTO'sidan (vaqtinchalik emas), ASL hisobot doc_id bilan", async () => {
    const calls = server(baseRoutes());
    bindDocId(CU, SALE_ID); // yozuv hali yo'q — faqat xarita
    expect(listJobs()).toEqual([]);
    const j = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "manual" });
    expect(j).toMatchObject({ doc_id: SALE_ID, client_uuid: CU, copy: "ORIGINAL", status: "PRINTED", provisional: false, reported: true });
    expect(calls.some((c) => c.method === "GET" && c.url.endsWith(`/sales/${SALE_ID}/receipt`))).toBe(true);
    expect(printed[0].html).toContain("#1288");
    expect(printed[0].html).not.toContain("OFLAYN");
    const post = printJobCalls(calls).find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ doc_id: SALE_ID, copy: "ORIGINAL" });
    // POS ekrani kaliti (client_uuid) bilan ham ko'rinadi; keyingi bosish — NUSXA.
    expect(listJobs({ key: docKey("SALE", CU) })).toHaveLength(1);
    expect((await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "manual" })).copy).toBe("REPRINT");
  });

  it("server DTO olinmasa (tarmoq) — vaqtinchalik DTO zaxira bo'lib qoladi", async () => {
    server(baseRoutes([[/\/sales\/[^/]+\/receipt/, () => { throw new TypeError("Failed to fetch"); }]]));
    bindDocId(CU.toUpperCase(), SALE_ID); // katta-kichik harf farqi muhim emas
    const j = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "auto" });
    expect(j).toMatchObject({ doc_id: SALE_ID, status: "PRINTED", provisional: true });
    expect(printed[0].html).toContain("OFLAYN");
  }, 10_000);

  it("xarita 500 ta bilan chegaralangan (eng eskisi ketadi), server bo'yicha ajratilgan kalitda", () => {
    const pairs = new Map<string, string>();
    for (let i = 0; i < 520; i++) pairs.set(`cu-${i}`, `id-${i}`);
    bindDocIds(pairs);
    bindDocId("cu-new", "id-new");
    const raw = JSON.parse(localStorage.getItem(nsKey("savdoos_print_bound")) as string);
    const keys = Object.keys(raw);
    expect(keys).toHaveLength(500);
    expect(raw["cu-new"]).toBe("id-new");
    expect(raw["cu-519"]).toBe("id-519");
    expect(raw["cu-0"]).toBeUndefined();
    expect(raw["cu-20"]).toBeUndefined();
    expect(raw["cu-21"]).toBe("id-21");
  });

  it("500 ta oflayn sotuv qayta ulanganda: jurnal BITTA marta yoziladi (N×J emas), hammasi bog'lanadi", async () => {
    const jobs: LocalPrintJob[] = Array.from({ length: 500 }, (_, i) => ({
      id: `j-${i}`, key: `SALE:cu-${i}`, doc_type: "SALE", doc_id: null, client_uuid: `cu-${i}`, copy: "ORIGINAL",
      copy_no: null, status: "PRINTED", attempts: 1, error: null, code: null, transport: "virtual", printer: null,
      created_at: new Date(Date.UTC(2026, 8, 19, 0, 0, i)).toISOString(), updated_at: "2026-09-19T00:00:00.000Z",
      printed_at: null, reported: false, provisional: true, owner_id: "emp-1",
    }));
    cacheSet(PRINT_JOBS_KEY, jobs);
    for (let i = 0; i < 500; i++) {
      outboxAdd({ client_uuid: `cu-${i}`, payload: { client_uuid: `cu-${i}` }, created_at: "2026-09-19T00:00:00.000Z", owner_id: "emp-1" });
    }
    server(baseRoutes([
      [/\/sync\/push/, (c: Call) => ({ results: c.body.sales.map((x: any) => ({ client_uuid: x.client_uuid, ok: true, id: `id-${x.client_uuid.slice(3)}` })) })],
      [/\/print-jobs$/, (c: Call) => jobOut(c.body)],
    ]));
    const jobsKey = nsKey(PRINT_JOBS_KEY);
    const writesTo: string[] = [];
    const orig = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, k: string, v: string) {
      writesTo.push(k);
      return orig.call(this, k, v);
    });
    const t0 = performance.now();
    await flushOutbox();
    const ms = performance.now() - t0;
    spy.mockRestore();
    expect(outboxAll()).toEqual([]);
    // Bog'lash: jurnal va xarita — har biri BIR marta (avval har sotuvga bir marta = 500).
    expect(writesTo.filter((k) => k === jobsKey)).toHaveLength(1);
    expect(writesTo.filter((k) => k === nsKey("savdoos_print_bound"))).toHaveLength(1);
    const bound = listJobs();
    expect(bound.filter((j) => j.doc_id === `id-${j.client_uuid!.slice(3)}`)).toHaveLength(500);
    expect(ms).toBeLessThan(15_000); // saxiy chegara (jsdom sekin); asosiy isbot — yozuvlar soni
  }, 30_000);

  it("zaxira: sinxronlash bilan ustma-ust tushib bog'lanmay qolgan yozuv flush'da bog'lanadi va yuboriladi", async () => {
    const calls = server(baseRoutes());
    const j = await printDoc({ doc_type: "SALE", client_uuid: CU, dto: provisional(), mode: "auto" });
    expect(j.doc_id).toBeNull();
    // Xarita yozildi, lekin yozuv (masalan boshqa oynada) bog'lanmagan holatda qoldi.
    localStorage.setItem(nsKey("savdoos_print_bound"), JSON.stringify({ [CU]: SALE_ID }));
    await flushPrintReports();
    expect(listJobs()[0]).toMatchObject({ doc_id: SALE_ID, reported: true });
    expect(printJobCalls(calls).find((c) => c.method === "POST")?.body).toMatchObject({ id: j.id, doc_id: SALE_ID });
  });
});

// ── 5F.1: hisobot faqat yozuv egasining tokeni bilan (#18, #39) ─────────────
describe("hisobot egasi: boshqa kassirning 403/404 i yozuvni tashlab yubormaydi (5F.1 #18/#39)", () => {
  it("A chop etdi (hisobot tarmoqsiz) → B kirdi: flush A yozuvini YUBORMAYDI; A qaytdi → yuboriladi", async () => {
    let down = true;
    const calls = server(baseRoutes([
      [/\/returns\/r-1\/receipt/, { ...SALE, kind: "RETURN", doc: { ...SALE.doc, id: "r-1", number: "QAY-7" }, payments: [], refund: { method: "cash", amount: SALE.totals.total } }],
      [/\/print-jobs$/, (c: Call) => {
        if (down) throw new TypeError("Failed to fetch");
        // B uchun A ning qaytarishi ko'rinmaydi (readable_return) — 404.
        return useAuth.getState().employee?.id === "emp-1" ? jobOut(c.body) : { __status: 404, detail: "Qaytarish topilmadi" };
      }],
    ]));
    const a = await printDoc({ doc_type: "RETURN", doc_id: "r-1", mode: "auto" });
    expect(a).toMatchObject({ status: "PRINTED", reported: false, owner_id: "emp-1" });
    down = false;
    useAuth.setState({ token: "tok-b", employee: { id: "emp-2", full_name: "Botir", role_code: "kassir", role_name: "Kassir", status: "active", permissions: ["kassa.sell"] } });
    calls.length = 0;
    await flushPrintReports();
    expect(printJobCalls(calls)).toEqual([]);
    expect(listJobs()[0]).toMatchObject({ reported: false });
    // B ning o'z qayta chop etishi ham A yozuvini "yuborildi" qilmaydi.
    useAuth.setState({ token: "tok", employee: { id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir", status: "active", permissions: ["kassa.sell"] } });
    await flushPrintReports();
    expect(listJobs()[0]).toMatchObject({ reported: true });
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(1);
    expect(printJobCalls(calls)[0].body).toMatchObject({ id: a.id, doc_type: "RETURN", copy: "ORIGINAL", status: "PRINTED" });
  });

  it("egasiz (eski) yozuv — istalgan kassir yuboradi", async () => {
    const calls = server(baseRoutes());
    const legacy: LocalPrintJob = {
      id: "old-1", key: docKey("SALE", SALE_ID), doc_type: "SALE", doc_id: SALE_ID, client_uuid: null, copy: "ORIGINAL",
      copy_no: null, status: "PRINTED", attempts: 1, error: null, code: null, transport: "virtual", printer: null,
      created_at: "2026-09-19T09:00:00.000Z", updated_at: "2026-09-19T09:00:00.000Z", printed_at: null, reported: false, provisional: false,
    };
    cacheSet(PRINT_JOBS_KEY, [legacy]);
    useAuth.setState({ employee: { ...useAuth.getState().employee!, id: "emp-7" } });
    await flushPrintReports();
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(1);
    expect(listJobs()[0].reported).toBe(true);
  });

  it("yozuv chop etgan xodim egasi bo'ladi (newJob va qayta urinish)", async () => {
    server(baseRoutes());
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "x" });
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, client_uuid: "c-1", mode: "auto" });
    expect(j.owner_id).toBe("emp-1");
    useAuth.setState({ employee: { ...useAuth.getState().employee!, id: "emp-3" } });
    printerAnswer = () => ({ ok: true });
    expect((await retryJob(j.id)).owner_id).toBe("emp-3");
  });
});
