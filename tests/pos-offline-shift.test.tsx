import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { CACHE, cacheGet, cacheSet, nsKey, outboxAll } from "@/lib/offline";
import {
  OFFLINE_POLICY_TTL_MS, clearOfflinePolicy, failedSales, offlineSaleAllowed,
  offlineSaleReason, refreshOfflinePolicy,
} from "@/lib/sync";
import { mockApi, renderApp, type Call } from "./util";

// P9 — OFFLINE SAVDONI YAKUNLASH DARVOZASI.
//
// MUAMMO (do'kondagi haqiqiy yo'qotish yo'li). `security.force_shift` yoqilgan do'konda
// server ochiq smenasiz savdoni RAD etadi. Kassa esa `security` kalitini KO'RMAYDI —
// server uni kassirga bermaydi (`settings.py::_UI_KEYS`). Shu bois tarmoq uzilganda
// kassa chekni MAHALLIY yakunlab, PULNI OLIB, mijozni jo'natardi; tarmoq qaytganda
// `/sync/push` uni 400 bilan rad etib dead-letter'ga tashlardi. Natija: pul olingan,
// serverda esa savdo ham, naqd harakati ham, stok chiqimi ham YO'Q.
//
// INVARIANT: offline YAKUNLASH faqat server AYNAN SHU kassir uchun bergan, ESKIRMAGAN
// «ALLOWED» tasdig'i bilan bo'ladi. Tasdiq yo'q / eskirgan / begona / shakli notanish —
// YAKUNLANMAYDI. Qiymatning yo'qligi HECH QACHON ruxsat bermaydi.
//
// TEGILMAYDIGAN XULQ: onlayn savdo, `force_shift` o'chiq do'kondagi offline savdo va
// «To'lovni yakunlash» tugmasining ochiqligi (Phase 7 maketi).

const NON: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 2, article: "A-1" };

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona" },
];
const SETTINGS = {
  features: { returns: true },
  payments: { karta: true, qr: true, qarz: true },
  store_info: { name: "Test Do'kon", branch: "Test filiali" },
};

const SETTINGS_KARTA_OFFLINE = { ...SETTINGS, payments: { karta: true, qr: true, qarz: true, offline_card: true } };

const ME = "e1";
const TARMOQ_YOQ = () => { throw new Error("Failed to fetch"); };

function routes(over: [RegExp, any][] = []): [RegExp, any][] {
  return [
    ...over,
    [/\/products\?include_archived=1/, PRODUCTS],
    [/\/categories/, []],
    [/\/settings$/, SETTINGS],
    [/\/customers$/, []],
    [/\/receipt\/profile/, { etag: "e", branch_id: "b1", effective: {}, store: {}, logo: null, store_qr: null }],
  ];
}

/** Server tasdig'ini keshga AYNAN o'sha shaklda yozadi (server javobi emas, saqlangan holat). */
function setPolicy(p: { mode?: string; reason?: string | null; at?: number; owner_id?: string } | null) {
  cacheSet(CACHE.offlinePolicy, p === null ? null
    : { mode: "ALLOWED", reason: null, at: Date.now(), owner_id: ME, ...p });
}

const setCart = (items: CartLine[]) => useCart.setState({ carts: [items], active: 0, items });

/** Naqd to'lovni oxirigacha olib boradi (Phase 7 oqimi: pay-go -> Naqd -> Yakunlash). */
async function payCash(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId("pay-go"));
  await user.click(await screen.findByRole("button", { name: "Naqd", exact: true }));
  await user.click(screen.getByRole("button", { name: /Yakunlash|Завершить/i }));
}

beforeEach(() => {
  localStorage.clear();
  cacheSet(CACHE.settings, SETTINGS);
  cacheSet(CACHE.products, PRODUCTS);
  cacheSet(CACHE.cats, []);
  useAuth.setState({
    token: "t",
    employee: { id: ME, full_name: "Test Kassir", permissions: ["kassa.sell"] } as never,
  });
  setCart([]);
});

afterEach(() => {
  vi.restoreAllMocks();
  useCart.setState({ carts: [[]], active: 0, items: [] });
});

