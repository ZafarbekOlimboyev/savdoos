import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { CACHE, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useCart } from "@/store/cart";
import { mockApi, renderApp } from "./util";

// SKANER YO'LI FAIL-CLOSED (POSKassa `onScan`).
//
// Nima uchun bu fayl bor: ilgari oqim `const hit = exact || shown[0]` bilan tugardi — ya'ni
// AYNAN mos kelmagan har qanday kiritma qidiruv ro'yxatining BIRINCHI qatorini 1 dona qilib
// savatga qo'shardi. `shown` esa `deferredQuery` bo'yicha (bir kadr kechikadi) va faqat
// nom/artikul bo'yicha filtrlanadi, shu bois skaner tez terganda u butun katalogning eng ko'p
// sotilgan qatori bo'lib qolardi. Buzuq etiketka yoki notanish kod kassirga bildirmasdan
// BOSHQA mahsulotni sotib yuborishi mumkin edi.
//
// Endi savatga FAQAT ikki yo'l bilan tushadi: (a) tanilgan tarozi etiketkasi + AYNAN mos PLU,
// (b) AYNAN mos shtrix-kod. Qolgan HAMMA holatda savat TEGILMAYDI va sabab ko'rsatiladi.

const SEARCH = "Mahsulot nomi, artikul yoki barcode...";

/** Fayzan do'konidan olingan HAQIQIY tarozi etiketkalari: [barkod, PLU, gramm, kg]. */
const REAL: Array<[string, string, number, number]> = [
  ["2700345032787", "345", 3278, 3.278],
  ["2700565020205", "565", 2020, 2.02],
  ["2700537004264", "537", 426, 0.426],
  ["2700349000560", "349", 56, 0.056],
];

const prod = (over: Partial<Record<string, unknown>> = {}) => ({
  id: "p-" + Math.random().toString(36).slice(2, 8),
  article_code: "A-1", name: "Tovar", category_id: null,
  base_sell_price: 1000, stock: 50, barcodes: [] as string[],
  plu_code: null, is_weighted: false, sold_qty: 0, is_active: true, ...over,
});

// Nom bo'yicha qidiruvga MOS keladigan, lekin barkodi BOSHQA mahsulot: eski zaxira aynan
// shuni qo'shib yuborardi. `sold_qty` yuqori — ro'yxatda birinchi bo'lib turadi.
const POPULAR = prod({ id: "p-pop", name: "Non", article_code: "NON-1", barcodes: ["4780000000011"], sold_qty: 999 });
const SODA = prod({ id: "p-soda", name: "Gazli suv", article_code: "GAZ-1", barcodes: ["4780000000028"] });
const WEIGHED = REAL.map(([, plu], i) =>
  prod({ id: "p-kg-" + plu, name: "Kg tovar " + plu, article_code: "KG-" + plu, plu_code: plu, is_weighted: true, base_sell_price: 12000 + i }));

const items = () => useCart.getState().items;

async function scan(user: ReturnType<typeof userEvent.setup>, code: string) {
  const input = await screen.findByPlaceholderText(SEARCH);
  await user.clear(input);
  await user.type(input, code + "{Enter}");
}

beforeEach(() => {
  // ⚠️  `/products` ni ATAYLAB to'g'ri javob bilan qaytaramiz: POSKassa mount'da `refreshCatalog()`
  //     ishga tushadi va javobni keshga YOZADI (`lib/sync.ts`). Umumiy `{}` javob keshni buzadi
  //     va ekran `products.filter is not a function` bilan yiqiladi.
  mockApi([
    [/\/products\b/, () => [POPULAR, SODA, ...WEIGHED]],
    [/\/categories\b/, () => []],
    [/\/settings\b/, () => ({})],
    [/./, {}],
  ]);
  useCart.setState({ carts: [[]], active: 0, items: [] });
  useAuth.setState({
    token: "tok",
    employee: {
      id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir",
      status: "active", branch_name: "Chilonzor filiali", permissions: ["kassa.sell"],
    },
  } as never);
  cacheSet(CACHE.products, [POPULAR, SODA, ...WEIGHED]);
  cacheSet(CACHE.cats, []);
});

describe("Skaner: AYNAN moslik bo'lmasa savat TEGILMAYDI", () => {
  it("aniq oddiy shtrix-kod → AYNAN o'sha mahsulot qo'shiladi", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "4780000000028");
    await waitFor(() => expect(items()).toHaveLength(1));
    expect(items()[0].id).toBe("p-soda");
    expect(items()[0].qty).toBe(1);
  });

  it("notanish shtrix-kod → savat BO'SH qoladi va sabab ko'rinadi", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "4780000009999");
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("nom bo'yicha topiladi, lekin AYNAN barkod yo'q → AVTOMATIK qo'shilmaydi", async () => {
    // REGRESSIYA: aynan shu holat eski `shown[0]` zaxirasida «Non» ni sotib yuborardi.
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "Non");
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("kassir ro'yxatdan O'ZI tanlasa — qo'shiladi", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "Non");                       // taklif ko'rinadi, savat tegilmaydi
    expect(items()).toHaveLength(0);
    await user.click(await screen.findByRole("button", { name: /Non/ }));
    await waitFor(() => expect(items()).toHaveLength(1));
    expect(items()[0].id).toBe("p-pop");
  });

  it("notanish prefiks (26…) → savat TEGILMAYDI", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "2600537004267");            // checksum TO'G'RI, prefiks 27 EMAS
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("ixtiyoriy raqamli kiritma → savat TEGILMAYDI", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "12345");
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });
});

describe("Skaner: tarozi etiketkasi", () => {
  for (const [code, plu, grams, kg] of REAL) {
    it(`REAL ${code} → PLU ${plu}, ${kg} kg`, async () => {
      const user = userEvent.setup();
      renderApp(<POSKassa />);
      await scan(user, code);
      await waitFor(() => expect(items()).toHaveLength(1));
      expect(items()[0].id).toBe("p-kg-" + plu);
      expect(items()[0].qty).toBeCloseTo(grams / 1000, 6);
      expect(items()[0].qty).toBeCloseTo(kg, 6);
    });
  }

  it("nazorat raqami BUZUQ → savat TEGILMAYDI", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "2700537004265");            // real barkodning oxirgi raqami o'zgartirilgan
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("shakli buzuq (12 raqam) → savat TEGILMAYDI", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "270053700426");
    expect(await screen.findByText(/Kod topilmadi/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("etiketka TO'G'RI, lekin bunday PLU'li tovar yo'q → savat TEGILMAYDI, PLU aytiladi", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "2799123015005");            // PLU 99123 — katalogda yo'q
    expect(await screen.findByText(/99123/)).toBeInTheDocument();
    expect(items()).toHaveLength(0);
  });

  it("bir xil etiketkani ikki marta skanerlash: BITTA qator, vazn QO'SHILADI", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await scan(user, "2700537004264");
    await waitFor(() => expect(items()).toHaveLength(1));
    await scan(user, "2700537004264");
    await waitFor(() => expect(items()[0].qty).toBeCloseTo(0.852, 6));
    expect(items()).toHaveLength(1);              // yangi qator OCHILMAYDI
  });
});
