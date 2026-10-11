import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { useShift } from "@/store/shift";
import { CACHE, cacheSet } from "@/lib/offline";
import { mockApi, renderApp } from "./util";

// ═══ J — NEGATIV NAZORAT ═════════════════════════════════════════════════════
//
// Bu fayl tuzatishni O'CHIRIB o'lchaydi. `createWedge` HECH QACHON barkod
// qaytarmaydigan qobiq bilan almashtiriladi: global skaner yo'li o'lik, qolgan
// hamma narsa (fokus mantiqi, `addByScan`, tarozi parseri, yorliqlar) TEGILMAGAN.
//
// Kutilgan natija: `pos-hardware-scan.test.tsx` dagi A holati (fokussiz skan)
// YIQILADI — ya'ni A testini yashil qilgan narsa aynan global yo'l, tasodif
// yoki boshqa qatlam EMAS. Ayni paytda fokusli (F2) yo'l AVVALGIDEK ishlaydi,
// bu esa qobiq boshqa hech narsani buzmaganini isbotlaydi.
//
// ⚠️  Qatlamni O'ZINI o'chirib o'lchash SHART: aks holda «A yashil» degani
//     tuzatish ishlaganini emas, shunchaki test kuchsizligini bildirardi.

vi.mock("@/lib/scanWedge", async () => {
  const real = await vi.importActual<typeof import("@/lib/scanWedge")>("@/lib/scanWedge");
  return {
    ...real,
    //  Bufer yig'adi, lekin skanni HECH QACHON «da'vo qilmaydi».
    createWedge: () => ({ push: () => null, reset: () => {}, peek: () => "" }),
  };
});

const BC_NON = "4780001234567";

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona", barcodes: [BC_NON] },
];

const SETTINGS = {
  features: { returns: true },
  payments: { karta: true, qr: true, qarz: true },
  store_info: { name: "Test Do'kon", branch: "Test filiali" },
};

function routes(): [RegExp, any][] {
  return [
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
});

async function atTillNoFocus() {
  mockApi(routes());
  const user = userEvent.setup();
  renderApp(<POSKassa />);
  await screen.findByTestId("pos-search");
  return user;
}

describe("J — negativ nazorat: global skaner yo'li o'chirilsa", () => {
  it("fokussiz skan YO'QOLADI (A holati tuzatishsiz YIQILADI)", async () => {
    const user = await atTillNoFocus();
    expect(document.activeElement).not.toBe(search());
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Tuzatish o'chiq — zarbalar `<body>` ga ketdi va JIM yo'qoldi.
    //  AYNAN shu haqiqiy apparatda kuzatilgan xulq.
    expect(lines()).toHaveLength(0);
  });

  it("fokusli (F2) yo'l esa AVVALGIDEK ishlaydi — qobiq boshqa narsani buzmadi", async () => {
    const user = await atTillNoFocus();
    await user.click(search());
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
  });
});
