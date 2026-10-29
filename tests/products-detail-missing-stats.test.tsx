/**
 * MAHSULOT DETALI — server maydonlarni yubormaganda ham YIQILMAYDI va
 * NOMA'LUM qiymatni NOL deb KO'RSATMAYDI.
 *
 * NEGA BU FAYL BOR (CI run 40864017103 da O'LCHANGAN, taxmin emas)
 * ================================================================
 * `Frontend (komponent sinovlari)` ishi `47 test files passed, 867 tests
 * passed` bilan ham **exit 1** qaytardi: `5 errors` —
 *
 *     TypeError: Cannot read properties of undefined (reading 'qty')
 *       at StatBlock  packages/shared/src/screens/Products.tsx:649
 *       at FullDetail packages/shared/src/screens/Products.tsx:1335
 *
 * Sababi `StatBlock` ICHKI OBYEKTNI guardsiz o'qishi:
 *
 *     <StatBlock title={...} s={d.sales_30d} />      // :691
 *     ...{s.qty}... {fmt(s.revenue)}... {s.profit >= 0 ...}   // :649
 *
 * `d` uchun guard BOR (`{!d ? loading : ...}`), `d.sales_*` uchun YO'Q edi.
 *
 * ⚠️  NEGA BU FAQAT FIKSTURA MUAMMOSI EMAS — IKKI O'LCHANGAN SABAB:
 *
 *   1. REPODA ErrorBoundary YO'Q. `packages/shared/src`, `apps/pos/src` va
 *      `apps/manager/src` da `componentDidCatch` / `getDerivedStateFromError`
 *      — 0 joy. Ikkala ilova `createHashRouter` + `RouterProvider` ni birorta
 *      `errorElement` SIZ ishlatadi, shu bois bu `throw` react-router ning
 *      standart xato sahifasini («Unexpected Application Error!») BUTUN
 *      qobiq ustiga chiqaradi — kassir uchun ilova ISHLAMAY QOLADI.
 *
 *   2. KLIENT/SERVER SKEWI HAQIQIY. `.exe` avto-yangilanadi (har ishga
 *      tushishda + har 4 soatda), `sales_7d` esa API ga KEYINCHALIK qo'shilgan
 *      (`2d1429a`). CLAUDE.md ning «AVVAL SERVER, KEYIN KLIENT» qoidasi aynan
 *      shu xavf uchun yozilgan — lekin qoida BUZILGANDA (yoki server rollback
 *      qilinganda) nima bo'lishini ham hal qilish kerak.
 *
 * NEGA «—», NEGA 0 EMAS: 0 — «hech narsa sotilmadi» degan HAQIQIY o'lchov.
 * Bu holat esa «NOMA'LUM». Nolni ko'rsatish operatorni CHALG'ITARDI.
 *
 * ⚠️  ENG XAVFLI SHAKL O'LCHANGAN: `fmt(undefined)` «0 so'm» qaytaradi
 *     (`lib/format.ts` da `const x = n || 0`). Ya'ni gardsiz holatda
 *     NOMA'LUM foyda ekranda NOL PUL bo'lib chiqadi — bu `undefined%` dan
 *     ham yomon, chunki ISHONCHLI ko'rinadi. Shu bois quyida ikki yo'nalish
 *     ham mixlangan: noma'lum → «—», HAQIQIY nol → 0.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Products, type Product } from "@/screens/Products";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp, type Call } from "./util";

const BC = "4780001234567";

/** RO'YXAT shakli — `GET /products` AYNAN shuni qaytaradi. */
const LIST: Product = {
  id: "p1", article_code: "A-1", sku: "1", name: "Non oq", category_id: "c1",
  base_buy_price: 7000, base_sell_price: 12000, stock: 10, min_stock: 0,
  unit_code: "dona", expiry_date: null, barcodes: [BC],
  track_lots: false, track_expiry: false,
};

/** DETAL shakli — `GET /products/{id}` AYNAN shuni qaytaradi (`FullD`). */
const DETAIL = {
  ...LIST,
  profit_unit: 5000, margin_pct: 41, month_in: 3, month_out: 1,
  sales_7d: { qty: 2, revenue: 24000, profit: 10000 },
  sales_30d: { qty: 7, revenue: 84000, profit: 35000 },
  last_sold_at: null, is_weighted: false, plu_code: null, created_by_name: "Test",
};

/** HAMMA raqam HAQIQATAN nol — «noma'lum» EMAS. */
const NOL = {
  ...LIST,
  base_buy_price: 0, base_sell_price: 0, stock: 0,
  profit_unit: 0, margin_pct: 0, month_in: 0, month_out: 0,
  sales_7d: { qty: 0, revenue: 0, profit: 0 },
  sales_30d: { qty: 0, revenue: 0, profit: 0 },
  last_sold_at: null, is_weighted: false, plu_code: null, created_by_name: "Test",
};

