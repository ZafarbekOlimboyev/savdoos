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

// ═══ SAVAT MIQDORI (CartQty) — SKANER XAVFSIZLIGI ════════════════════════════
//
// XAVF (read-only auditda O'LCHANGAN). Donali qatorning miqdor inputi
// (`POSKassa.tsx` `CartQty`) raqamlarni qabul qiladi (`onChange` faqat
// `[^0-9]` ni olib tashlaydi), `Enter` esa `blur()` qiladi va `onBlur`
// `commit()` ni chaqiradi. Klaviatura-wedge skaner barkodni shu maydonga
// yozib, oxirgi `Enter` i bilan uni TASDIQLAB qo'yardi. `commit()` esa
// qiymatni JIMGINA qisqartirardi:
//     parseInt("4780001234567") = 4 780 001 234 567  ->  Math.min(..., 99999)
// Zond bilan o'lchangan natija: qty = 99999, input «99999» ko'rsatadi.
//
// ⚠️  JIM QISQARTIRISH ENG XAVFLI QISMI: 99 999 XATO TERISH kabi ko'rinadi,
//     4.7e12 esa darhol ko'zga tashlanadi.
//
// ⚠️  OFLAYN YO'L SERVER GARDINI CHETLAB O'TADI (manbada tekshirilgan).
//     `app/services/sales.py:584` qoldiq gardi `and not honor_price_snapshot` bilan
//     yozilgan (QA WH-007 — oflayn chek HECH QACHON rad etilmaydi, tovar jismonan
//     chiqqan), `honor_price_snapshot=True` esa FAQAT `/sync/push` dan keladi
//     (`app/api/v1/sync.py:90`; shartnoma `services/sales.py:124`). Ya'ni oflayn
//     yaratilgan 99 999 donali qator flush'da YOZILADI va qoldiqni manfiyga tushiradi.
//
// ⚠️  CHEGARA O'ZGARMAYDI: 99 999 AVVALGIDEK eng katta ruxsat etilgan miqdor.
//     Yagona o'zgarish — undan katta qiymat JIM QISQARTIRILMAYDI, balki RAD
//     etiladi va savat miqdori O'ZGARMAY qoladi.

const BC_NON = "4780001234567";          // 13 xonali
const BC_SHORT = "47000016";             // 8 xonali
const PLU = "537";
const scaleCode = (plu5: string, grams5: string) => {
  const body = SCALE_PREFIX + plu5 + grams5;
  return body + String(ean13Checksum(body));
};
const SCALE_500G = scaleCode("00537", "00500");

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
const qtyBox = (id: string) => document.querySelector(`[data-qty-for="${id}"]`) as HTMLInputElement | null;

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

async function atTill() {
  mockApi(routes());
  const user = userEvent.setup();
  renderApp(<POSKassa />);
  await screen.findByTestId("pos-search");
  return user;
}

/** Donali tovarni savatga qo'yib, miqdor inputini HAQIQATAN fokuslaydi. */
async function focusedQty(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard(`${BC_NON}{Enter}`);
  await waitFor(() => expect(line("p1")?.qty).toBe(1));
  const box = qtyBox("p1")!;
  expect(box).toBeTruthy();
  await user.click(box);
  //  `onFocus` mavjud matnni TANLAYDI — ya'ni yozilgan raqam uni almashtiradi.
  expect(document.activeElement).toBe(box);
  return box;
}

describe("C — CartQty: skaner miqdorni JIM o'zgartirmaydi", () => {
  it("C1. 13 xonali barkod + Enter → miqdor O'ZGARMAYDI, sabab KO'RINADI", async () => {
    const user = await atTill();
    const box = await focusedQty(user);
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 40));
    //  ASOSIY TASDIQ: oldingi miqdor saqlanadi (99999 BO'LMAYDI).
    expect(line("p1")?.qty).toBe(1);
    expect(box.value).toBe("1");
    //  Sabab ko'rinadi (POS ekranidagi mavjud xato sirti).
    expect(await screen.findByText(/99\s?999/)).toBeInTheDocument();
  });

  it("C2. 8 xonali barkod + Enter → ayni natija", async () => {
    const user = await atTill();
    const box = await focusedQty(user);
    await user.keyboard(`${BC_SHORT}{Enter}`);
    await new Promise((r) => setTimeout(r, 40));
    expect(line("p1")?.qty).toBe(1);
    expect(box.value).toBe("1");
  });

  it("C3. QO'LDA 5 → QABUL qilinadi", async () => {
    const user = await atTill();
    await focusedQty(user);
    await user.keyboard("5{Enter}");
    await waitFor(() => expect(line("p1")?.qty).toBe(5));
  });

  it("C4. QO'LDA 99999 → QABUL qilinadi (chegara O'ZGARMADI, inklyuziv)", async () => {
    const user = await atTill();
    await focusedQty(user);
    await user.keyboard("99999{Enter}");
    await waitFor(() => expect(line("p1")?.qty).toBe(99999));
  });

  it("C5. QO'LDA 100000 → RAD, miqdor O'ZGARMAYDI", async () => {
    const user = await atTill();
    await focusedQty(user);
    await user.keyboard("100000{Enter}");
    await new Promise((r) => setTimeout(r, 40));
    expect(line("p1")?.qty).toBe(1);
    expect(await screen.findByText(/99\s?999/)).toBeInTheDocument();
  });

  it("C6. NOL va BO'SH kirish — mavjud xulq saqlanadi", async () => {
    const user = await atTill();
    const box = await focusedQty(user);
    //  `0` → `n > 0` sharti sababi o'zgarishsiz qoldiriladi va tiklanadi.
    await user.keyboard("0{Enter}");
    await new Promise((r) => setTimeout(r, 30));
    expect(line("p1")?.qty).toBe(1);
    expect(box.value).toBe("1");
    //  BO'SH ham ayni xulq.
    await user.click(box);
    await user.clear(box);
    await user.keyboard("{Enter}");
    await new Promise((r) => setTimeout(r, 30));
    expect(line("p1")?.qty).toBe(1);
  });

  it("C7. ± tugmalari O'ZGARMAGAN", async () => {
    const user = await atTill();
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    const row = qtyBox("p1")!.parentElement!;
    const btns = row.querySelectorAll("button");
    await user.click(btns[1]);                      // +
    await waitFor(() => expect(line("p1")?.qty).toBe(2));
    await user.click(btns[0]);                      // −
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
  });

  it("C8. VAZNLI qatorda tahrirlanadigan CartQty YO'Q", async () => {
    const user = await atTill();
    //  Tarozi etiketkasi → vaznli qator (vazn dialogi ochilmaydi).
    await user.keyboard(`${SCALE_500G}{Enter}`);
    await waitFor(() => expect(line("p2")?.qty).toBe(0.5));
    //  Vaznli qator FAQAT O'QISH uchun — miqdor inputi umuman yo'q.
    expect(qtyBox("p2")).toBeNull();
    //  Donali qatorda esa bor (fix u yerga oqib ketmagan).
    await user.keyboard(`${BC_NON}{Enter}`);
    await waitFor(() => expect(line("p1")?.qty).toBe(1));
    expect(qtyBox("p1")).toBeTruthy();
  });
});
