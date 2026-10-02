import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { useShift } from "@/store/shift";
import { CACHE, cacheSet } from "@/lib/offline";
import { mockApi, renderApp } from "./util";

// ═══ F-1: KATALOG OCHIQ → SKANER JIM YO'QOLADI ═══════════════════════════════
//
// NUQSON (Phase 7 redizayni kiritgan). Skaner — oddiy klaviatura: raqamlarni
// yozadi, so'ng Enter. Barkod buferi — `pos-search` inputining `query` state'i,
// `onScan` esa AYNAN shu inputning `onKeyDown` ida (`POSKassa.tsx`). Ya'ni skan
// ishlashi uchun FOKUS shu inputda bo'lishi SHART.
//
// Katalog («Mahsulotlar» overlay'i) ochilganda:
//   1) overlay `position:fixed; inset:0; zIndex:21` — inputni QOPLAYDI (bosib
//      bo'lmaydi);
//   2) `onKey` (window listener) katalog ochiqda Escape'dan boshqa hammasini
//      early-return qiladi → F2 bilan ham fokusni QAYTARIB bo'lmaydi;
//   3) katalogni ochgan tugma fokusni O'ZIGA oladi.
// Natija: skaner zarbalari hech qayerga bormaydi — xato ham, savatga qo'shilish
// ham YO'Q. Kassir buni ko'rmaydi (fail-silent).
//
// ⚠️  CHEKLOV. Haqiqiy apparat skanerni (USB HID) jsdom'da ifodalash imkoni yo'q.
//     Eng tor DOM ekvivalenti ishlatilgan: `user.keyboard(...)` — u hodisalarni
//     `document.activeElement` ga yuboradi, aynan apparat skaner qilganidek,
//     ya'ni ATAYLAB hech bir elementni nishonga olmaydi. `onScan()` TO'G'RIDAN
//     chaqirilmaydi: nuqson aynan fokus/hodisa yo'naltirishida.

const BC_NON = "4780001234567";
const BC_SUV = "4780009999999";

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona", barcodes: [BC_NON] },
  { id: "p2", article_code: "A-2", name: "Pomidor", category_id: null, base_sell_price: 12000, stock: 50, unit_code: "kg", is_weighted: true, plu_code: "537", barcodes: [] },
  { id: "p3", article_code: "A-3", name: "Suv 1L", category_id: null, base_sell_price: 3000, stock: 80, unit_code: "dona", barcodes: [BC_SUV] },
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

const search = () => screen.getByTestId("pos-search") as HTMLInputElement;
const lines = () => useCart.getState().items;
const line = (id: string) => lines().find((i: CartLine) => i.id === id);

beforeEach(() => {
  localStorage.clear();
  cacheSet(CACHE.settings, SETTINGS);
  cacheSet(CACHE.products, PRODUCTS);
  cacheSet(CACHE.cats, []);
  useAuth.setState({ token: "t", employee: { id: "e1", full_name: "Test Kassir" } as any });
  useShift.setState({ current: { shift_id: "sh1", till_id: "t1", branch_id: "b1", till_code: "1" } as any });
  useCart.setState({ carts: [[]], active: 0, items: [] });
  vi.restoreAllMocks();
});

/** Kassir ekranni ochadi va (pre-P7 oqimi bo'yicha) qidiruv maydoniga kiradi. */
async function atTill() {
  mockApi(routes());
  const user = userEvent.setup();
  renderApp(<POSKassa />);
  await screen.findByTestId("pos-search");
  await user.click(search());
  return user;
}

describe("F-1 — katalog ochiqda skaner", () => {
  it("1. katalog YOPIQ: skan avvalgidek ishlaydi (regressiya bo'lmasin)", async () => {
    const user = await atTill();
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
    // Bufer tozalandi — keyingi skan uchun tayyor (`onScan` -> setQuery(""))
    expect(search().value).toBe("");
  });

  it("2. katalog OCHIQ: skan JIM YO'QOLMAYDI — ayni mahsulot yo'liga tushadi", async () => {
    const user = await atTill();
    // Katalogni ochish fokusni tugmaga oladi — haqiqiy kassir xatti-harakati
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    // Apparat skaner: hodisalar `document.activeElement` ga ketadi
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("3. bitta skan = AYNAN BIR marta qo'shiladi (ikki tinglovchi ikki marta ishlamasin)", async () => {
    const user = await atTill();
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    // Ikkinchi skan — aynan +1 (3 emas): bitta zarba bitta amal
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(2));
    // Boshqa barkod ALOHIDA qator ochadi, mavjudini buzmaydi
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(line("p3")?.qty).toBe(1));
    expect(lines()).toHaveLength(2);
    expect(line("p1")?.qty).toBe(2);
  });

  it("4. Escape katalogni YOPADI (P7 xulqi saqlanadi)", async () => {
    const user = await atTill();
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("catalog-overlay")).toBeNull());
  });

  it("5. katalog yopilgach fokus qidiruv/skaner maydoniga QAYTADI", async () => {
    const user = await atTill();
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.click(screen.getByTestId("catalog-close"));
    await waitFor(() => expect(screen.queryByTestId("catalog-overlay")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(search()));
    // Va skan darhol ishlaydi — kassir F2 qidirishga majbur emas
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(line("p3")?.qty).toBe(1));
  });

  it("6a. to'lov oynasidagi yozuv O'G'IRLANMAYDI", async () => {
    const user = await atTill();
    useCart.setState({ carts: [[{ id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" }]], active: 0, items: [{ id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" }] });
    await user.click(await screen.findByTestId("pay-go"));
    await user.click(await screen.findByRole("button", { name: "Naqd", exact: true }));
    const amount = screen.getAllByPlaceholderText("0")[0] as HTMLInputElement;
    await user.click(amount);
    await user.keyboard("5000");
    expect(amount.value).toBe("5000");
    // Yozuv savatga sizib o'tmadi
    expect(lines()).toHaveLength(1);
    expect(line("p1")?.qty).toBe(1);
  });

  it("6b. vazn (kg) dialogining fokusi O'G'IRLANMAYDI — katalog yopilsa ham", async () => {
    const user = await atTill();
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    // Vaznli mahsulot: katalog YOPILADI va vazn dialogi OCHILADI (P7 xulqi)
    await user.click(await screen.findByRole("button", { name: /Pomidor/ }));
    const kg = await screen.findByPlaceholderText("0.000 kg");
    await waitFor(() => expect(document.activeElement).toBe(kg));
    await user.keyboard("0.500");
    expect((kg as HTMLInputElement).value).toBe("0.500");
  });

  it("7. F2/F4 xulqi mos qoladi (katalog yopiq → ishlaydi, ochiq → to'silgan)", async () => {
    const user = await atTill();
    // F2 — qidiruvni fokuslaydi
    await user.click(screen.getByTestId("open-catalog"));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("catalog-overlay")).toBeNull());
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    // Katalog OCHIQ: F4 to'lov oynasini OCHMAYDI (P7 gardi saqlanadi)
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.keyboard("{F4}");
    expect(screen.queryByText(/TO‘LOV SUMMASI/i)).toBeNull();
    // Katalog yopilgach F4 yana ishlaydi
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("catalog-overlay")).toBeNull());
    useCart.setState({ carts: [[{ id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" }]], active: 0, items: [{ id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" }] });
    await user.keyboard("{F4}");
    expect(await screen.findByText(/TO‘LOV SUMMASI/i)).toBeInTheDocument();
  });
});
