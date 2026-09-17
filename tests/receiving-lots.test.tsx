import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FullReceiving, type Product } from "@/screens/Products";
import { Purchases } from "@/screens/Purchases";
import { invalidateBusinessDate } from "@/components/LotReceivingEditor";
import { mockApi, renderApp, type Call } from "./util";

// KIRIM EKRANI × PARTIYA (Phase 5C, B2).
//
// ⚠️  ENG MUHIM SINOV — BIRINCHISI. Production'da BIRORTA kuzatuvli tovar yo'q,
//     ya'ni bu o'zgarish kuzatuvsiz kirim payloadini BIR BAYTGA ham
//     o'zgartirmasligi shart. Qolgani — kuzatuv yoqilgandan keyingi xulq.

const BIZ = "2026-09-17";
const FUTURE = "2026-12-01";

const prod = (over: Partial<Product>): Product => ({
  id: "p0", article_code: "A-0", sku: "0", name: "Tovar", category_id: "c1",
  base_buy_price: 7000, base_sell_price: 12000, stock: 0, min_stock: 0, unit_code: "dona",
  expiry_date: null, barcodes: [], track_lots: false, track_expiry: false, ...over,
});

const FIFO = prod({ id: "p1", name: "Sut 1L", track_lots: true, barcodes: ["4780012340015"] });
const EXPIRY = prod({ id: "p2", name: "Qatiq 400g", track_lots: true, track_expiry: true });
const PLAIN = prod({ id: "p3", name: "Non", base_buy_price: 2000, base_sell_price: 3000 });
const CATS = [{ id: "c1", name: "Ichimliklar" }, { id: "c2", name: "Oziq-ovqat" }];
const SUPS = [{ id: "s1", name: "Ta'minotchi" }];

function mount(over: { commit?: any } = {}) {
  invalidateBusinessDate();
  const onSaved = vi.fn();
  const calls = mockApi([
    [/\/products\?tracked=true/, [FIFO, EXPIRY]],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/lots\/products\//, { business_date: BIZ, track_lots: true, track_expiry: true, lots: [] }],
    [/\/receiving\/commit/, over.commit ?? { ok: true, receiving_id: "r1", doc_no: "KIR-1" }],
  ]);
  renderApp(
    <FullReceiving cats={CATS} products={[FIFO, EXPIRY, PLAIN]} suppliers={SUPS}
                   onBack={() => {}} onSaved={onSaved} />, { lang: "ru" });
  return { calls, onSaved };
}

const commits = (calls: Call[]) => calls.filter((c) => c.url.includes("/receiving/commit"));
const trackedFetches = (calls: Call[]) => calls.filter((c) => c.url.includes("tracked=true"));

async function addRow(u: ReturnType<typeof userEvent.setup>) {
  await u.click(screen.getByRole("button", { name: /Добавить товар/ }));
}

/** Mavjud tovarni nom bo'yicha tanlash (taklif ro'yxatidan — haqiqiy yo'l). */
async function pick(u: ReturnType<typeof userEvent.setup>, name: string) {
  const inputs = screen.getAllByPlaceholderText("Название товара");
  await u.type(inputs[inputs.length - 1], name.slice(0, 4));
  await u.click(await screen.findByText(name));
}

async function typeQty(u: ReturnType<typeof userEvent.setup>, key: number, v: string) {
  const el = screen.getByTestId(`recv-qty-${key}`);
  await u.clear(el);
  await u.type(el, v);
}

const confirmRow = (u: ReturnType<typeof userEvent.setup>) =>
  u.click(screen.getAllByTitle("Подтвердить")[0]);

