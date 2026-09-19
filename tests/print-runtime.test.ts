import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  _resetPrintRuntime, bindDocId, docKey, flushPrintReports, getReceiptProfile, listJobs, printDoc, printTestReceipt,
  retryJob, usePrintJobs, PRINT_JOBS_KEY, type LocalPrintJob,
} from "@/lib/printing";
import { PRINTER_CONFIG_KEY, readPrinterConfig, writePrinterConfig } from "@/lib/printerConfig";
import { cacheGet, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";
import { BUILTIN_TEMPLATE, provisionalSaleReceipt, sampleReceipt, type ReceiptDTO } from "@/receipt";
import type { VirtualPrintRequest } from "@/print/bridge";
import { LOGO_64x16, saleDto } from "./__golden__/receipt/fixtures";
import { mockApi, type Call } from "./util";

// Phase 5F F2: renderer chop etish runtime'i — navbat holat mashinasi, asl/nusxa, qayta urinish, oflayn
// vaqtinchalik chek, server jurnali hisobotlari (409 bilan) va sinov chekining YOZMASLIGI.

const SALE = saleDto();
const SALE_ID = SALE.doc.id as string;
const ORIGINAL_EXISTS = "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting";

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

const printJobCalls = (calls: Call[]) => calls.filter((c) => /\/print-jobs/.test(c.url));
const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

let printed: VirtualPrintRequest[] = [];
let printerAnswer: (req: VirtualPrintRequest) => any = () => ({ ok: true });

beforeEach(() => {
  _resetPrintRuntime();
  serverJobs = new Map();
  printed = [];
  printerAnswer = () => ({ ok: true });
  useLang.getState().set("uz");
  useAuth.setState({
    token: "tok",
    employee: { id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir", status: "active", permissions: ["kassa.sell"] },
  });
  window.__BINOS_VIRTUAL_PRINTER__ = (req) => {
    printed.push(req);
    return printerAnswer(req);
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
    expect(pj.map((c) => c.method)).toEqual(["POST"]);
    expect(pj[0].body).toMatchObject({
      id: a.id, doc_type: "SALE", doc_id: SALE_ID, copy: "ORIGINAL", status: "PRINTED", attempts: 1, transport: "virtual", error: null,
    });
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
    const patch = printJobCalls(calls).find((c) => c.method === "PATCH");
    expect(patch?.url).toMatch(/\/print-jobs\/srv-1$/);
    expect(patch?.body).toMatchObject({ status: "PRINTED", attempts: 3 });
  });
});

describe("xato, qayta urinish, uzilib qolgan yozuv", () => {
  it("printer xatosi → FAILED (kod bilan); qo'lda bosish AYNAN o'sha ASL yozuvni qayta chop etadi", async () => {
    const calls = server(baseRoutes());
    printerAnswer = () => ({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan" });
    const bad = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(bad).toMatchObject({ status: "FAILED", code: "PAPER_OUT", error: "qog'oz tugagan", attempts: 1, reported: true });
    expect(printJobCalls(calls)[0].body).toMatchObject({ status: "FAILED", error: "PAPER_OUT: qog'oz tugagan" });

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

  it("409 PRINT_ORIGINAL_EXISTS → qayd etiladi (reported, kod), AVTOMATIK qayta chop etilmaydi", async () => {
    const calls = server(baseRoutes([[/\/print-jobs$/, { __status: 409, detail: ORIGINAL_EXISTS }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", reported: true, code: "PRINT_ORIGINAL_EXISTS", error: "PRINT_ORIGINAL_EXISTS", copy: "ORIGINAL" });
    expect(printed).toHaveLength(1);
    await flushPrintReports();
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("tarmoq xatosi → reported:false; keyingi flush yuboradi (id o'sha — server takrorni PATCH deb qabul qiladi)", async () => {
    let down = true;
    const calls = server(baseRoutes([[/\/print-jobs$/, (c: Call) => {
      if (down) throw new TypeError("Failed to fetch");
      return jobOut(c.body);
    }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j).toMatchObject({ status: "PRINTED", reported: false });
    down = false;
    await flushPrintReports();
    const posts = printJobCalls(calls).filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[1].body.id).toBe(j.id);
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
    expect(pj.map((c) => [c.method, c.body.status])).toEqual([["POST", "PENDING"], ["PATCH", "PRINTED"]]);
  });

  it("5xx hisobot → keyinroq; 404 (hujjat ko'rinmaydi) → doimiy, qayta yuborilmaydi", async () => {
    const calls = server(baseRoutes([[/\/print-jobs$/, { __status: 404, detail: "Chek topilmadi" }]]));
    const j = await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "auto" });
    expect(j.reported).toBe(true);
    await flushPrintReports();
    expect(printJobCalls(calls).filter((c) => c.method === "POST")).toHaveLength(1);
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
    expect(req).toMatchObject({ printer: "XP-80C", widthMm: 58, copies: 1 });
    expect(req.html).toContain("size: 58mm auto");
  });

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
    const calls = server(baseRoutes([
      [/\/sales\/[^/]+\/receipt/, other],
      [/\/receipt\/logos\/logo-b2/, { id: "logo-b2", variants: { "58": LOGO_64x16, "80": LOGO_64x16 } }],
    ]));
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    await printDoc({ doc_type: "SALE", doc_id: SALE_ID, mode: "manual" });
    expect(calls.filter((c) => /\/receipt\/logos\//.test(c.url))).toHaveLength(1);
    expect(printed[0].html).toContain("data:image/png;base64,");
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
