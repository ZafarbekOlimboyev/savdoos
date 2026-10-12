import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { useAuth } from "@/store/auth";
import { useCart, type CartLine } from "@/store/cart";
import { useShift } from "@/store/shift";
import { CACHE, cacheSet } from "@/lib/offline";
import { ean13Checksum, SCALE_PREFIX } from "@/lib/scaleBarcode";
import { mockApi, renderApp } from "./util";

// ═══ POS VAZN (kg) DIALOGI — SKANER XAVFSIZLIGI ══════════════════════════════
//
// XAVF (read-only auditda o'lchangan). `POSKassa.tsx:1242` vazn inputida
// `autoFocus` bor, `onChange` esa `[0-9.,]` ni QABUL QILADI, va `:1244`
// `Enter -> addWeighed()`. Klaviatura-wedge skaner raqamlarni yozib `Enter`
// yuboradi, ya'ni skanerlangan barkod VAZN bo'lib savatga tushadi.
// O'lchandi: `kgOf("4700000160204")` = 4700000160204 — `decRound` TASHLAMAYDI,
// ya'ni izohdagi "juda katta son" gardi bu qiymatlarga ishlamaydi.
//
// ⚠️  UMUMIY SKANER YO'LI BU YERDA AYBDOR EMAS va yordam ham bermaydi:
//     `useBarcodeScanner` ikki marta chetga chiqadi — `enabled: !weigh && !modal`
//     (dialog ochiq) va `isEditableTarget` (input fokusda) — va `preventDefault`
//     QILMAYDI. Zarbalar nativ yo'l bilan inputga boradi. Bu AYNAN
//     `NewSupplierCard` bilan bir sinf (`9bcdb97`).
//
// ⚠️  TAROZI INTEGRATSIYASI BUZILMAYDI. Repo'dagi tarozi yo'li — serverdagi
//     `ScaleDriver` (`services/scales/base.py`: faqat `probe` va
//     `sync_products`, jonli vazn API'si YO'Q) PLU ni tarozi qurilmasiga
//     yuboradi, tarozi esa ETIKETKA chop etadi; POS uni skanerlab
//     `parseScaleBarcode` -> `cart.add(qty = grams/1000)` qiladi
//     (`POSKassa.tsx:605-612`) va vazn dialogi UMUMAN ochilmaydi. W4 shuni
//     qulflaydi.

const BC_NON = "4780001234567";          // oddiy tovar
const BC_REAL = "4700000160204";         // eganing HAQIQIY skanerdan kodi
const PLU = "537";

const scaleCode = (plu5: string, grams5: string) => {
  const body = SCALE_PREFIX + plu5 + grams5;
  return body + String(ean13Checksum(body));
};
const SCALE_500G = scaleCode("00537", "00500");   // 0.500 kg

const PRODUCTS = [
  { id: "p1", article_code: "A-1", name: "Non oq", category_id: null, base_sell_price: 4000, stock: 100, unit_code: "dona", barcodes: [BC_NON] },
  { id: "p2", article_code: "A-2", name: "Pomidor", category_id: null, base_sell_price: 12000, stock: 50, unit_code: "kg", is_weighted: true, plu_code: PLU, barcodes: [] },
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

const lines = () => useCart.getState().items;
const line = (id: string) => lines().find((i: CartLine) => i.id === id);
const kgInput = () => screen.getByPlaceholderText(/kg/) as HTMLInputElement;
//  ⚠️  Apostrof EGRI (`Qo‘shish`, U+2018) — `/Qo'shish/` MOS KELMAYDI.
//      Shu bois har qanday apostrof uchun `.` ishlatiladi.
const addBtn = () => screen.getByRole("button", { name: /Qo.shish|Добавить/ });

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
afterEach(() => cleanup());

/** Kassir ekranni ochadi — SICHQONCHAGA tegmaydi (apparat skaner holati). */
async function atTill() {
  mockApi(routes());
  const user = userEvent.setup();
  renderApp(<POSKassa />);
  await screen.findByTestId("pos-search");
  return user;
}

/** Vaznli tovarni katalogdan bosib vazn dialogini ochadi (haqiqiy yo'l). */
async function openWeigh(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("open-catalog"));
  await screen.findByTestId("catalog-overlay");
  await user.click(await screen.findByRole("button", { name: /Pomidor/ }));
  const kg = await screen.findByPlaceholderText(/kg/);
  //  `autoFocus` — operator turgan HAQIQIY holat. TEGILMAYDI.
  await waitFor(() => expect(document.activeElement).toBe(kg));
}