describe("Kirim × partiya — KUZATUVSIZ oqim O'ZGARMAYDI", () => {
  it("yangi (kuzatuvsiz) tovar payloadi HARFMA-HARF bugungidek", async () => {
    const u = userEvent.setup();
    const { calls, onSaved } = mount();
    await addRow(u);
    await u.type(screen.getByPlaceholderText("Название товара"), "Yangi tovar");
    await u.type(screen.getByPlaceholderText("Скан / ввод"), "4780012349999");
    await u.selectOptions(screen.getAllByRole("combobox")[1], "c1");
    const nums = screen.getAllByPlaceholderText("0");
    await u.type(nums[0], "5000");
    await u.type(nums[1], "7000");
    await typeQty(u, 1, "10");
    await confirmRow(u);
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());

    const body = commits(calls)[0].body;
    // AYNAN shu matn (kalit tartibi bilan) 537d20b da ham yuborilardi.
    expect(JSON.stringify(body.items[0])).toBe(JSON.stringify({
      product_id: null, new_name: "Yangi tovar", new_sell_price: 7000, new_category_id: "c1",
      new_barcode: "4780012349999", new_plu: null, new_is_weighted: false,
      qty: 10, unit_cost: 5000, unit: "dona",
    }));
    expect(JSON.stringify(body)).not.toContain("lots");
  });

  it("KUZATUVSIZ mavjud tovarda muharrir UMUMAN ko'rinmaydi", async () => {
    const u = userEvent.setup();
    mount();
    await addRow(u);
    await pick(u, "Non");
    await typeQty(u, 1, "3");
    expect(screen.queryByTestId("recv-lots-1")).toBeNull();
  });
});

describe("Kirim × partiya — KUZATUVLI tovar", () => {
  it("bitta partiya: miqdor qatorga ERGASHADI va `lots` bilan yuboriladi", async () => {
    const u = userEvent.setup();
    const { calls, onSaved } = mount();
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 1, "10");
    expect(screen.getByTestId("recv-lots-1-qty-0")).toHaveValue("10");
    expect(screen.queryByTestId("recv-lots-1-expiry-0")).toBeNull();   // FIFO — sana YO'Q
    await confirmRow(u);
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());

    const it0 = commits(calls)[0].body.items[0];
    expect(it0.product_id).toBe("p1");
    expect(it0.qty).toBe(10);
    expect(it0.lots).toEqual([{ qty: 10 }]);
  });

  it("ko'p partiya: mos kelmagan yig'indi TASDIQLATMAYDI, «qolganini yozish» tuzatadi", async () => {
    const u = userEvent.setup();
    const { calls } = mount();
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 1, "10");
    const q0 = screen.getByTestId("recv-lots-1-qty-0");
    await u.clear(q0);
    await u.type(q0, "6");
    await u.click(screen.getByTestId("recv-lots-1-add"));
    await u.type(screen.getByTestId("recv-lots-1-qty-1"), "3");
    expect(screen.getByTestId("recv-lots-1-sum")).toHaveTextContent(/осталось 1/);

    await confirmRow(u);
    expect(screen.getByTestId("recv-error")).toHaveTextContent(/Сумма партий не равна/i);
    await u.click(screen.getByTestId("recv-save"));
    expect(commits(calls)).toHaveLength(0);          // hujjat YUBORILMADI

    await u.click(screen.getByTestId("recv-lots-1-fill"));
    expect(screen.getByTestId("recv-lots-1-qty-1")).toHaveValue("4");
    await confirmRow(u);
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(commits(calls)).toHaveLength(1));
    expect(commits(calls)[0].body.items[0].lots).toEqual([{ qty: 6 }, { qty: 4 }]);
  });

  it("MUDDAT kuzatiladigan tovar: sanasiz tasdiqlanmaydi, o'tgan sana ham", async () => {
    const u = userEvent.setup();
    const { calls } = mount();
    await addRow(u);
    await pick(u, "Qatiq 400g");
    await typeQty(u, 1, "5");
    await waitFor(() => expect(screen.getByTestId("recv-lots-1-bizdate")).toHaveTextContent(BIZ));

    await confirmRow(u);
    expect(screen.getByTestId("recv-error")).toHaveTextContent(/срок/i);

    const d = screen.getByTestId("recv-lots-1-expiry-0");
    await u.clear(d);
    await u.type(d, "2026-09-16");                     // biznes sanasidan OLDIN
    await confirmRow(u);
    expect(screen.getByTestId("recv-error")).toHaveTextContent(/бизнес-дат/i);
    expect(commits(calls)).toHaveLength(0);

    await u.clear(d);
    await u.type(d, FUTURE);
    await u.type(screen.getByTestId("recv-lots-1-batch-0"), "  A-1  ");
    await confirmRow(u);
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(commits(calls)).toHaveLength(1));
    expect(commits(calls)[0].body.items[0].lots).toEqual([
      { qty: 5, batch_number: "A-1", expiry_date: FUTURE },
    ]);
  });

  it("TASDIQLANMAGAN partiyali qator jimgina tushib qolmaydi", async () => {
    const u = userEvent.setup();
    const { calls } = mount();
    // 1-qator: kuzatuvsiz, tasdiqlangan (hujjatda summa bo'lsin)
    await addRow(u);
    await pick(u, "Non");
    await typeQty(u, 1, "2");
    await confirmRow(u);
    // 2-qator: kuzatuvli, TASDIQLANMAGAN
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 2, "4");

    await u.click(screen.getByTestId("recv-save"));
    expect(screen.getByTestId("recv-error")).toHaveTextContent(/не подтверждена/i);
    expect(commits(calls)).toHaveLength(0);
  });

  it("nom KUZATUVLI tovarniki bo'lsa — yangi tovar sifatida yuborilmaydi", async () => {
    const u = userEvent.setup();
    mount();
    await addRow(u);
    await u.type(screen.getByPlaceholderText("Название товара"), "sut 1l");
    await confirmRow(u);
    expect(screen.getByTestId("recv-error")).toHaveTextContent(/учётом партий/i);
  });
});