// ═══ 1. DARVOZA QOIDASI (fail-closed) ═══════════════════════════════════════
describe("offlineSaleAllowed — tasdiq yo'q bo'lsa RUXSAT YO'Q", () => {
  it("1. hech qachon tasdiq olinmagan (birinchi ishga tushish) → false", () => {
    expect(offlineSaleAllowed()).toBe(false);
  });

  it("2. server ALLOWED degan va tasdiq yangi → true", () => {
    setPolicy({ mode: "ALLOWED" });
    expect(offlineSaleAllowed()).toBe(true);
  });

  it("3. server BLOCKED degan → false, sabab o'qiladi", () => {
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    expect(offlineSaleAllowed()).toBe(false);
    expect(offlineSaleReason()).toBe("OPEN_SHIFT_REQUIRED");
  });

  it("4. tasdiq ESKIRGAN (TTL dan oshgan) → false", () => {
    const now = Date.now();
    setPolicy({ mode: "ALLOWED", at: now - OFFLINE_POLICY_TTL_MS - 1 });
    expect(offlineSaleAllowed(now)).toBe(false);
    // Chegaraning AYNAN o'zi hali kuchda — TTL yopiq oraliq.
    setPolicy({ mode: "ALLOWED", at: now - OFFLINE_POLICY_TTL_MS });
    expect(offlineSaleAllowed(now)).toBe(true);
  });

  it("5. tasdiq BOSHQA kassirniki (qurilmada smena almashdi) → false", () => {
    setPolicy({ mode: "ALLOWED", owner_id: "boshqa-kassir" });
    expect(offlineSaleAllowed()).toBe(false);
  });

  it("6. kassir tizimdan chiqqan (employee yo'q) → false", () => {
    setPolicy({ mode: "ALLOWED" });
    useAuth.setState({ token: null, employee: null } as never);
    expect(offlineSaleAllowed()).toBe(false);
  });

  it("7. saqlangan qiymat BUZUQ/notanish shaklda → false (taxmin qilinmaydi)", () => {
    for (const buzuq of [{ mode: "MAYBE" }, { mode: "ALLOWED", at: "kecha" }, {}, 42, "ALLOWED"]) {
      cacheSet(CACHE.offlinePolicy, buzuq);
      expect(offlineSaleAllowed()).toBe(false);
    }
    localStorage.setItem(nsKey(CACHE.offlinePolicy), "{buzuq json");
    expect(offlineSaleAllowed()).toBe(false);
  });

  it("8. chiqishda (logout) tasdiq BEKOR qilinadi", () => {
    setPolicy({ mode: "ALLOWED" });
    expect(offlineSaleAllowed()).toBe(true);
    clearOfflinePolicy();
    expect(offlineSaleAllowed()).toBe(false);
  });
});

