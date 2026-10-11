import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullReceiving, Products, type Product } from "@/screens/Products";
import { Returns } from "@/screens/Returns";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp, type Call } from "./util";

// ═══ NEGATIV NAZORAT (P7 / S7 / R5) ══════════════════════════════════════════
//
// Bu fayl umumiy skaner yo'lini O'CHIRIB o'lchaydi: `createWedge` hech qachon
// barkod qaytarmaydigan qobiq bilan almashtiriladi. Qolgan hamma narsa —
// fokus mantiqi, ekran handlerlari, `onBarcode`, `scanCode`, fuzzy filtr —
// TEGILMAGAN.
//
// Kutilgan natija: `scanner-universal.test.tsx` dagi FOKUSSIZ holatlar
// (P1 / S1 / R1) YIQILADI, ya'ni ularni yashil qilgan narsa aynan umumiy
// yo'l — tasodif yoki boshqa qatlam EMAS. Fokusli (input ichidagi) yo'llar
// esa AVVALGIDEK ishlaydi, bu esa qobiq boshqa hech narsani buzmaganini
// isbotlaydi.

vi.mock("@/lib/scanWedge", async () => {
  const real = await vi.importActual<typeof import("@/lib/scanWedge")>("@/lib/scanWedge");
  return { ...real, createWedge: () => ({ push: () => null, reset: () => {}, peek: () => "" }) };
});

const BC_NON = "4780001234567";

const prod = (over: Partial<Product>): Product => ({
  id: "p0", article_code: "A-0", sku: "0", name: "Tovar", category_id: "c1",
  base_buy_price: 7000, base_sell_price: 12000, stock: 0, min_stock: 0, unit_code: "dona",
  expiry_date: null, barcodes: [], track_lots: false, track_expiry: false, ...over,
});
const NON = prod({ id: "p1", name: "Non oq", barcodes: [BC_NON], stock: 10, base_sell_price: 4000 });
const CATS = [{ id: "c1", name: "Ichimliklar" }];
const SUPS = [{ id: "s1", name: "Ta'minotchi" }];

const SALE = {
  id: "s1", receipt_no: "#1001", uid: "2610111001", method: "cash",
  sold_at: "2026-10-11T10:00:00Z", cashier: "Test", total: 4000,
  items: [{ product_id: "p1", name: "Non oq", qty: 2, returnable: 2, unit_price: 4000, barcode: BC_NON, barcodes: [BC_NON] }],
};

beforeEach(() => {
  localStorage.clear();
  useAuth.setState({
    token: "t",
    employee: { id: "e1", full_name: "Test", permissions: ["ombor.view", "ombor.edit", "sotuv.view"] } as any,
  });
});

const opened = (calls: Call[]) =>
  calls.filter((c) => /\/products\/p\d+$/.test(c.url)).map((c) => c.url.split("/").pop());

describe("P7 — MAHSULOTLAR: umumiy yo'l o'chirilsa fokussiz skan YO'QOLADI", () => {
  function mount() {
    const calls = mockApi([
      [/\/products\?tracked=true/, []],
      [/\/inventory\/movements/, []],
      [/\/products\/(p1)$/, NON],
      [/\/products(\?|$)/, [NON]],
      [/\/categories/, CATS],
      [/\/suppliers/, SUPS],
    ]);
    const user = userEvent.setup();
    renderApp(<Products />);
    return { user, calls };
  }

  it("fokussiz skan hech narsa qilmaydi (P1 tuzatishsiz YIQILADI)", async () => {
    const { user, calls } = mount();
    await screen.findByText("Non oq");
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 30));
    //  Navigatsiya YO'Q — zarbalar `<body>` ga ketib JIM yo'qoldi.
    expect(opened(calls)).toEqual([]);
    expect(screen.queryByTestId("prod-scan-err")).toBeNull();
  });

  it("FOKUSLI (qidiruv maydoni) yo'l esa AVVALGIDEK ishlaydi", async () => {
    const { user, calls } = mount();
    await screen.findByText("Non oq");
    await user.click(screen.getByPlaceholderText(/qidirish/i));
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Bu AYNI mavjud `onSearchEnter` yo'li — qobiq unga tegmadi.
    await waitFor(() => expect(opened(calls)).toEqual(["p1"]));
  });
});

describe("S7 — QO'LDA KIRIM: umumiy yo'l o'chirilsa fokussiz skan YO'QOLADI", () => {
  it("fokussiz skan qator QO'SHMAYDI va to'ldirmaydi (S1 tuzatishsiz YIQILADI)", async () => {
    mockApi([
      [/\/products\?tracked=true/, []],
      [/\/products\/guess-category/, { category_id: null }],
    ]);
    const user = userEvent.setup();
    renderApp(<FullReceiving cats={CATS} products={[NON]} suppliers={SUPS} onBack={() => {}} onSaved={() => {}} />);
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryAllByPlaceholderText("Mahsulot nomi")).toHaveLength(0);
  });
});

describe("R5 — QAYTARISH: umumiy yo'l o'chirilsa fokussiz skan YO'QOLADI", () => {
  it("chek topilgach fokussiz skan miqdorni OSHIRMAYDI (R1 tuzatishsiz YIQILADI)", async () => {
    mockApi([
      [/\/sales\/find/, SALE],
      [/\/sales\?limit=8/, []],
    ]);
    const user = userEvent.setup();
    renderApp(<Returns />);
    await screen.findByPlaceholderText("Chek shtrix kodi yoki ID...");
    await user.click(screen.getByPlaceholderText("Chek shtrix kodi yoki ID..."));
    await user.keyboard("#1001{Enter}");
    await screen.findByText("Non oq");
    //  Fokus bo'shatilgan (bu qism qobiqdan MUSTAQIL), lekin umumiy yo'l o'lik.
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByTestId("ret-qty-0").textContent).toBe("0");
  });
});