describe("Kirim × partiya — SERVER javoblari", () => {
  it("400: xabar OPERATOR TILIDA ko'rinadi va kuzatuvli ro'yxat QAYTA o'qiladi", async () => {
    const u = userEvent.setup();
    const { calls, onSaved } = mount({
      commit: {
        __status: 400,
        detail: "'Sut 1L': partiyalar yig'indisi 9.000 qator miqdori 10.000 ga TENG EMAS. "
          + "Yetishmagan miqdor taxmin qilinmaydi.",
      },
    });
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 1, "10");
    await confirmRow(u);
    const before = trackedFetches(calls).length;
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(screen.getByTestId("recv-error")).toHaveTextContent(/сумма партий/i));
    expect(onSaved).not.toHaveBeenCalled();
    await waitFor(() => expect(trackedFetches(calls).length).toBe(before + 1));
  });

  it("IKKI marta bosish — BITTA so'rov; xatodan keyin AYNI client_uuid", async () => {
    const u = userEvent.setup();
    let release: ((v: any) => void) | null = null;
    let first = true;
    const { calls } = mount({
      commit: () => {
        if (!first) return { ok: true, receiving_id: "r1" };
        first = false;
        return new Promise((res) => { release = res; });
      },
    });
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 1, "10");
    await confirmRow(u);

    await u.click(screen.getByTestId("recv-save"));
    await u.click(screen.getByTestId("recv-save"));
    expect(commits(calls)).toHaveLength(1);
    release!({ __status: 500, detail: "server" });
    await waitFor(() => expect(screen.getByTestId("recv-error")).toBeInTheDocument());

    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(commits(calls)).toHaveLength(2));
    // QA PC-002: qayta yuborishda AYNI kalit — server dedup ushlasin.
    expect(commits(calls)[1].body.client_uuid).toBe(commits(calls)[0].body.client_uuid);
  });

  it("duplicate: hujjat ALLAQACHON yozilgani AYTILADI (jimgina yopilmaydi)", async () => {
    const u = userEvent.setup();
    const { onSaved } = mount({ commit: { ok: true, receiving_id: "r1", duplicate: true } });
    await addRow(u);
    await pick(u, "Sut 1L");
    await typeQty(u, 1, "10");
    await confirmRow(u);
    await u.click(screen.getByTestId("recv-save"));
    await waitFor(() => expect(screen.getByTestId("recv-duplicate")).toBeInTheDocument());
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByTestId("recv-save")).toBeDisabled();
    await u.click(screen.getByTestId("recv-duplicate-ok"));
    expect(onSaved).toHaveBeenCalled();
  });
});

// ── RASM ORQALI KIRIM VA KIRIM TAFSILOTI ─────────────────────────────────────

