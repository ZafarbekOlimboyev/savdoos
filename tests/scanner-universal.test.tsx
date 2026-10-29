import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullReceiving, Products, type Product } from "@/screens/Products";
import { Returns } from "@/screens/Returns";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp, type Call } from "./util";

// ═══ UMUMIY APPARAT-SKANER YO'LI — EKRAN-MA-EKRAN QABUL ══════════════════════
//
// POS uchun tuzatish (95ef2f6) real apparatda PASS bo'ldi. Ega qolgan uch
// ekranni fizik skaner bilan sinab FAIL berdi:
//   · Mahsulotlar/ombor — fokussiz skan ishlamaydi
//   · Qo'lda kirim      — fokussiz ishlamaydi + skaner `Enter` i YANGI BO'SH
//                         QATOR qo'shadi
//   · Qaytarish         — fokus/F2 ga bog'liq
//
// Ushlash mantiqi endi YAGONA: `lib/useBarcodeScanner` (`lib/scanWedge` ustida).
// Har ekran faqat semantikani beradi.
//
// ⚠️  HARNESS HECH QANDAY INPUTNI FOKUSLAMAYDI. Aynan shu xato mavjud F-1
//     to'plamini yashil tutib turgan edi: uning `atTill()` yordamchisi har
//     testni `user.click(search())` bilan boshlab, skanerning yagona yo'lini
//     oldindan fokuslardi va nuqsonni SHARTGA aylantirardi.
//
// ⚠️  CHEKLOV: USB HID skanerni jsdom'da ifodalash imkoni yo'q. Eng tor DOM
//     ekvivalenti — `user.keyboard(...)`, u hodisalarni `document.activeElement`
//     ga yuboradi va hech bir elementni nishonga olmaydi.

const BC_NON = "4780001234567";      // Non oq
const BC_SUV = "4780009999999";      // Suv 1L
const BC_UNKNOWN = "4779999999999";  // katalogda YO'Q
const BC_REAL = "4700040115745";     // eganing HAQIQIY skaneridan

const prod = (over: Partial<Product>): Product => ({
  id: "p0", article_code: "A-0", sku: "0", name: "Tovar", category_id: "c1",
  base_buy_price: 7000, base_sell_price: 12000, stock: 0, min_stock: 0, unit_code: "dona",
  expiry_date: null, barcodes: [], track_lots: false, track_expiry: false, ...over,
});

const NON = prod({ id: "p1", name: "Non oq", barcodes: [BC_NON], stock: 10, base_sell_price: 4000 });
const SUV = prod({ id: "p3", name: "Suv 1L", barcodes: [BC_SUV], stock: 8, base_sell_price: 3000 });
const CHOY = prod({ id: "p4", name: "Choy", barcodes: [BC_REAL], stock: 5, base_sell_price: 15000 });
/** `GET /products/{id}` javobining DETAL shakli (`Products.tsx` dagi `FullD`).
 *
 *  ⚠️  RO‘YXAT shakli (`prod()`) YETARLI EMAS va ilgari AYNAN shu
 *      ishlatilgan edi: `FullD` da `sales_7d`/`sales_30d` ICHKI OBYEKT, ularsiz
 *      `StatBlock` `TypeError: ... reading 'qty'` bilan yiqilardi. Assertionlar
 *      O‘TSA HAM vitest unhandled error bilan exit 1 berardi
 *      (CI run 40864017103: `47 files passed, 867 tests passed, 5 errors`).
 *      Backend ikkala maydonni SHARTSIZ yuboradi (`api/v1/products.py`), ya’ni
 *      bu FIKSTURA mos kelmasligi edi.
 *
 *  ⚠️  FIKSTURA TO‘LIQLIGI GARD O‘RNINI BOSMAYDI. Komponent gardi
 *      ALOHIDA tuzatish (`Products.tsx` dagi `StatBlock` izohi) va u ALOHIDA
 *      test bilan mixlangan (`tests/products-detail-missing-stats.test.tsx`) —
 *      aks holda to‘liq fikstura gardsiz komponentni NIQOBLARDI (repodagi
 *      tayyor misol: `tests/products-expiry.test.tsx` gardsiz `FullDetail` ni
 *      ochadi va yashil, chunki uning fiksturasi maydonlarni beradi). */
