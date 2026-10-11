import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { useShift } from "@/store/shift";
import { CACHE, cacheSet } from "@/lib/offline";
import { ean13Checksum, SCALE_PREFIX } from "@/lib/scaleBarcode";
import { mockApi, renderApp } from "./util";

// ═══ APPARAT SKANER: FOKUSSIZ SKAN JIM YO'QOLADI ═════════════════════════════
//
// HAQIQIY APPARAT BILAN TASDIQLANGAN NUQSON. Kassir POS'ni ochadi, barkodni
// skanerlaydi — HECH NARSA bo'lmaydi. F2 bosib qidiruv maydonini fokuslagandan
// keyin AYNI skaner ishlaydi.
//
// ROOT CAUSE: bu ekranda skanerning YAGONA yo'li `pos-search` inputi edi —
// barkod buferi uning `query` state'i, terminator uning `onKeyDown` i
// (`POSKassa.onScan`). Ekran ochilganda esa hech narsa fokusda EMAS: inputda
// `autoFocus` yo'q, F-1 fokus effekti esa mount'da ATAYLAB o'tkazib yuboradi
// (`catalogFocusArmed`). Zarbalar `<body>` ga ketib yo'qolardi.
//
// ⚠️  NEGA MAVJUD F-1 TO'PLAMI BUNI TUTMAGAN. `pos-scanner-catalog.test.tsx`
//     dagi `atTill()` yordamchisi HAR testni `await user.click(search())` bilan
//     boshlaydi — ya'ni skanerning yagona yo'lini OLDINDAN fokuslaydi va
//     nuqsonni SHARTGA aylantiradi. Shu bois bu faylning yordamchisi
//     inputga ATAYLAB TEGMAYDI: fokus `<body>` da qoladi, aynan apparat
//     skanerni ushlab turgan kassirda bo'lgani kabi.
//
// ⚠️  CHEKLOV. USB HID skanerni jsdom'da ifodalash imkoni yo'q. Eng tor DOM
//     ekvivalenti: `user.keyboard(...)` hodisalarni `document.activeElement` ga
//     yuboradi va hech bir elementni nishonga olmaydi. `addByScan()`
//     TO'G'RIDAN chaqirilmaydi — nuqson aynan hodisa yo'naltirishida.

const BC_NON = "4780001234567";
const BC_SUV = "4780009999999";
const BC_UNKNOWN = "4779999999999";          // katalogda YO'Q
//  EGANING HAQIQIY APPARAT SKANERIDAN kelgan kod (2026-10-11). Yaroqli
//  EAN-13 (nazorat raqami repo kutubxonasi bilan tekshirilgan) va tarozi
//  etiketkasi EMAS (prefiks `47`), ya'ni ODDIY barkod yo'li.
const BC_REAL = "4700040115745";

//  Tarozi etiketkalari repo'ning O'Z kutubxonasi bilan quriladi (qo'lda
//  yozilgan nazorat raqami testni jim yolg'onchi qilardi).
const scaleCode = (plu: string, grams: string) => {
  const body = SCALE_PREFIX + plu + grams;   // 2 + 5 + 5 = 12
  return body + String(ean13Checksum(body));
};
const SCALE_POMIDOR = scaleCode("00537", "00500");   // p2, 0.500 kg
const SCALE_NO_PLU = scaleCode("99999", "00500");    // bunday PLU YO'Q

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona", barcodes: [BC_NON] },
  { id: "p2", article_code: "A-2", name: "Pomidor", category_id: null, base_sell_price: 12000, stock: 50, unit_code: "kg", is_weighted: true, plu_code: "537", barcodes: [] },
  { id: "p3", article_code: "A-3", name: "Suv 1L", category_id: null, base_sell_price: 3000, stock: 80, unit_code: "dona", barcodes: [BC_SUV] },
  { id: "p4", article_code: "A-4", name: "Choy", category_id: null, base_sell_price: 15000, stock: 20, unit_code: "dona", barcodes: [BC_REAL] },
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
const isEditable = (el: Element | null) =>
  !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)
           || (el as HTMLElement).isContentEditable === true);

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

/**
 * Kassir ekranni ochadi va SICHQONCHAGA TEGMAYDI — qo'lida faqat skaner.
 * Fokus `<body>` da: aynan shu holat haqiqiy apparatda yiqilgan.
 */
async function atTillNoFocus() {
  mockApi(routes());
  const user = userEvent.setup();
  renderApp(<POSKassa />);
  await screen.findByTestId("pos-search");
  //  Oldindan fokus BERILMAYDI — bu testlarning butun mohiyati.
  expect(document.activeElement).not.toBe(search());
  return user;
}