describe("W — vazn dialogi: skaner savatga NOTO'G'RI miqdor qo'shmaydi", () => {
  it("W1. barkod + Enter -> savat BO'SH qoladi (fokus TEGILMAGAN)", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard(`${BC_REAL}{Enter}`);
    await new Promise((r) => setTimeout(r, 40));
    //  ASOSIY TASDIQ: hech narsa qo'shilmadi.
    expect(lines()).toHaveLength(0);
    //  Dialog JOYIDA — operator xato qiymatni ko'radi va tuzatadi.
    expect(screen.getByPlaceholderText(/kg/)).toBeInTheDocument();
  });

  it("W1b. qisqa barkod (8 xona) ham qo'shilmaydi", async () => {
    //  ⚠️  Server `SaleItemIn.qty` ni `le=1e9` bilan cheklaydi
    //      (`apps/server/app/schemas/sales.py:11`), ya'ni 13 xonali kod
    //      serverda RAD etilardi. 8 xonali kod esa `1e9` dan KICHIK —
    //      server qabul qilardi. Shu bois gard CHEGARADA: 47 000 016 kg
    //      `MAX_LINE_WEIGHT_KG` (99.999) dan katta.
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("47000016{Enter}");
    await new Promise((r) => setTimeout(r, 40));
    expect(lines()).toHaveLength(0);
  });

  it("W2. QO'LDA vazn kiritish va TASDIQLASH ishlaydi", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("0.500");
    expect(kgInput().value).toBe("0.500");
    //  ⚠️  ENTER bilan tasdiqlash SAQLANADI (ega qarori) — `pos-print.test.tsx`
    //      dagi yaxlitlash pariteti testlari ham aynan shu yo'lni ishlatadi.
    await user.keyboard("{Enter}");
    //  Tasdiqlash tugmasi bilan savatga AYNAN kiritilgan vazn tushadi.
    await waitFor(() => expect(line("p2")?.qty).toBe(0.5));
    expect(line("p2")?.weighted).toBe(true);
    //  Dialog yopildi.
    await waitFor(() => expect(screen.queryByPlaceholderText(/kg/)).toBeNull());
  });

  it("W2b. vergul bilan kiritilgan vazn ham ishlaydi (mavjud xulq)", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("1,25");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(line("p2")?.qty).toBe(1.25));
  });

  it("W3. validatsiyadan o'tmagan qiymat savatga QO'SHILMAYDI", async () => {
    const user = await atTill();
    await openWeigh(user);
    //  `kgOf("0")` = 0 -> `addWeighed` `if (kg <= 0) return` bilan to'xtaydi
    //  va tugma `disabled` bo'ladi.
    await user.keyboard("0");
    expect((addBtn() as HTMLButtonElement).disabled).toBe(true);
    await user.keyboard("{Enter}");
    await new Promise((r) => setTimeout(r, 30));
    expect(lines()).toHaveLength(0);
  });

  it("W4. ODDIY POS skanerlashi BUZILMAYDI (dialog umuman ochilmaydi)", async () => {
    const user = await atTill();
    //  (a) oddiy tovar barkodi -> to'g'ridan savatga
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    //  (b) TAROZI ETIKETKASI -> `parseScaleBarcode` yo'li, vazn dialogi YO'Q
    await user.keyboard(`${SCALE_500G}{Enter}`);
    await waitFor(() => expect(line("p2")?.qty).toBe(0.5));
    expect(screen.queryByPlaceholderText(/kg/)).toBeNull();
    expect(line("p2")?.weighted).toBe(true);
  });

  it("W6. CHEGARA: 99.999 kg QABUL qilinadi (aynan chegarada)", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("99.999{Enter}");
    //  Chegara INKLYUZIV — `MAX_LINE_WEIGHT_KG` ning o'zi o'tadi.
    await waitFor(() => expect(line("p2")?.qty).toBe(99.999));
  });

  it("W6b. CHEGARA: 100 kg RAD etiladi va sabab KO'RINADI", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("100");
    //  Xabar DARHOL ko'rinadi (operator Enter bosishini kutmaymiz).
    expect(await screen.findByTestId("weigh-too-big")).toBeInTheDocument();
    await user.keyboard("{Enter}");
    await new Promise((r) => setTimeout(r, 30));
    expect(lines()).toHaveLength(0);
  });

  it("W6c. Enter va «Qo‘shish» tugmasi AYNI validatsiyadan o'tadi", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("100");
    //  Tugma ham yopiq — ya'ni ikki yo'l bir xil qoidaga bo'ysunadi.
    expect((addBtn() as HTMLButtonElement).disabled).toBe(true);
    await user.click(addBtn());
    await new Promise((r) => setTimeout(r, 30));
    expect(lines()).toHaveLength(0);
    //  Chegaraga tushirilsa IKKISI ham ochiladi.
    await user.clear(kgInput());
    await user.keyboard("2.5");
    expect((addBtn() as HTMLButtonElement).disabled).toBe(false);
    await user.click(addBtn());
    await waitFor(() => expect(line("p2")?.qty).toBe(2.5));
  });

  it("W5. Escape dialogni yopadi (mavjud xulq saqlanadi)", async () => {
    const user = await atTill();
    await openWeigh(user);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByPlaceholderText(/kg/)).toBeNull());
    expect(lines()).toHaveLength(0);
  });
});