beforeEach(() => {
  localStorage.clear();
  useAuth.setState({
    token: "t",
    employee: { id: "e1", full_name: "Test", permissions: ["ombor.view", "ombor.edit", "sotuv.view"] } as any,
  });
  vi.restoreAllMocks();
});

/** Detal sahifasini AYNI usul bilan ochadi: fokussiz skan (mavjud testlar
 *  naqshi). `detail` — `/products/{id}` javobi. */
async function ochDetal(detail: unknown) {
  const calls = mockApi([
    [/\/products\?tracked=true/, []],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/inventory\/movements/, []],
    [/\/products\/p1$/, detail],
    [/\/products(\?|$)/, [LIST]],
    [/\/categories/, [{ id: "c1", name: "Non" }]],
    [/\/suppliers/, []],
  ]);
  const user = userEvent.setup();
  renderApp(<Products />);
  await screen.findByText("Non oq");
  await user.keyboard(`${BC}{Enter}`);
  //  ⚠️  DETAL SAHIFASI TO'LIQ CHIZILISHINI KUTAMIZ. Shu kutish testni
  //      DETERMINISTIK qiladi: `opened(calls)` tasdig'i so'rov QAYD
  //      ETILISHIDA bajariladi, render esa keyinroq — kutmasa, xato
  //      ko'rinmasligi mumkin edi.
  const sarlavha = await screen.findByText("So'nggi 30 kun");
  return { calls, blok30: sarlavha.closest(".card") as HTMLElement };
}

/** Sarlavhasi bo'yicha bitta `Stat` plitkasini qaytaradi. */
const karta = (label: string) => screen.getByText(label).closest(".card") as HTMLElement;

const opened = (calls: Call[]) =>
  calls.filter((c) => /\/products\/p\d+$/.test(c.url)).map((c) => c.url.split("/").pop());

