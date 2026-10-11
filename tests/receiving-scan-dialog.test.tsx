import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullReceiving, type Product } from "@/screens/Products";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp } from "./util";

// ═══ QO'LDA KIRIM: SKANER DIALOG ORTIDA ISHLAMASIN ═══════════════════════════
//
// NUQSON (adversarial ko'rikda topilgan, `8a06daa` kiritgan). `Products.tsx:929`
// dagi `useBarcodeScanner` chaqiruvida `enabled` YO'Q edi, ya'ni hook
// `NewSupplierCard` modali (`Products.tsx:1158`, `ui.tsx` `Modal` — fokus
// tuzog'i ham, Escape ham YO'Q) ochiq bo'lganda ham TIRIK qolardi. Faqat
// tasodifan niqoblangan: kartaning nom inputida `autoFocus` bor, shu bois
// `isEditableTarget` chetga chiqardi. Fokus Bekor/Saqlash TUGMASIGA o'tishi
// bilan skan dialog ORTIDA kirim qatorlarini o'zgartirardi.
//
// ⚠️  `LotReceivingEditor` BU RO'YXATGA KIRMAYDI va ataylab. U modal emas —
//     qator ICHIDAGI inline muharrir (`Products.tsx:1106`), partiyali har
//     qatorda ko'rinadi. Uni to'sish har qanday partiyali hujjatda skanni
//     o'chirardi. Uning inputlarida yozilganda esa mavjud tahrirlanadigan-fokus
//     gardi allaqachon ishlaydi. S3c shuni qulflaydi.

const BC_NON = "4780001234567";
const BC_SUV = "4780009999999";

const prod = (over: Partial<Product>): Product => ({
  id: "p0", article_code: "A-0", sku: "0", name: "Tovar", category_id: "c1",
  base_buy_price: 7000, base_sell_price: 12000, stock: 0, min_stock: 0, unit_code: "dona",
  expiry_date: null, barcodes: [], track_lots: false, track_expiry: false, ...over,
});
const NON = prod({ id: "p1", name: "Non oq", barcodes: [BC_NON] });
const SUV = prod({ id: "p3", name: "Suv 1L", barcodes: [BC_SUV] });
const FIFO = prod({ id: "p9", name: "Sut 1L", track_lots: true, barcodes: ["4780012340015"] });
const CATS = [{ id: "c1", name: "Ichimliklar" }];
const SUPS = [{ id: "s1", name: "Ta'minotchi" }];