const detail = (p: Product) => ({
  ...p,
  profit_unit: p.base_sell_price - p.base_buy_price,
  margin_pct: 42, month_in: 3, month_out: 1,
  sales_7d: { qty: 2, revenue: 2 * p.base_sell_price, profit: 1000 },
  sales_30d: { qty: 7, revenue: 7 * p.base_sell_price, profit: 5000 },
  last_sold_at: null, is_weighted: false, plu_code: null, created_by_name: "Test",
});

/** Detal sahifasi HAQIQATAN chizilganini tasdiqlaydi.
 *
 *  ⚠️  NEGA KERAK (mustaqil ko‘rikda o‘lchangan): ilgari testlar
 *      `expect(screen.queryByText("Non oq")).toBeNull()` bilan «navigatsiya
 *      bo‘ldi» deb xulosa chiqarardi. Bu tasdiq RENDER YIQILGANDA HAM
 *      bajariladi — daraxt uzilgach ro‘yxat matni ham yo‘qoladi. Ya’ni
 *      testlar «detalga o‘tdi» ni «detal portladi» dan AJRATA OLMASDI:
 *      gardsiz ham 22/22 PASS edi, qizillikni faqat vitest ning
 *      unhandled-error siyosati berardi. Quyidagi yordamchi POZITIV o‘lchov
 *      qo‘yadi: detal sahifasining O‘ZIGA XOS elementlari. */
async function detalChizildi(nom: string) {
  //  Sarlavha — detal sahifasining `h1` i.
  await screen.findByText(nom);
  //  Statistika bloklari FAQAT detal sahifasida bor (ro‘yxatda YO‘Q).
  await screen.findByText("So'nggi 30 kun");
  await screen.findByText("So'nggi 7 kun");
}

const CATS = [{ id: "c1", name: "Ichimliklar" }];
const SUPS = [{ id: "s1", name: "Ta'minotchi" }];
const ALL = [NON, SUV, CHOY];

beforeEach(() => {
  localStorage.clear();
  useAuth.setState({
    token: "t",
    employee: { id: "e1", full_name: "Test", permissions: ["ombor.view", "ombor.edit", "sotuv.view"] } as any,
  });
  vi.restoreAllMocks();
});

// ═══════════════════════════════════════════════════════════════════════════
//  MAHSULOTLAR / OMBOR  (P1–P6)
// ═══════════════════════════════════════════════════════════════════════════

function mountProducts() {
  const calls = mockApi([
    [/\/products\?tracked=true/, []],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/inventory\/movements/, []],
    //  Detal sahifasi AYRIM so'rov qiladi (`/products/{id}`) — mock SHU bo'lmasa
    //  sarlavha «…» bo'lib qolardi va test o'z selektorida yiqilardi.
    //  DETAL shakli (`detail()` izohiga qarang) — ro‘yxat shakli crash berardi.
    [/\/products\/(p1|p3|p4)$/, (c: Call) => {
      const p = ALL.find((x) => c.url.endsWith("/" + x.id));
      return p ? detail(p) : undefined;
    }],
    [/\/products(\?|$)/, ALL],
    [/\/categories/, CATS],
    [/\/suppliers/, SUPS],
  ]);
  const user = userEvent.setup();
  renderApp(<Products />);
  return { user, calls };
}

const psearch = () => screen.getByPlaceholderText(/qidirish/i) as HTMLInputElement;
const scanErr = () => screen.queryByTestId("prod-scan-err");
/** Detal sahifasi `GET /products/{id}` qiladi — skan QAYSI mahsulotni hal
 *  qilganining to'g'ridan-to'g'ri o'lchovi (render shakliga bog'liq emas). */
const opened = (calls: Call[]) =>
  calls.filter((c) => /\/products\/p\d+$/.test(c.url)).map((c) => c.url.split("/").pop());

