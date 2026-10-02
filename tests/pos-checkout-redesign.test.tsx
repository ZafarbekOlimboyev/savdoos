import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { useShift } from "@/store/shift";
import { CACHE, cacheSet } from "@/lib/offline";
import { mockApi, renderApp, type Call } from "./util";

// Phase 7 — kassa redizaynining IKKI xulqi bo'yicha fokuslangan regressiya.
//
//  1) SMENA YOPIQ + to'lov. Backend qoidasi MUTLAQ EMAS (`services/sales.py`):
//     ochiq smenasiz savdo TAQIQLANMAYDI; u faqat do'kon `security.force_shift` ni
//     yoqqanda 400 bilan rad etiladi. Shu bois tugma SHARTSIZ o'chirilmaydi —
//     aks holda smenasiz savdo rejimi (ataylab qo'llab-quvvatlanadi) buzilardi.
//     ⚠️ POS `security` kalitini KO'RMAYDI (`settings.py::_UI_KEYS`, QA SB-011:
//        kassir hamma sozlamani o'qimasin) — shu bois klientda oldindan to'sib
//        bo'lmaydi. Rad etish serverda bo'ladi va kassirga oynada ko'rsatiladi.
//
//  2) PASTKI PANEL tanlangan qatorga ishlaydi. Tanlov — FAQAT ko'rinish holati;
//     savat API'si (`useCart`) tegilmagan.
//
// Testlar faqat tashlab yuboriladigan mock ma'lumot ishlatadi.

const NON: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 2, article: "A-1" };
const SUV: CartLine = { id: "p3", name: "Suv 1L", price: 3000, qty: 1, article: "A-3" };
const POMIDOR: CartLine = { id: "p2", name: "Pomidor", price: 12000, qty: 0.352, weighted: true, article: "A-2" };

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona" },
  { id: "p2", article_code: "A-2", name: "Pomidor", category_id: null, base_sell_price: 12000, stock: 50, unit_code: "kg", is_weighted: true },
  { id: "p3", article_code: "A-3", name: "Suv 1L", category_id: null, base_sell_price: 3000, stock: 80, unit_code: "dona" },
];

const SETTINGS = {
  features: { returns: true },
  payments: { karta: true, qr: true, qarz: true },
  store_info: { name: "Test Do'kon", branch: "Test filiali" },
};

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

function setCart(items: CartLine[]) {
  useCart.setState({ carts: [items], active: 0, items });
}

/** Smenani OCHIQ qiladi (saqlangan identity) yoki YOPIQ qoldiradi. */
function setShift(open: boolean) {
  useShift.setState({
    current: open ? { shift_id: "sh1", till_id: "t1", branch_id: "b1", till_code: "1" } : null,
  });
}

beforeEach(() => {
  localStorage.clear();
  cacheSet(CACHE.settings, SETTINGS);
  cacheSet(CACHE.products, PRODUCTS);
  cacheSet(CACHE.cats, []);
  useAuth.setState({ token: "t", employee: { id: "e1", full_name: "Test Kassir" } as any });
  setShift(false);
  setCart([]);
});

afterEach(() => {
  vi.restoreAllMocks();
  useCart.setState({ carts: [[]], active: 0, items: [] });
});