// ═══ 2. TASDIQNI YANGILASH ══════════════════════════════════════════════════
describe("refreshOfflinePolicy — serverdan qaror olish", () => {
  it("9. server javobi keshga yoziladi va QURILMA SOATI yuboriladi", async () => {
    const calls = mockApi([[/offline-sale-policy/, { mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" }]]);
    const now = Date.UTC(2026, 8, 29, 10, 0, 0);
    await refreshOfflinePolicy(now);
    const saqlangan = cacheGet<any>(CACHE.offlinePolicy, null);
    expect(saqlangan).toMatchObject({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED", at: now, owner_id: ME });
    const so = calls.find((c: Call) => /offline-sale-policy/.test(c.url))!;
    expect(so.url).toContain("client_time=" + encodeURIComponent(new Date(now).toISOString()));
  });

  it("10. tarmoq yo'q / eski server (404) → mavjud tasdiq TEGILMAYDI, o'zi eskiradi", async () => {
    const now = Date.now();
    setPolicy({ mode: "ALLOWED", at: now });
    mockApi([[/offline-sale-policy/, TARMOQ_YOQ]]);
    await refreshOfflinePolicy(now);
    expect(cacheGet<any>(CACHE.offlinePolicy, null)).toMatchObject({ mode: "ALLOWED", at: now });
    // ...lekin ALOQA YO'Q ruxsatni CHO'ZMAYDI: TTL o'tgach darvoza yopiladi.
    expect(offlineSaleAllowed(now + OFFLINE_POLICY_TTL_MS + 1)).toBe(false);
  });

  it("11. notanish javob shakli → kesh TEGILMAYDI (soxta ruxsat yozilmaydi)", async () => {
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    mockApi([[/offline-sale-policy/, { holat: "yaxshi" }]]);
    await refreshOfflinePolicy();
    expect(cacheGet<any>(CACHE.offlinePolicy, null)).toMatchObject({ mode: "BLOCKED" });
  });

  it("12. `kassa.sell` yo'q xodim serverni URMAYDI (403 yog'dirmaslik)", async () => {
    useAuth.setState({
      token: "t", employee: { id: ME, full_name: "Omborchi", permissions: ["omborxona.view"] } as never,
    });
    const calls = mockApi([[/offline-sale-policy/, { mode: "ALLOWED", reason: null }]]);
    await refreshOfflinePolicy();
    expect(calls.filter((c: Call) => /offline-sale-policy/.test(c.url))).toHaveLength(0);
  });
});

// ═══ 3. KASSA OQIMI — PUL OLINISHIDAN OLDIN TO'SILADI ══════════════════════
describe("kassa: tarmoq yo'q + smena talab qilinadi", () => {
  it("13. BLOCKED: savdo NAVBATGA TUSHMAYDI, savat SAQLANADI, sabab ko'rinadi", async () => {
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(await screen.findByText(/ochiq смена|ochiq smena/i)).toBeInTheDocument();
    // ENG MUHIMI: navbatga HECH NARSA tushmagan — pul olingan savdo «bor» bo'lib qolmaydi.
    expect(outboxAll()).toHaveLength(0);
    expect(failedSales()).toHaveLength(0);
    // Savat TEGILMAYDI: kassir smenani ochib qayta uradi.
    await waitFor(() => expect(useCart.getState().items).toHaveLength(1));
  });

  it("14. ALLOWED: mavjud offline xulq SAQLANADI — savdo navbatga tushadi", async () => {
    setPolicy({ mode: "ALLOWED" });
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    await waitFor(() => expect(outboxAll()).toHaveLength(1));
    expect(useCart.getState().items).toHaveLength(0);          // savdo yakunlandi
  });

  it("15. ESKIRGAN tasdiq: navbatga TUSHMAYDI (uzoq offline qurilma)", async () => {
    setPolicy({ mode: "ALLOWED", at: Date.now() - OFFLINE_POLICY_TTL_MS - 60_000 });
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(outboxAll()).toHaveLength(0);
    await waitFor(() => expect(useCart.getState().items).toHaveLength(1));
  });

  it("16. TASDIQSIZ (ilova yangi o'rnatilgan / kesh tozalangan): navbatga TUSHMAYDI", async () => {
    setPolicy(null);
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(outboxAll()).toHaveLength(0);
    await waitFor(() => expect(useCart.getState().items).toHaveLength(1));
  });

  it("17. SOAT xato bo'lsa sabab AYNAN soat haqida bo'ladi", async () => {
    setPolicy({ mode: "BLOCKED", reason: "DEVICE_CLOCK_UNRELIABLE" });
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(await screen.findByText(/соат|soati/i)).toBeInTheDocument();
    expect(outboxAll()).toHaveLength(0);
  });

  it("18. ONLAYN savdo BLOCKED bo'lsa ham AVVALGIDEK ishlaydi (darvoza faqat offline)", async () => {
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    const calls = mockApi(routes([[/\/sales$/, { id: "s1", receipt_no: "#7", uid: "u1" }]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    await waitFor(() => expect(useCart.getState().items).toHaveLength(0));
    expect(calls.filter((c: Call) => c.method === "POST" && /\/sales$/.test(c.url))).toHaveLength(1);
    expect(outboxAll()).toHaveLength(0);
  });

  it("19. «To'lovni yakunlash» tugmasi OCHIQ qoladi (Phase 7 maketi buzilmaydi)", async () => {
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    mockApi(routes());
    setCart([NON]);
    renderApp(<POSKassa />);
    await waitFor(() => expect(screen.getByTestId("pay-go")).toBeEnabled());
  });
});

// ═══ 4. DEAD-LETTER: DALIL YO'Q QILINMASIN ═════════════════════════════════
describe("rad etilgan cheklar — bir bosishda yo'q qilinmaydi", () => {
  beforeEach(() => {
    localStorage.setItem(nsKey("savdoos_outbox_failed"), JSON.stringify([
      { client_uuid: "cu-1", created_at: "2026-09-29T10:00:00.000Z",
        payload: { expected_total: 50000 }, error: "Ochiq smena yo'q" },
    ]));
  });

  it("20. birinchi bosishda O'CHMAYDI — ogohlantirish va tasdiq so'raladi", async () => {
    mockApi(routes());
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await user.click(await screen.findByTestId("failed-badge"));
    expect(await screen.findByTestId("failed-row")).toBeInTheDocument();
    await user.click(screen.getByTestId("failed-clear"));
    // Ma'lumot JOYIDA: pul olingan savdoning yagona dalili yo'qolmadi.
    expect(failedSales()).toHaveLength(1);
    expect(await screen.findByTestId("failed-clear-warn")).toBeInTheDocument();
    expect(screen.getByTestId("failed-clear-confirm")).toBeInTheDocument();
  });

  it("21. faqat TASDIQLANGANDAN keyin o'chadi", async () => {
    mockApi(routes());
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await user.click(await screen.findByTestId("failed-badge"));
    await user.click(await screen.findByTestId("failed-clear"));
    await user.click(await screen.findByTestId("failed-clear-confirm"));
    await waitFor(() => expect(failedSales()).toHaveLength(0));
  });

  it("22. oyna yopilsa tasdiq holati TIKLANADI (tasodifiy ikkinchi bosish yo'q)", async () => {
    mockApi(routes());
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await user.click(await screen.findByTestId("failed-badge"));
    await user.click(await screen.findByTestId("failed-clear"));
    await user.click(screen.getByRole("button", { name: /Yopish|Закрыть/i }));
    await user.click(await screen.findByTestId("failed-badge"));
    expect(screen.getByTestId("failed-clear")).toBeInTheDocument();
    expect(screen.queryByTestId("failed-clear-confirm")).toBeNull();
    expect(failedSales()).toHaveLength(1);
  });
});

// ═══ 5. TANQIDIY SHARHDAN KELIB CHIQQAN QOTIRISHLAR ════════════════════════
describe("darvoza YANGI yo'qotish yo'li ochmasin", () => {
  it("23. PUL ALLAQACHON OLINGAN (karta, internetsiz rejim): BLOCKED bo'lsa ham NAVBATGA tushadi", async () => {
    // Tashqi terminalda karta allaqachon o'tkazilgan. Bunday chekni to'sish uni navbatga
    // ham, dead-letter'ga ham yozmasdan YO'Q QILARDI — pul ketib, izi qolmasdi.
    cacheSet(CACHE.settings, SETTINGS_KARTA_OFFLINE);
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    mockApi([[/\/settings$/, SETTINGS_KARTA_OFFLINE], ...routes([[/\/sales$/, TARMOQ_YOQ]])]);
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await user.click(await screen.findByTestId("pay-go"));
    await user.click(await screen.findByRole("button", { name: "Karta", exact: true }));
    await user.click(screen.getByRole("button", { name: /Yakunlash|Завершить/i }));
    await waitFor(() => expect(outboxAll()).toHaveLength(1));
  });

  it("24. NAQD (pul hali olinmagan) BLOCKED bo'lsa — navbatga TUSHMAYDI", async () => {
    // Nazorat: 23-sinov darvozani butunlay ochib yubormaganini isbotlaydi.
    cacheSet(CACHE.settings, SETTINGS_KARTA_OFFLINE);
    setPolicy({ mode: "BLOCKED", reason: "OPEN_SHIFT_REQUIRED" });
    mockApi([[/\/settings$/, SETTINGS_KARTA_OFFLINE], ...routes([[/\/sales$/, TARMOQ_YOQ]])]);
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(outboxAll()).toHaveLength(0);
  });

  it("25. SOAT ORQAGA surilsa tasdiq abadiy yashamaydi", () => {
    // `now - at` MANFIY bo'lib TTL solishtiruvi hamisha rost bo'lib qolardi.
    const now = Date.now();
    setPolicy({ mode: "ALLOWED", at: now + 5 * 60 * 60 * 1000 });   // muhr KELAJAKDA
    expect(offlineSaleAllowed(now)).toBe(false);
  });

  it("26. TASDIQ YO'Q holatida xabar smenaga EMAS, ULANISHGA yo'naltiradi", async () => {
    // «Smenani oching» deyish yolg'on bo'lardi: smena ochish darvozani ochmaydi —
    // server bilan aloqa kerak.
    setPolicy(null);
    mockApi(routes([[/\/sales$/, TARMOQ_YOQ]]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await payCash(user);
    expect(await screen.findByText(/serverga hali ulanmagan/i)).toBeInTheDocument();
    expect(outboxAll()).toHaveLength(0);
  });

  it("27. server bergan BARQAROR KOD dead-letter yozuviga YETIB BORADI", async () => {
    // Ilgari `code` klientda tashlab yuborilardi va dead-letter'da faqat tilga bog'liq
    // matn qolardi — yarashtirish uchun mashina o'qiydigan sabab bo'lmasdi.
    const { flushOutbox } = await import("@/lib/sync");
    const { outboxAdd } = await import("@/lib/offline");
    outboxAdd({ client_uuid: "cu-9", payload: { client_uuid: "cu-9" },
                created_at: new Date().toISOString(), owner_id: ME });
    mockApi([[/\/sync\/push/, { accepted: 0, failed: 1, results: [
      { client_uuid: "cu-9", ok: false, retry: false, error: "Ochiq smena yo'q",
        code: "OPEN_SHIFT_REQUIRED" }] }]]);
    await flushOutbox();
    await waitFor(() => expect(failedSales()).toHaveLength(1));
    expect(failedSales()[0].code).toBe("OPEN_SHIFT_REQUIRED");
    expect(outboxAll()).toHaveLength(0);
  });
});