describe("MAHSULOTLAR — fokusdan mustaqil skan (P1–P6)", () => {
  it("P1. fokussiz tanilgan barkod → AYNAN shu mahsulot sahifasi ochiladi", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Non oq");
    //  Hech narsa bosilmadi — fokus `<body>` da.
    expect(document.activeElement).not.toBe(psearch());
    await user.keyboard(`${BC_SUV}{Enter}`);
    //  Ro'yxat ko'rinishi almashdi va AYNAN p3 (Suv 1L) ochildi.
    await waitFor(() => expect(screen.queryByText("Non oq")).toBeNull());
    //  ⚠️  RO‘YXAT YO‘QOLISHI NAVIGATSIYA ISBOTI EMAS (`detalChizildi`
    //      izohiga qarang): u render YIQILGANDA ham bajariladi. POZITIV o‘lchov:
    await detalChizildi("Suv 1L");
    expect(opened(calls)).toEqual(["p3"]);
    expect(scanErr()).toBeNull();
  });

  it("P1b. eganing HAQIQIY kodi (4700040115745) fokussiz ishlaydi", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Choy");
    await user.keyboard(`${BC_REAL}{Enter}`);
    await waitFor(() => expect(screen.queryByText("Non oq")).toBeNull());
    await detalChizildi("Choy");       //  POZITIV: detal HAQIQATAN chizildi
    expect(opened(calls)).toEqual(["p4"]);
  });

  it("P2. tanilmagan barkod → XAVFSIZ no-match (navigatsiya YO'Q, xabar KO'RINADI)", async () => {
    const { user } = mountProducts();
    await screen.findByText("Non oq");
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    //  FAIL-LOUD: ilgari `onSearchEnter` jimgina qaytardi.
    await waitFor(() => expect(scanErr()).not.toBeNull());
    expect(scanErr()!.textContent).toMatch(/topilmadi/i);
    //  Ro'yxat JOYIDA: hech qaysi mahsulot ochilmadi, «birinchi ko'rinayotgan»
    //  kabi zaxira tanlov YO'Q.
    expect(screen.getByText("Non oq")).toBeInTheDocument();
    expect(screen.getByText("Suv 1L")).toBeInTheDocument();
  });

  it("P3. qidiruv maydoni FOKUSDA: skan AYNAN BIR marta ishlanadi", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Non oq");
    await user.click(psearch());
    expect(document.activeElement).toBe(psearch());
    await user.keyboard(`${BC_SUV}{Enter}`);
    //  Ikki yo'l (input `onSearchEnter` + umumiy hook) FOKUS bo'yicha o'zaro
    //  inkor: AYNAN BITTA detal so'rovi ketdi, ikki emas.
    await waitFor(() => expect(screen.queryByText("Non oq")).toBeNull());
    await detalChizildi("Suv 1L");     //  POZITIV: detal HAQIQATAN chizildi
    expect(opened(calls)).toEqual(["p3"]);
    expect(scanErr()).toBeNull();
  });

  it("P4. ODAMNING nom bo'yicha qidiruvi AVVALGIDEK ishlaydi (fuzzy saqlandi)", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Non oq");
    await user.click(psearch());
    //  ⚠️  «Choy» ATAYLAB: 4 belgi, ya'ni `WEDGE_MIN_LEN` dan KAM EMAS. Agar
    //      tahrirlanadigan-fokus gardi olib tashlansa, umumiy yo'l aynan shu
    //      so'zni DA'VO qilib `onHardwareScan("Choy")` chaqiradi va «Mahsulot
    //      topilmadi» chiqadi — ya'ni bu test GARDNI O'LDIRADI. Qisqa so'z
    //      (masalan «Suv») bilan test TISHSIZ bo'lardi.
    await user.keyboard("Choy{Enter}");
    //  Fuzzy filtr ishladi: Choy qoladi, Non chiqib ketadi.
    await waitFor(() => expect(screen.queryByText("Non oq")).toBeNull());
    expect(screen.getByText("Choy")).toBeInTheDocument();
    //  Odam yozuvi skan deb QABUL QILINMADI: na xato, na navigatsiya.
    expect(scanErr()).toBeNull();
    expect(opened(calls)).toEqual([]);
  });

  it("P5. takror skan DETERMINISTIK (ayni sahifa, xato yo'q)", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Non oq");
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(opened(calls)).toEqual(["p3"]));
    //  ⚠️  POZITIV: detal sahifasi HAQIQATAN chizildi. Bu tasdiqsiz P5 O‘LIK
    //      test edi — chunki «ikkinchi skan sahifani almashtirmadi» ni
    //      `StatBlock` ning TypeError’i ham «ta’minlardi» (daraxt uzilgach
    //      almashtiriladigan hech narsa qolmaydi).
    await detalChizildi("Suv 1L");
    //  Detal sahifasi ochiq — `enabled` false, skan sahifani ALMASHTIRMAYDI
    //  (ro'yxat ostidan boshqa mahsulotga o'tib ketish xavfi yopilgan).
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 30));
    expect(opened(calls)).toEqual(["p3"]);
  });

  it("P6. tahrirlanadigan maydonda ODAM yozuvi skan deb QABUL QILINMAYDI", async () => {
    const { user, calls } = mountProducts();
    await screen.findByText("Non oq");
    await user.click(psearch());
    //  Barkodga O'XSHAGAN, lekin TANILMAGAN kod — odam yozmoqda.
    await user.keyboard(BC_UNKNOWN);
    //  Belgilar INPUTGA tushdi (skaner yo'li ularni yutib ketmadi).
    expect(psearch().value).toBe(BC_UNKNOWN);
    //  Enter'siz: skan yo'li ishga TUSHMADI — na xato, na navigatsiya.
    //  ⚠️  Ro'yxatning BO'SHAB qolishi KUTILGAN va TO'G'RI: fuzzy filtr
    //      yozilgan matnga mos tovar topmadi. Shu bois «Non oq ko'rinib
    //      turadi» deb tasdiqlash XATO bo'lardi — biz odam yozuvining
    //      SKAN deb qabul qilinmaganini o'lchaymiz, filtrni emas.
    expect(scanErr()).toBeNull();
    expect(opened(calls)).toEqual([]);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
//  QO'LDA KIRIM  (S1–S6)
// ═══════════════════════════════════════════════════════════════════════════

function mountRecv() {
  const calls = mockApi([
    [/\/products\?tracked=true/, []],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/receiving\/commit/, { ok: true, receiving_id: "r1", doc_no: "KIR-1" }],
  ]);
  const user = userEvent.setup();
  renderApp(<FullReceiving cats={CATS} products={ALL} suppliers={SUPS} onBack={() => {}} onSaved={() => {}} />);
  return { user, calls };
}

const nameCells = () => screen.queryAllByPlaceholderText("Mahsulot nomi") as HTMLInputElement[];
const bcCells = () => screen.queryAllByPlaceholderText(/Skanerlang|Avtomatik/) as HTMLInputElement[];
const addBtn = () => screen.getByRole("button", { name: /Mahsulot qo'shish/ });

describe("QO'LDA KIRIM — fokusdan mustaqil skan (S1–S6)", () => {
  it("S1. fokussiz tanilgan barkod → qator AVTO-TO'LDIRILADI", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    expect(nameCells()).toHaveLength(0);          // hali qator yo'q
    expect(document.activeElement).not.toBe(nameCells()[0]);
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Bitta qator paydo bo'ldi va mahsulot to'ldirildi.
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    expect(nameCells()[0].value).toBe("Non oq");
    expect(bcCells()[0].value).toBe(BC_NON);
  });

  it("S2. skaner `Enter` i YANGI BO'SH QATOR QO'SHMAYDI (asosiy nuqson)", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    //  Operator «Mahsulot qo'shish» ni BOSADI — tugma fokusda QOLADI.
    await user.click(addBtn());
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    expect(document.activeElement).toBe(addBtn());
    //  ⚠️  NUQSON SHU YERDA EDI: skanerning `Enter` i fokusdagi tugmani bosib
    //      ikkinchi BO'SH qator qo'shardi. Endi `Enter` da'vo qilinadi va
    //      tugmaga YETIB BORMAYDI.
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(nameCells()[0].value).toBe("Non oq"));
    //  AYNAN BITTA qator — ikki emas.
    expect(nameCells()).toHaveLength(1);
  });

  it("S3. barkod maydoni FOKUSDA: skan AYNAN BIR marta", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.click(addBtn());
    await waitFor(() => expect(bcCells()).toHaveLength(1));
    await user.click(bcCells()[0]);
    await user.keyboard(`${BC_SUV}{Enter}`);
    //  Qator to'ldirildi va IKKINCHI qator yaratilmadi (hook chetda turdi).
    await waitFor(() => expect(nameCells()[0].value).toBe("Suv 1L"));
    expect(nameCells()).toHaveLength(1);
  });

  it("S4. tanilmagan barkod → MAVJUD biznes qoidasi: kod qatorda QOLADI, boshqa mahsulot TANLANMAYDI", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    //  Nom BO'SH — operator yozib yangi mahsulot yaratadi (bu ekranning
    //  mavjud va ataylab saqlangan xulqi), barkod esa biriktirilgan holda turadi.
    expect(nameCells()[0].value).toBe("");
    expect(bcCells()[0].value).toBe(BC_UNKNOWN);
  });

  it("S5. QO'LDA klaviatura bilan to'ldirish AVVALGIDEK ishlaydi", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.click(addBtn());
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    await user.click(nameCells()[0]);
    await user.keyboard("Qalampir");
    expect(nameCells()[0].value).toBe("Qalampir");
    //  Qo'lda yozilgan nom skan deb yutilmadi va qator soni o'zgarmadi.
    expect(nameCells()).toHaveLength(1);
  });

  it("S6. takror skan DETERMINISTIK: AYNI qator, MIQDOR o'zgarmaydi", async () => {
    const { user } = mountRecv();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(nameCells()[0].value).toBe("Non oq"));
    //  Miqdorni operator kiritadi
    const qtyIn = screen.getAllByPlaceholderText("0").find((el) => (el as HTMLInputElement).value === "")!;
    await user.click(qtyIn);
    await user.keyboard("7");
    //  Ayni barkodni QAYTA skanerlaymiz
    (document.activeElement as HTMLElement).blur();
    await user.keyboard(`${BC_NON}{Enter}`);
    //  ⚠️  Qator SONI o'zgarmaydi va MIQDOR tegilmaydi: bu savdo emas, KIRIM
    //      hujjati — «+1» semantikasi bu yerda pul xatosi bo'lardi.
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    expect(nameCells()[0].value).toBe("Non oq");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
//  DUBLIKAT HIMOYASI — IKKI ULANGAN EKRAN (D1)
// ═══════════════════════════════════════════════════════════════════════════

describe("D1 — ikki ekran ulangan bo'lsa bitta skan BIR MARTA ishlanadi", () => {
  it("ikki `FullReceiving` instansiyasi: AYNAN BITTA qator to'ldiriladi", async () => {
    //  ⚠️  Bu `defaultPrevented` gardining tishi. Hook GLOBAL SINGLETON
    //      ishlatmaydi — har instansiya o'z tinglovchisiga ega. Ikkisi bir
    //      vaqtda ulangan bo'lsa (marshrut almashuvi, ichma-ich ko'rinish)
    //      bitta skan IKKI MARTA ishlanishi mumkin edi. Birinchi da'vo
    //      `preventDefault()` qiladi, ikkinchisi esa `e.defaultPrevented` ni
    //      ko'rib chetga chiqadi — koordinatsiya modul o'zgaruvchisida emas,
    //      HODISANING O'ZIDA.
    mockApi([
      [/\/products\?tracked=true/, []],
      [/\/products\/guess-category/, { category_id: null }],
    ]);
    const user = userEvent.setup();
    renderApp(
      <>
        <FullReceiving cats={CATS} products={ALL} suppliers={SUPS} onBack={() => {}} onSaved={() => {}} />
        <FullReceiving cats={CATS} products={ALL} suppliers={SUPS} onBack={() => {}} onSaved={() => {}} />
      </>,
    );
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Mahsulot qo'shish/ })).toHaveLength(2));
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Jami BITTA qator: ikki instansiyadan faqat biri da'vo qildi.
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    expect(nameCells()[0].value).toBe("Non oq");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
//  QAYTARISH  (R1–R4)
// ═══════════════════════════════════════════════════════════════════════════

const SALE = {
  id: "s1", receipt_no: "#1001", uid: "2610111001", method: "cash",
  sold_at: "2026-10-11T10:00:00Z", cashier: "Test", total: 7000,
  items: [
    { product_id: "p1", name: "Non oq", qty: 2, returnable: 2, unit_price: 4000, barcode: BC_NON, barcodes: [BC_NON] },
    { product_id: "p3", name: "Suv 1L", qty: 1, returnable: 1, unit_price: 3000, barcode: BC_SUV, barcodes: [BC_SUV] },
  ],
};

function mountReturns(over: [RegExp, any][] = []) {
  const calls = mockApi([
    ...over,
    [/\/sales\/find/, SALE],
    [/\/sales\?limit=8/, []],
    [/\/returns/, { ok: true, id: "ret1", total: 4000 }],
  ]);
  const user = userEvent.setup();
  renderApp(<Returns />);
  return { user, calls };
}

const rsearch = () => screen.getByPlaceholderText("Chek shtrix kodi yoki ID...") as HTMLInputElement;
const ritemScan = () => screen.getByPlaceholderText("Mahsulot barcode’ini skaner qiling...") as HTMLInputElement;

/** Chekni topish — 1-qadam. Chek shtrix-kodini skanerlash AYNI yo'l. */
async function findReceipt(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByPlaceholderText("Chek shtrix kodi yoki ID...");
  await user.click(rsearch());
  await user.keyboard("#1001{Enter}");
  await screen.findByText("Non oq");
}

describe("QAYTARISH — fokusdan mustaqil skan (R1–R4)", () => {
  it("R1. chek topilgach FOKUSSIZ skan chek QATORINI topadi", async () => {
    const { user, calls } = mountReturns();
    await findReceipt(user);
    //  Chek topilgach fokus BO'SHATILADI — 2-qadam skani maydonni bosishni
    //  talab qilmaydi.
    await waitFor(() => expect(document.activeElement).not.toBe(rsearch()));
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Qator miqdori 1 bo'ldi (`returnable` chegarasida).
    await waitFor(() => expect(screen.getByTestId("ret-qty-0").textContent).toBe("1"));
    //  SERVERGA hech narsa yozilmadi: `POST /returns` YO'Q.
    expect(calls.filter((c: Call) => c.url.includes("/returns") && c.method === "POST")).toHaveLength(0);
  });

  it("R2. tanilmagan barkod → XAVFSIZ no-match, hech narsa o'zgarmaydi", async () => {
    const { user, calls } = mountReturns();
    await findReceipt(user);
    await waitFor(() => expect(document.activeElement).not.toBe(rsearch()));
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    await waitFor(() => expect(screen.getByText(/chekda yo/i)).toBeInTheDocument());
    //  Miqdor qo'yilmadi va server chaqirilmadi.
    expect(screen.getByTestId("ret-qty-0").textContent).toBe("0");
    expect(screen.getByTestId("ret-qty-1").textContent).toBe("0");
    expect(calls.filter((c: Call) => c.url.includes("/returns") && c.method === "POST")).toHaveLength(0);
  });

  it("R3. skan maydoni FOKUSDA: AYNAN BIR marta (+1, +2 emas)", async () => {
    const { user } = mountReturns();
    await findReceipt(user);
    await user.click(ritemScan());
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Ikki yo'l o'zaro inkor: miqdor 1, 2 EMAS.
    await waitFor(() => expect(screen.getByTestId("ret-qty-0").textContent).toBe("1"));
  });

  it("R4. MAVJUD chek bo'yicha oqim buzilmaydi (chek qidirish + qo'lda miqdor)", async () => {
    const { user, calls } = mountReturns();
    await findReceipt(user);
    //  1-qadam chek qidiruvi ishladi
    expect(calls.filter((c: Call) => c.url.includes("/sales/find")).length).toBeGreaterThan(0);
    expect(screen.getByText("Non oq")).toBeInTheDocument();
    expect(screen.getByText("Suv 1L")).toBeInTheDocument();
    //  Qo'lda `+` bilan miqdor qo'yish avvalgidek
    //  Qatorda barkod bo'lgani uchun tugma «+» emas, «▮ Skanerla» — u ayni
    //  `scanCode` ni chaqiradi (mavjud xulq).
    await user.click(screen.getAllByRole("button", { name: /Skanerla/ })[0]);
    await waitFor(() => expect(screen.getByTestId("ret-qty-0").textContent).toBe("1"));
  });
});