const PURCHASES = [{ id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", date: "2026-09-17", total: 70000, status: "received" }];

function mountPurchases(over: { detail?: any; scan?: any } = {}) {
  invalidateBusinessDate();
  return mockApi([
    [/\/purchases\/pur1/, over.detail ?? {
      id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", supplier_id: "s1",
      date: "2026-09-17", status: "received", payment: "cash", subtotal: 70000, total: 70000,
      paid_amount: 70000,
      items: [
        { id: "i1", product_id: "p1", name: "Sut 1L", qty: 10, unit_cost: 7000, line_total: 70000, sell_price: 12000, unit: "dona", stock: 10, track_lots: true, track_expiry: false },
        { id: "i2", product_id: "p3", name: "Non", qty: 2, unit_cost: 2000, line_total: 4000, sell_price: 3000, unit: "dona", stock: 2, track_lots: false, track_expiry: false },
      ],
    }],
    [/\/purchases/, PURCHASES],
    [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
    [/\/categories/, CATS],
    [/\/receiving\/scan/, over.scan ?? {
      source: "ai", ai_raw: [],
      items: [{ ai_name: "Sut 1L", qty: 5, unit: "dona", product_id: "p1", matched_name: "Sut 1L", unit_cost: 7000 }],
    }],
    [/\/receiving\/commit/, { ok: true, receiving_id: "r2" }],
    [/\/products\/guess-category/, { category_id: null }],
    [/\/lots\/products\//, { business_date: BIZ, lots: [] }],
    [/\/products/, [FIFO, EXPIRY, PLAIN]],
  ]);
}

async function openPhoto(u: ReturnType<typeof userEvent.setup>, container: HTMLElement) {
  await u.click(await screen.findByRole("button", { name: /Приход по фото/ }));
  const file = container.querySelector('input[type="file"]') as HTMLInputElement;
  await u.upload(file, new File(["x"], "n.jpg", { type: "image/jpeg" }));
  await screen.findByTestId("kirim-lots-0", undefined, { timeout: 4000 });
}

describe("Rasm orqali kirim — kuzatuvli qator", () => {
  it("partiyasiz yuborilmaydi; to'g'rilangach `lots` bilan ketadi", async () => {
    const u = userEvent.setup();
    const calls = mountPurchases();
    const { container } = renderApp(<Purchases />, { lang: "ru" });
    await openPhoto(u, container);

    // Miqdor 5 — partiya avtomatik 5 bilan ochildi; uni BUZAMIZ.
    const lotQty = screen.getByTestId("kirim-lots-0-qty-0");
    await u.clear(lotQty);
    await u.type(lotQty, "2");
    await u.click(screen.getByTestId("kirim-save"));
    expect(screen.getByTestId("kirim-error")).toHaveTextContent(/Sut 1L/);
    expect(commits(calls)).toHaveLength(0);

    await u.click(screen.getByTestId("kirim-lots-0-add"));
    await u.type(screen.getByTestId("kirim-lots-0-qty-1"), "3");
    await u.click(screen.getByTestId("kirim-save"));
    await waitFor(() => expect(commits(calls)).toHaveLength(1));
    const it0 = commits(calls)[0].body.items[0];
    expect(it0.product_id).toBe("p1");
    expect(it0.lots).toEqual([{ qty: 2 }, { qty: 3 }]);
  });
});

describe("Kirim tafsiloti — kuzatuvli qator QULFLANGAN", () => {
  it("miqdor/narx/o'chirish yopiq va sababi yozilgan (kuzatuvsiz qator ochiq)", async () => {
    const u = userEvent.setup();
    mountPurchases();
    renderApp(<Purchases />, { lang: "ru" });
    await u.click(await screen.findByText("KIR-1"));
    await screen.findByTestId("kd-tracked-note");

    expect(screen.getByTestId("kd-qty-0")).toBeDisabled();
    expect(screen.getByTestId("kd-cost-0")).toBeDisabled();
    expect(screen.getByTestId("kd-remove-0")).toBeDisabled();
    expect(screen.getByTestId("kd-tracked-note")).toHaveTextContent(/Инвентаризаци/i);
    // KUZATUVSIZ qator — avvalgidek tahrirlanadi
    expect(screen.getByTestId("kd-qty-1")).not.toBeDisabled();
    expect(screen.getByTestId("kd-cost-1")).not.toBeDisabled();
  });
});