const nameCells = () => screen.queryAllByPlaceholderText("Mahsulot nomi") as HTMLInputElement[];
const addBtn = () => screen.getByRole("button", { name: /Mahsulot qo'shish/ });

function mount(products: Product[] = [NON, SUV]) {
  const calls = mockApi([
    [/\/products\?tracked=true/, products.filter((p) => p.track_lots)],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/lots\/products\//, { business_date: "2026-10-12", track_lots: true, track_expiry: false, lots: [] }],
    [/\/suppliers/, SUPS],
  ]);
  const user = userEvent.setup();
  renderApp(<FullReceiving cats={CATS} products={products} suppliers={SUPS}
                           onBack={() => {}} onSaved={() => {}} />);
  return { user, calls };
}

/** Yangi ta'minotchi modalini ochadi (haqiqiy yo'l: select → «__new__»). */
async function openSupplierDialog(user: ReturnType<typeof userEvent.setup>) {
  const sel = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
  await user.selectOptions(sel, "__new__");
  await waitFor(() => expect(screen.getByPlaceholderText("Nomi")).toBeInTheDocument());
}

//  ⚠️  AVTOMATIK `cleanup` YO'Q. Bo'lmasa oldingi testning DOM'i qolib ketadi va
//      `getAllByRole("combobox")[0]` ESKI renderning select'ini oladi — natijada
//      dialog umuman ochilmaydi va test O'Z selektori sababli yiqiladi
//      (o'lchangan: S3b yolg'iz o'tib, faylda yiqilardi).
afterEach(() => cleanup());

beforeEach(() => {
  localStorage.clear();
  useAuth.setState({
    token: "t",
    employee: { id: "e1", full_name: "Test", permissions: ["ombor.view", "ombor.edit", "xaridlar.edit"] } as any,
  });
  vi.restoreAllMocks();
});

describe("S3 — skaner yangi-ta'minotchi dialogi ORTIDA ishlamaydi", () => {
  it("S3a. dialog ochiq va fokus TUGMADA: skan kirim qatorlarini O'ZGARTIRMAYDI", async () => {
    const { user } = mount();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await openSupplierDialog(user);
    //  Fokus kartaning nom inputida (`autoFocus`) — uni OLAMIZ. Aynan shu holat
    //  nuqsonni ochadi: `isEditableTarget` endi false, ya'ni `enabled` dan
    //  BOSHQA hech narsa skanni to'smaydi.
    //  ⚠️  Fokus TUGMAGA qo'yilmaydi: `enabled:false` da hook `Enter` ni DA'VO
    //      QILMAYDI (to'g'ri a11y), shu bois fokusdagi tugma BOSILADI va dialog
    //      yopilib ketardi — test o'z mexanizmi bilan o'zini buzardi (o'lchangan).
    (document.activeElement as HTMLElement | null)?.blur?.();
    await waitFor(() => expect(document.activeElement).toBe(document.body));
    await user.keyboard(`${BC_NON}{Enter}`);
    await new Promise((r) => setTimeout(r, 40));
    //  Dialog ortida HECH QANDAY qator yaratilmadi/to'ldirilmadi.
    expect(nameCells()).toHaveLength(0);
    //  Dialog ham joyida qoladi (skanerning `Enter` i uni yopmadi).
    expect(screen.getByPlaceholderText("Nomi")).toBeInTheDocument();
  });

  it("S3b. dialog YOPILGACH skan DARHOL yana ishlaydi (doimiy o'chirib qo'yilmaydi)", async () => {
    const { user } = mount();
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await openSupplierDialog(user);
    const bekor = screen.getAllByRole("button").find((b) => /Bekor|Отмена|bekor/i.test(b.textContent || ""))!;
    await user.click(bekor);
    await waitFor(() => expect(screen.queryByPlaceholderText("Nomi")).toBeNull());
    //  Fokus yopilgan tugmada qolmasin — apparat skaner holati.
    (document.activeElement as HTMLElement | null)?.blur?.();
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(nameCells()).toHaveLength(1));
    expect(nameCells()[0].value).toBe("Suv 1L");
  });

  it("S3c. PARTIYALI qator (LotReceivingEditor ko'rinib turgan) holatda skan ISHLAYDI", async () => {
    //  ⚠️  REGRESSIYA GARDI. `LotReceivingEditor` modal EMAS — inline muharrir.
    //      Agar `enabled` shartiga u ham qo'shilsa, partiyali tovar bo'lgan HAR
    //      QANDAY hujjatda skaner o'lardi. Bu test shuni to'sadi.
    const { user } = mount([NON, SUV, FIFO]);
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    //  Partiyali tovarni skan bilan qo'yamiz — qatorda lot muharriri ochiladi.
    await user.keyboard(`4780012340015{Enter}`);
    await waitFor(() => expect(nameCells()[0].value).toBe("Sut 1L"));
    await waitFor(() => expect(screen.getByTestId(/^recv-lots-\d+$/)).toBeInTheDocument());
    //  Lot muharriri KO'RINIB TURGANDA ikkinchi tovarni skanerlaymiz.
    await user.keyboard(`${BC_SUV}{Enter}`);
    await waitFor(() => expect(nameCells()).toHaveLength(2));
    expect(nameCells().map((i) => i.value)).toContain("Suv 1L");
  });

  it("S3d. lot muharriri INPUTIDA yozilganda skan yo'li CHETDA turadi", async () => {
    const { user } = mount([NON, SUV, FIFO]);
    await screen.findByRole("button", { name: /Mahsulot qo'shish/ });
    await user.keyboard(`4780012340015{Enter}`);
    await waitFor(() => expect(screen.getByTestId(/^recv-lots-\d+$/)).toBeInTheDocument());
    const lotIn = screen.getByTestId(/^recv-lots-\d+$/)
      .querySelectorAll("input")[0] as HTMLInputElement;
    await user.click(lotIn);
    await user.keyboard("12");
    //  Yozuv INPUTGA tushdi va yangi qator YARATILMADI.
    expect(lotIn.value).toContain("12");
    expect(nameCells()).toHaveLength(1);
  });
});