// ═══ 1. SMENA YOPIQ ══════════════════════════════════════════════════════════
describe("smena yopiq + to'lov (mavjud backend qoidasi)", () => {
  it("1. yopiq smena + to'la savat: sarlavha holatni AYTADI, to'lov tugmasi OCHIQ", async () => {
    mockApi(routes());
    setCart([NON]);
    renderApp(<POSKassa />);
    // Sarlavha holatni ANIQ ko'rsatadi (redizayndan oldin bu ma'lumot ekranda YO'Q edi)
    expect(await screen.findByText(/Smena yopiq/i)).toBeInTheDocument();
    // ⚠️ Tugma ATAYLAB ochiq: smenasiz savdo `force_shift` o'chiq do'konda QONUNIY.
    await waitFor(() => expect(screen.getByTestId("pay-go")).toBeEnabled());
  });

  it("2. yopiq smenada to'lov: server rad etsa sabab KASSIRGA ko'rinadi, savat SAQLANADI", async () => {
    const calls = mockApi(routes([
      [/\/sales$/, () => { const e: any = new Error("400"); e.status = 400; throw e; }],
    ]));
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await user.click(await screen.findByTestId("pay-go"));
    await user.click(await screen.findByRole("button", { name: "Naqd", exact: true }));
    await user.click(screen.getByRole("button", { name: /Yakunlash|Завершить/i }));
    // Savat YO'QOLMAYDI — pul o'tmagan, kassir smenani ochib qayta uradi
    await waitFor(() => expect(useCart.getState().items).toHaveLength(1));
    expect(calls.filter((c: Call) => c.method === "POST" && /\/sales$/.test(c.url)).length).toBeGreaterThan(0);
  });

  it("3. F4 yorlig'i yopiq smenada QO'SHIMCHA yo'l ochmaydi — ayni oynani ochadi", async () => {
    mockApi(routes());
    setCart([NON]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await screen.findByTestId("pay-go");
    await user.keyboard("{F4}");
    // F4 ham AYNI to'lov oynasini ochadi (tugma bilan bir xil yo'l), sotuvni O'ZI yubormaydi
    expect(await screen.findByText(/TO‘LOV SUMMASI|СУММА ОПЛАТЫ/i)).toBeInTheDocument();
  });

  it("4. smena OCHIQ + to'g'ri savat: ayni oqim, tugma ochiq", async () => {
    mockApi(routes());
    setShift(true);
    setCart([NON]);
    renderApp(<POSKassa />);
    expect(await screen.findByText(/Smena ochiq/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("pay-go")).toBeEnabled());
  });
});

// ═══ 2. PASTKI PANEL — TANLANGAN QATOR ═══════════════════════════════════════
describe("pastki panel tanlangan qatorga ishlaydi", () => {
  it("5. tanlovsiz: «Miqdor» va «Qatorni olib tashlash» O'CHIRILGAN (shartnoma)", async () => {
    mockApi(routes());
    setCart([NON, SUV]);
    renderApp(<POSKassa />);
    await waitFor(() => expect(screen.getAllByTestId("cart-row")).toHaveLength(2));
    expect(screen.getByTestId("act-qty")).toBeDisabled();
    expect(screen.getByTestId("act-remove")).toBeDisabled();
    // Qolgan ikkitasi savatga bog'liq (tanlovga emas) — ular OCHIQ
    expect(screen.getByTestId("act-hold")).toBeEnabled();
    expect(screen.getByTestId("act-clear")).toBeEnabled();
  });

  it("6. qatorni bosish TANLAYDI: ko'rinadigan holat + tugmalar ochiladi", async () => {
    mockApi(routes());
    setCart([NON, SUV]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    const rows = await screen.findAllByTestId("cart-row");
    await user.click(rows[1]);
    // KO'RINADIGAN tanlov holati: chap chetda ko'k chiziq (inset box-shadow)
    await waitFor(() => expect(rows[1].style.boxShadow).toMatch(/inset/));
    expect(rows[0].style.boxShadow).not.toMatch(/inset/);
    expect(screen.getByTestId("act-qty")).toBeEnabled();
    expect(screen.getByTestId("act-remove")).toBeEnabled();
  });

  it("7. «Miqdor» AYNAN tanlangan qatorning maydonini fokuslaydi", async () => {
    mockApi(routes());
    setCart([NON, SUV]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    const rows = await screen.findAllByTestId("cart-row");
    await user.click(rows[1]);                      // Suv 1L
    await user.click(screen.getByTestId("act-qty"));
    await waitFor(() => {
      const el = document.activeElement as HTMLInputElement | null;
      expect(el?.getAttribute("data-qty-for")).toBe(SUV.id);   // NON emas
    });
  });

  it("8. «Qatorni olib tashlash» FAQAT tanlangan qatorni o'chiradi", async () => {
    mockApi(routes());
    setCart([NON, SUV]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    const rows = await screen.findAllByTestId("cart-row");
    await user.click(rows[0]);                      // Non oq
    await user.click(screen.getByTestId("act-remove"));
    await waitFor(() => expect(useCart.getState().items.map((i) => i.id)).toEqual([SUV.id]));
  });

  it("9. tarozi qatori: kasr kg SAQLANADI va «Miqdor» unga QO'LLANMAYDI", async () => {
    mockApi(routes());
    setCart([POMIDOR]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    const rows = await screen.findAllByTestId("cart-row");
    await user.click(rows[0]);
    // ±1 stepper kasr vaznni buzardi — shu bois «Miqdor» tarozi qatorida O'CHIQ
    await waitFor(() => expect(screen.getByTestId("act-qty")).toBeDisabled());
    // Olib tashlash esa ISHLAYDI
    expect(screen.getByTestId("act-remove")).toBeEnabled();
    // Kasr miqdor o'zgarmagan
    expect(useCart.getState().items[0].qty).toBe(0.352);
  });

  it("10. o'chirilgandan keyin tanlov TOZALANADI — tugmalar yana o'chiq", async () => {
    mockApi(routes());
    setCart([NON, SUV]);
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    const rows = await screen.findAllByTestId("cart-row");
    await user.click(rows[0]);
    await user.click(screen.getByTestId("act-remove"));
    await waitFor(() => expect(screen.getAllByTestId("cart-row")).toHaveLength(1));
    // Tanlov qolmadi: qolgan qator O'Z-O'ZIDAN tanlanmaydi
    expect(screen.getByTestId("act-qty")).toBeDisabled();
    expect(screen.getByTestId("act-remove")).toBeDisabled();
  });

  it("pastki panel AYNAN TO'RT tugma (beshinchisi qo'shilmagan)", async () => {
    mockApi(routes());
    setCart([NON]);
    renderApp(<POSKassa />);
    await screen.findAllByTestId("cart-row");
    expect(document.querySelectorAll("footer button")).toHaveLength(4);
  });
});