describe("MAHSULOT DETALI — to'liqsiz javob", () => {
  it("`sales_30d`/`sales_7d` YO'Q: yiqilmaydi, «—» chiziladi (0 EMAS)", async () => {
    //  ATAYLAB RO'YXAT shakli: `sales_*`, `profit_unit`, `margin_pct`,
    //  `month_in`, `month_out` YO'Q — aynan CI'da yiqilgan holat.
    const { calls, blok30 } = await ochDetal(LIST);

    expect(blok30).toBeTruthy();
    expect(blok30.textContent).toContain("Sotildi");
    //  NOMA'LUM -> «—».
    expect(blok30.textContent).toContain("—");
    //  VA 0 EMAS: «Sotildi 0» soxta o'lchov bo'lardi.
    expect(blok30.textContent).not.toMatch(/Sotildi\s*0(\D|$)/);

    //  7 kunlik blok ham chizildi (ikkinchi `StatBlock`).
    const blok7 = (await screen.findByText("So'nggi 7 kun")).closest(".card") as HTMLElement;
    expect(blok7.textContent).toContain("—");

    //  ⚠️  A3 — AYNI SINFNING JIM SHAKLI. Bu to'rt maydon TypeError BERMAYDI,
    //      shu bois CI ni qizil qilmasdi; ular YOLG'ON ko'rsatardi.
    //      O'lchangan (gardsiz): «Foyda (dona) 0 so'm» · «Margin undefined%» ·
    //      «Bu oy kirim +undefined» · «Bu oy chiqim −undefined».
    expect(karta("Foyda (dona)").textContent).toContain("—");
    //  ENG MUHIM TASDIQ: noma'lum foyda NOL PUL bo'lib ko'rinmasin.
    expect(karta("Foyda (dona)").textContent).not.toMatch(/\b0\b/);
    expect(karta("Margin").textContent).toContain("—");
    expect(karta("Bu oy kirim").textContent).toContain("—");
    expect(karta("Bu oy chiqim").textContent).toContain("—");

    //  Butun sahifada buzuq matn QOLMADI.
    expect(document.body.textContent).not.toContain("undefined");
    expect(document.body.textContent).not.toContain("NaN");

    //  SKANER XULQI O'ZGARMAGAN: aynan p1 ochildi, bir marta.
    expect(opened(calls)).toEqual(["p1"]);
  });

  it("POZITIV NAZORAT: to'liq javobda RAQAMLAR ko'rinadi («—» emas)", async () => {
    //  ⚠️  BU TEST MAJBURIY: usiz birinchi test «—» ni har qanday holatda
    //      topib, VAKUUMDA yashil bo'lardi.
    const { calls, blok30 } = await ochDetal(DETAIL);

    expect(blok30.textContent).toContain("Sotildi");
    //  `sales_30d.qty = 7` -> ko'rinadi.
    expect(blok30.textContent).toMatch(/Sotildi\s*7(\D|$)/);
    //  Bu blokda «—» BO'LMASLIGI shart.
    expect(blok30.textContent).not.toContain("—");

    const blok7 = (await screen.findByText("So'nggi 7 kun")).closest(".card") as HTMLElement;
    expect(blok7.textContent).toMatch(/Sotildi\s*2(\D|$)/);

    //  A3 maydonlari ham HAQIQIY qiymatni ko'rsatadi.
    expect(karta("Margin").textContent).toContain("41%");
    expect(karta("Bu oy kirim").textContent).toContain("+3");
    expect(karta("Bu oy chiqim").textContent).toContain("−1");
    expect(karta("Foyda (dona)").textContent).not.toContain("—");

    //  `barcodes` massivi kelganda chip CHIZILADI (A2 ning pozitiv tomoni).
    expect(screen.getByText(BC)).toBeInTheDocument();

    expect(opened(calls)).toEqual(["p1"]);
  });

  it("HAQIQIY NOL «—» ga AYLANMAYDI (0 — o'lchov, noma'lumlik emas)", async () => {
    //  ⚠️  BU TEST GARD SHAKLINI MIXLAYDI. `??` / `== null` o'rniga `||` yoki
    //      `!s` ishlatilsa HAQIQIY nol «—» ga aylanib, «hech narsa
    //      sotilmadi» ma'lumoti YO'QOLARDI. O'lchangan: 0 so'm · 0% · +0 ·
    //      −0 · «Sotildi 0».
    const { calls, blok30 } = await ochDetal(NOL);

    expect(blok30.textContent).toMatch(/Sotildi\s*0(\D|$)/);
    expect(blok30.textContent).not.toContain("—");

    const blok7 = (await screen.findByText("So'nggi 7 kun")).closest(".card") as HTMLElement;
    expect(blok7.textContent).toMatch(/Sotildi\s*0(\D|$)/);
    expect(blok7.textContent).not.toContain("—");

    expect(karta("Margin").textContent).toContain("0%");
    expect(karta("Margin").textContent).not.toContain("—");
    expect(karta("Bu oy kirim").textContent).toContain("+0");
    expect(karta("Bu oy chiqim").textContent).toContain("−0");
    expect(karta("Foyda (dona)").textContent).not.toContain("—");

    expect(opened(calls)).toEqual(["p1"]);
  });

  it("`barcodes` YO'Q: yiqilmaydi, chip chizilmaydi (A2)", async () => {
    //  AYNI SINFNING IKKINCHI NUSXASI: ichki MASSIVGA guardsiz murojaat
    //  (`d.barcodes.length`, `d.barcodes.map`). Serverda bu maydon bor, lekin
    //  bo'sh tana / eski shakl AYNI xato sahifasini berardi.
    const { barcodes: _olib_tashlandi, ...BARKODSIZ } = DETAIL;
    const { calls, blok30 } = await ochDetal(BARKODSIZ);

    //  Sahifa YIQILMADI: statistika HAQIQIY raqamlar bilan chizildi.
    expect(blok30.textContent).toMatch(/Sotildi\s*7(\D|$)/);
    //  Chip YO'Q (massiv yo'q), lekin bu xatosiz holat.
    expect(screen.queryByText(BC)).toBeNull();
    expect(document.body.textContent).not.toContain("undefined");

    expect(opened(calls)).toEqual(["p1"]);
  });

  it("javob BO'SH obyekt bo'lsa ham yiqilmaydi (eng qo'pol skew)", async () => {
    //  Eng yomon holat: server 200 qaytaradi, lekin tana bo'sh `{}`.
    //  `d` «truthy» bo'lgani uchun `{!d ? ...}` gardi O'TKAZIB YUBORADI.
    const calls = mockApi([
      [/\/products\?tracked=true/, []],
      [/\/products\/guess-category/, { category_id: null }],
      [/\/inventory\/movements/, []],
      [/\/products\/p1$/, {}],
      [/\/products(\?|$)/, [LIST]],
      [/\/categories/, [{ id: "c1", name: "Non" }]],
      [/\/suppliers/, []],
    ]);
    const user = userEvent.setup();
    renderApp(<Products />);
    await screen.findByText("Non oq");
    await user.keyboard(`${BC}{Enter}`);
    //  Ro'yxat ko'rinishi almashdi — detal sahifasiga o'tildi.
    await waitFor(() => expect(screen.queryByText("Non oq")).toBeNull());
    //  Sahifa YIQILMADI: statistika sarlavhalari chizildi.
    const blok30 = (await screen.findByText("So'nggi 30 kun")).closest(".card") as HTMLElement;
    expect(blok30.textContent).toContain("—");
    expect(opened(calls)).toEqual(["p1"]);
  });
});