describe("Apparat skaner — fokusdan mustaqil yo'l (A–I)", () => {
  it("A. normal POS, hech narsa fokusda emas: tanilgan barkod → savat +1", async () => {
    const user = await atTillNoFocus();
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
    //  F2 BOSILMADI — qabul mezonining o'zi.
    expect(document.activeElement).not.toBe(search());
  });

  it("A2. HAQIQIY apparat kodi (4700040115745) fokussiz savatga tushadi", async () => {
    const user = await atTillNoFocus();
    //  Ega bu kodni o'z skaneri bilan yuborgan: raqamlar + Enter.
    await user.keyboard(`${BC_REAL}{Enter}`);
    await waitFor(() => expect(line("p4")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("B. ayni barkod yana: miqdor +1, dublikat hodisa EMAS", async () => {
    const user = await atTillNoFocus();
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(2));
    //  Uchinchi emas, AYNAN ikki: bitta skan = bitta amal
    expect(lines()).toHaveLength(1);
    //  Boshqa barkod alohida qator ochadi, mavjudini buzmaydi
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(line("p3")?.qty).toBe(1));
    expect(line("p1")?.qty).toBe(2);
  });

  it("C. F2 ochiq (input fokusda): skan AYNAN BIR marta qo'shiladi", async () => {
    const user = await atTillNoFocus();
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Ikki yo'l (input `onScan` + global tinglovchi) FOKUS bo'yicha o'zaro
    //  inkor — aks holda bu yerda 2 bo'lardi.
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
    expect(search().value).toBe("");
  });

  it("C2. F2 QO'LDA qidiruv bo'lib QOLADI (tahrirlanadigan-fokus gardining tishi)", async () => {
    const user = await atTillNoFocus();
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    //  ⚠️  BU TEST GARDNI O'LDIRADI. Agar `isEditableTarget` tekshiruvi
    //      POSKassa'dan olib tashlansa, global yo'l «Choy» ni DA'VO qilib
    //      `addByScan(term, false)` chaqiradi — `allowNameFallback=false`,
    //      ya'ni nom bo'yicha HECH NARSA qo'shilmaydi va bu test YIQILADI.
    //      Shu bois C2 aynan ikki yo'lning FOKUS bo'yicha ajralishini
    //      isbotlaydi (test C bu ajralishni isbotlay OLMAYDI: `stopPropagation`
    //      tufayli gard bo'lmasa ham natija «bir marta» bo'lib qoladi).
    await user.keyboard("Choy{Enter}");
    await waitFor(() => expect(line("p4")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("D. F2 yopilgach (fokus ketgach) normal skan DARHOL ishlaydi", async () => {
    const user = await atTillNoFocus();
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    (document.activeElement as HTMLElement).blur();
    await waitFor(() => expect(document.activeElement).not.toBe(search()));
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(line("p3")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("E. tanilmagan barkod: savat MUTLAQO qimirlamaydi (shown[0] zaxirasi YO'Q)", async () => {
    const user = await atTillNoFocus();
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    //  Sabab KO'RINADI (fail-loud), lekin savat BO'SH qoladi.
    expect(await screen.findByText(/topilmadi/i)).toBeInTheDocument();
    expect(lines()).toHaveLength(0);
    //  Takror skan ham mutatsiya bermaydi
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    expect(lines()).toHaveLength(0);
  });

  it("E2. F2 FOKUSDA tanilmagan barkod: `shown[0]` poygasi savatni buzmaydi", async () => {
    const user = await atTillNoFocus();
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    //  ⚠️  Bu ENG XAVFLI holat edi. `shown` KECHIKTIRILGAN `deferredQuery` dan
    //      hisoblanadi, `onScan` esa JONLI `query` ni o'qiydi: tez skanda
    //      `shown` hali OLDINGI (bo'sh) so'rov natijasi — BUTUN katalog — va
    //      `exact || shown[0]` zaxirasi kassir bexabar BOSHQA mahsulotni
    //      1 dona qilib sotib yuborardi.
    await user.keyboard(`${BC_UNKNOWN}{Enter}`);
    expect(lines()).toHaveLength(0);
  });

  it("F. to'lov oynasidagi odam yozuvi skaner deb QABUL QILINMAYDI", async () => {
    const user = await atTillNoFocus();
    const one: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" } as CartLine;
    useCart.setState({ carts: [[one]], active: 0, items: [one] });
    await user.click(await screen.findByTestId("pay-go"));
    await user.click(await screen.findByRole("button", { name: "Naqd", exact: true }));
    const amount = screen.getAllByPlaceholderText("0")[0] as HTMLInputElement;
    await user.click(amount);
    //  Barkodga O'XSHAGAN raqamlar + Enter — bu ODAM yozayotgan summa.
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Savat o'zgarmadi: raqamlar global skaner yo'liga SIZIB O'TMADI.
    expect(lines()).toHaveLength(1);
    expect(line("p1")?.qty).toBe(1);
  });

  it("G. fokus HAQIQATAN tugmada: skan ishlaydi va Enter tugmani BOSMAYDI", async () => {
    const user = await atTillNoFocus();
    //  ⚠️  Katalogni OCHMAYMIZ. Ilgari bu test katalogni ochardi va shu bois
    //      TUZATISHSIZ HAM o'tardi: F-1 effekti katalog holati o'zgarganda
    //      fokusni `pos-search` ga qaytaradi, ya'ni skan eski input yo'lidan
    //      o'tib ketardi va «tugmada fokus» holati UMUMAN sinalmasdi.
    //      Endi tugma TO'G'RIDAN fokuslanadi — F-1 effekti ishga tushmaydi.
    const btn = screen.getByTestId("open-catalog") as HTMLButtonElement;
    btn.focus();
    expect(document.activeElement).toBe(btn);
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    //  Skanerning `Enter` i fokusdagi tugmani BOSMADI — katalog OCHILMADI.
    expect(screen.queryByTestId("catalog-overlay")).toBeNull();
  });

  it("G2. bufer QISQA bo'lsa Enter tugmani AVVALGIDEK bosadi (a11y buzilmaydi)", async () => {
    const user = await atTillNoFocus();
    const btn = screen.getByTestId("open-catalog") as HTMLButtonElement;
    btn.focus();
    //  Ikki belgi — `WEDGE_MIN_LEN` (4) dan past: skan DA'VO QILINMAYDI va
    //  `Enter` o'z standart ishini bajaradi (klaviatura bilan boshqarish).
    await user.keyboard("12{Enter}");
    expect(await screen.findByTestId("catalog-overlay")).toBeInTheDocument();
    expect(lines()).toHaveLength(0);
  });

  it("H. Escape/F2/F4/F6/F7 yorliqlari BUZILMAYDI", async () => {
    const user = await atTillNoFocus();
    //  F2 — qidiruvni fokuslaydi (bufer da'vo qilinmagani uchun o'tadi)
    await user.keyboard("{F2}");
    await waitFor(() => expect(document.activeElement).toBe(search()));
    (document.activeElement as HTMLElement).blur();
    //  Escape — katalogni yopadi
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("catalog-overlay")).toBeNull());
    //  F6 — yangi savat; F7 — keyingi savatga o'tish
    const one: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" } as CartLine;
    useCart.setState({ carts: [[one]], active: 0, items: [one] });
    await user.keyboard("{F6}");
    await waitFor(() => expect(useCart.getState().carts.length).toBe(2));
    await user.keyboard("{F7}");
    await waitFor(() => expect(useCart.getState().active).toBe(0));
    //  F4 — to'lov oynasi (savat bo'sh bo'lmasa)
    await user.keyboard("{F4}");
    expect(await screen.findByText(/TO‘LOV SUMMASI/i)).toBeInTheDocument();
  });

  it("H3. Escape/F6/F7 yorliqlari FOKUSSIZ ham ishlaydi (holat shartlangan)", async () => {
    const user = await atTillNoFocus();
    //  ⚠️  Oldingi H testi yorliqlarni bosardi, lekin FOKUS holatini
    //      SHARTLAMAGAN edi — ya'ni «fokussiz» da'vosi o'lchanmagan edi.
    const one: CartLine = { id: "p1", name: "Non oq", price: 4000, qty: 1, article: "A-1" } as CartLine;
    useCart.setState({ carts: [[one]], active: 0, items: [one] });
    expect(isEditable(document.activeElement)).toBe(false);
    await user.keyboard("{F6}");
    await waitFor(() => expect(useCart.getState().carts.length).toBe(2));
    expect(isEditable(document.activeElement)).toBe(false);
    await user.keyboard("{F7}");
    await waitFor(() => expect(useCart.getState().active).toBe(0));
  });

  it("H4. vazn (kg) dialogi ochiq: skan savatni QIMIRLATMAYDI", async () => {
    const user = await atTillNoFocus();
    await user.click(screen.getByTestId("open-catalog"));
    await screen.findByTestId("catalog-overlay");
    await user.click(await screen.findByRole("button", { name: /Pomidor/ }));
    const kg = await screen.findByPlaceholderText("0.000 kg");
    await waitFor(() => expect(document.activeElement).toBe(kg));
    //  Fokusni dialogdan OLAMIZ — shunda faqat `weighRef` gardi qoladi.
    (document.activeElement as HTMLElement).blur();
    await user.keyboard(`${BC_NON}{Enter}`);
    //  Savat BO'SH: vazn so'ralayotganda skan boshqa mahsulot qo'shmaydi.
    expect(lines()).toHaveLength(0);
    //  Dialog ham o'z mahsulotida qoladi
    expect(screen.queryByPlaceholderText("0.000 kg")).not.toBeNull();
  });

  it("H2. `+`/`-` miqdor yorliqlari fokussiz AVVALGIDEK ishlaydi", async () => {
    const user = await atTillNoFocus();
    //  Avval skan bilan qator qo'shamiz (fokussiz) — keyin yorliq bilan miqdor.
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    //  ⚠️  `+` va `-` ATAYLAB wedge buferidan TASHQARIDA: ular POS'ning global
    //      yorliqlari va ularni barkod belgisi deb yig'ish kassirning klaviatura
    //      boshqaruvini o'g'irlardi (`scanWedge.BARCODE_CHAR`).
    await user.keyboard("+");
    await waitFor(() => expect(line("p1")?.qty).toBe(2));
    await user.keyboard("-");
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    //  Yorliqlar bufer qoldirmadi: keyingi skan toza ishlaydi
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(line("p3")?.qty).toBe(1));
  });

  it("K. StrictMode (DEV yig'ma): input mount'da FOKUSLANADI — prod'da esa YO'Q", async () => {
    //  ⚠️  NUQSON NEGA YETIB KELGANINING SABABI. `apps/pos/src/main.tsx` ilovani
    //      `React.StrictMode` ga o'raydi: DEV'da effektlar mount -> unmount ->
    //      mount bo'ladi. `catalogFocusArmed` REF esa qayta mount'da SAQLANADI,
    //      shu bois IKKINCHI yurishda u allaqachon `true` va F-1 effekti
    //      `searchRef.focus()` ni CHAQIRADI. Ya'ni `npm run dev` da skaner
    //      ishlaydi (input fokusda), PAKETLANGAN .exe da esa StrictMode YO'Q,
    //      effekt bir marta yuradi, fokus hech kimda qolmaydi va skan JIM
    //      yo'qoladi. Dev bilan prod AJRALGANI uchun nuqson ko'rinmagan.
    mockApi(routes());
    const user = userEvent.setup();
    renderApp(<StrictMode><POSKassa /></StrictMode>);
    await screen.findByTestId("pos-search");
    //  O'LCHOV (hukm emas): dev'da fokus inputda bo'ladi.
    expect(document.activeElement).toBe(search());
    await user.keyboard(`${BC_NON}{Enter}`);
    //  AYNAN 1 — StrictMode ikki tinglovchi qoldirmaganining isboti
    //  (tozalash to'liq bo'lmasa HAR SKAN ikki marta qo'shilardi).
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("K2. StrictMode + fokus olingan: GLOBAL yo'l ham aynan bir marta", async () => {
    mockApi(routes());
    const user = userEvent.setup();
    renderApp(<StrictMode><POSKassa /></StrictMode>);
    await screen.findByTestId("pos-search");
    (document.activeElement as HTMLElement)?.blur();
    await waitFor(() => expect(document.activeElement).not.toBe(search()));
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(lines()).toHaveLength(1);
  });

  it("I. tarozi etiketkasi regressiyalari SAQLANADI (fokussiz ham)", async () => {
    const user = await atTillNoFocus();
    //  Yaroqli etiketka → vaznli mahsulot savatga AYNAN vazn bilan tushadi
    await user.keyboard(`${SCALE_POMIDOR}{Enter}`);
    await waitFor(() => expect(line("p2")?.qty).toBe(0.5));
    expect(line("p2")?.weighted).toBe(true);
    //  PLU mos kelmasa — savat QIMIRLAMAYDI va sabab ko'rinadi
    const oldLen = lines().length;
    await user.keyboard(`${SCALE_NO_PLU}{Enter}`);
    expect(await screen.findByText(/PLU/i)).toBeInTheDocument();
    expect(lines()).toHaveLength(oldLen);
  });
});
