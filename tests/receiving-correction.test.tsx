import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Purchases } from "@/screens/Purchases";
import { translate } from "@/lib/i18n";
import { invalidateBusinessDate } from "@/components/LotReceivingEditor";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp, type Call } from "./util";

// QABULNI TUZATISH — MANAGER EKRANI (Phase 5D, §8).
//
// ⚠️  BU YERDA SERVER QOIDALARI SINALMAYDI. Tuzatish qoldiqni, yetkazib beruvchi
//     qarzini VA kassani birdaniga siljitadi — buning hakami backend
//     (`services/lot_correction.py` va uning sinovlari). Bu yerda tekshiriladigan
//     narsa: ekran serverga NIMA yuboradi, rad etishni operator TILIDA
//     ko'rsatadimi va ruxsatsiz xodimga oqim umuman ko'rinadimi.
//
// ⚠️  RAD ETISH MATNI SERVERDAN KELADI. Sinov uni lotin-o'zbekcha (server
//     yozganidek) beradi va rus tilidagi natijani kutadi: shunda lug'at
//     (`serverErrorsLots.ts`) jimgina tushib qolsa sinov qizaradi.

const OK_RESP = {
  ok: true, correction_id: "c1", receiving_id: "r1", purchase_id: "pur1",
  reversed_total: 14000, replaced_total: 0, delta_total: -14000,
  purchase_status: "received", cancelled: false, duplicate: false,
};

const PURCHASES = [{ id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", date: "2026-09-17", total: 74000, status: "received" }];

/** Aralash hujjat: kuzatuvli qator (ikki kogorta, biri TEGILGAN) + kuzatuvsiz qator. */
const DETAIL = {
  id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", supplier_id: "s1",
  date: "2026-09-17", status: "received", payment: "cash",
  subtotal: 74000, total: 74000, paid_amount: 74000,
  receiving_id: "r1", correctable: true, correction_blocked_reason: null, corrections: [],
  items: [
    {
      id: "i1", product_id: "p1", name: "Sut 1L", qty: 10, unit_cost: 7000, line_total: 70000,
      sell_price: 12000, unit: "dona", stock: 7, track_lots: true, track_expiry: false,
      lots: [
        { id: "b1", batch_no: "A-1", expiry_date: null, received_qty: 6, remaining_qty: 6, consumed_qty: 0, unit_cost: 7000, status: "open", correctable: true },
        { id: "b2", batch_no: "A-2", expiry_date: null, received_qty: 4, remaining_qty: 1, consumed_qty: 3, unit_cost: 7000, status: "open", correctable: false },
      ],
    },
    {
      id: "i2", product_id: "p3", name: "Non", qty: 2, unit_cost: 2000, line_total: 4000,
      sell_price: 3000, unit: "dona", stock: 2, track_lots: false, track_expiry: false, lots: [],
    },
  ],
};

/** Bitta kuzatuvli qator, hech narsa ketmagan — TO'LIQ bekor qilinadigan hujjat. */
const DETAIL_ONE = {
  ...DETAIL, subtotal: 70000, total: 70000, paid_amount: 70000,
  items: [{
    id: "i1", product_id: "p1", name: "Sut 1L", qty: 10, unit_cost: 7000, line_total: 70000,
    sell_price: 12000, unit: "dona", stock: 10, track_lots: true, track_expiry: false,
    lots: [{ id: "b1", batch_no: "A-1", expiry_date: null, received_qty: 10, remaining_qty: 10, consumed_qty: 0, unit_cost: 7000, status: "open", correctable: true }],
  }],
};

function login(perms: string[]) {
  useAuth.setState({
    token: "t",
    employee: {
      id: "e1", full_name: "Aziz", role_code: "menejer", role_name: "Menejer",
      status: "active", permissions: perms,
    } as any,
  });
}

function mountP(over: { detail?: any; correction?: any } = {}) {
  invalidateBusinessDate();
  return mockApi([
    [/\/purchases\/pur1/, over.detail ?? DETAIL],
    [/\/purchases/, PURCHASES],
    [/\/receiving\/r1\/corrections/, over.correction ?? OK_RESP],
    [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
    [/\/categories/, [{ id: "c1", name: "Ichimliklar" }]],
    [/\/lots\/products\//, { business_date: "2026-09-17", lots: [] }],
    [/\/products/, []],
  ]);
}

const corrections = (calls: Call[]) => calls.filter((c) => c.url.includes("/corrections"));

/** Ro'yxatdan hujjatni ochadi va tafsilot yuklanguncha kutadi. */
async function openDoc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByText("KIR-1"));
  await screen.findByTestId("kd-qty-0");
}

async function openModal(u: ReturnType<typeof userEvent.setup>) {
  await openDoc(u);
  await u.click(screen.getByTestId("kd-correct"));
  await screen.findByTestId("corr-modal");
}

describe("Tuzatish oqimi — RUXSAT", () => {
  it("`xaridlar.edit` yo'q xodimga tugma UMUMAN ko'rinmaydi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.view"]);
    mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openDoc(u);
    // ⚠️  Server baribir 403 berardi — lekin operator buni butun oynani
    //     to'ldirib bo'lgandan KEYIN bilardi.
    expect(screen.queryByTestId("kd-correct")).toBeNull();
  });

  it("`xaridlar.edit` bor xodimda tugma bor", async () => {
    const u = userEvent.setup();
    login(["xaridlar.view", "xaridlar.edit"]);
    mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openDoc(u);
    expect(screen.getByTestId("kd-correct")).toBeInTheDocument();
  });

  it("server «tuzatib bo'lmaydi» desa — SABABI operator tilida ko'rinadi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.view", "xaridlar.edit"]);
    mountP({
      detail: {
        ...DETAIL, correctable: false,
        // ⚠️  SERVER MATNI AYNAN (`api/v1/purchases.SHORTFALL_BLOCK`): lug'at kaliti
        //     shu satr — bir harf farq qilsa operator XOM lotin matnini ko'radi.
        correction_blocked_reason: "Mahsulotda yopilmagan partiya qarzi bor — avval "
          + "qarzni partiyaga bog'lang, keyin bu qatorni tuzating.",
      },
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openDoc(u);
    expect(screen.queryByTestId("kd-correct")).toBeNull();
    expect(screen.getByTestId("kd-correct-blocked"))
      .toHaveTextContent(/незакрытый долг по партиям/i);
  });
});

describe("Tuzatilgan hujjat — ESKI TAHRIR YO'LI", () => {
  it("tuzatish bo'lgan hujjatda qatorlar ham, «Saqlash» ham YOPIQ", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    mountP({
      detail: {
        ...DETAIL,
        corrections: [{ id: "c1", at: "2026-09-18T07:00:00+00:00", reason: "10 emas, 8 keldi", delta_total: -14000, employee: "Aziz" }],
      },
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openDoc(u);

    // ⚠️  `PATCH /purchases/{id}` hujjat jamini QATORLARDAN qayta hisoblaydi va
    //     tuzatishni jimgina teskari qilardi — server uni 409 bilan rad etadi.
    expect(screen.getByTestId("kd-doc-locked")).toHaveTextContent(/старое редактирование/i);
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByTestId("kd-qty-1")).toBeDisabled();       // kuzatuvsiz qator HAM
    expect(screen.getByTestId("kd-corrections")).toHaveTextContent("10 emas, 8 keldi");
    // Yangi tuzatish esa OCHIQ qoladi — hujjatni faqat shu yo'l o'zgartiradi.
    expect(screen.getByTestId("kd-correct")).toBeInTheDocument();
  });
});

describe("Tuzatish oynasi — KOGORTALAR", () => {
  it("har kogorta kelgan/qoldiq/ketgan bilan ko'rinadi, tegilgani BELGILANADI", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    const b1 = screen.getByTestId("corr-lot-b1");
    expect(b1).toHaveTextContent("A-1");
    expect(b1).toHaveTextContent(/Принято: 6/);
    expect(b1).toHaveTextContent(/Остаток: 6/);
    expect(b1).toHaveTextContent(/Ушло: 0/);
    // ⚠️  «Tegilgan» — SERVER qarori (`correctable`). Ekran uni qayta
    //     hisoblamaydi: sotilib keyin qaytarilgan kogortada qoldiq AYNAN
    //     tiklanadi va «tegilmagan» ko'rinardi.
    expect(screen.getByTestId("corr-lot-b2-touched")).toHaveTextContent(/уже ушёл товар/i);
    expect(screen.queryByTestId("corr-lot-b1-touched")).toBeNull();
    // Kuzatuvsiz qator («Non») tuzatish oynasida UMUMAN ko'rinmaydi: uni bu
    // oqim o'zgartirmaydi (orqadagi tafsilot jadvalida esa qoladi).
    expect(within(screen.getByTestId("corr-modal")).queryByText("Non")).toBeNull();
  });

  it("qoldiqdan katta miqdor YUBORILMAYDI", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await u.type(screen.getByTestId("corr-reason"), "Nakladnoyda xato");
    await u.type(screen.getByTestId("corr-rev-b1"), "7");      // qoldiq 6
    await u.click(screen.getByTestId("corr-submit"));
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/больше остатка партии/i);
    expect(corrections(calls)).toHaveLength(0);
  });

  it("QATOR darajasidagi to'siq: sabab KO'RINADI va o'sha qator YOZILMAYDI", async () => {
    // ⚠️  HUJJAT OCHIQ, QATOR YOPIQ. Server yopilmagan partiya qarzini MAHSULOT
    //     bo'yicha hisoblaydi: bitta qatordagi qarz butun hujjatni yopmasin, lekin
    //     o'sha qatorga miqdor kiritib bo'lmasin — aks holda operator 409 ni faqat
    //     «Yozish» dan keyin bilardi.
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    mockApi([
      [/\/purchases\/pur1/, {
        ...DETAIL,
        items: [{
          ...DETAIL.items[0], correctable: false,
          correction_blocked_reason: "Mahsulotda yopilmagan partiya qarzi bor — avval "
            + "qarzni partiyaga bog'lang, keyin bu qatorni tuzating.",
        }, DETAIL.items[1]],
      }],
      [/\/purchases/, PURCHASES],
      [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
      [/\/categories/, []],
      [/\/products/, []],
    ]);
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    expect(screen.getByTestId("corr-line-0-blocked")).toHaveTextContent(/незакрытый долг по партиям/i);
    expect(screen.getByTestId("corr-rev-b1")).toBeDisabled();
    expect(screen.getByTestId("corr-rev-b2")).toBeDisabled();
  });

  it("TEGILGAN kogortada o'rniga qo'yish YOPIQ", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await u.type(screen.getByTestId("corr-rev-b2"), "1");
    expect(screen.getByTestId("corr-replace-0")).toBeDisabled();
    expect(screen.getByTestId("corr-replace-0-locked")).toHaveTextContent(/Замена недоступна/i);
  });
});

describe("Tuzatish oynasi — YUBORISH", () => {
  it("MIQDOR tuzatishi: faqat teskari qilish yuboriladi (tannarxsiz)", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP();
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "10 emas, 8 keldi");
    await u.type(screen.getByTestId("corr-rev-b1"), "2");
    // To'liq bekor EMAS — tugma matni ham shuni aytadi.
    expect(screen.getByTestId("corr-submit")).toHaveTextContent("Записать исправление");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));

    const c = corrections(calls)[0];
    expect(c.method).toBe("POST");
    expect(c.url).toContain("/receiving/r1/corrections");
    expect(c.body.reason).toBe("10 emas, 8 keldi");
    expect(typeof c.body.client_uuid).toBe("string");
    expect(c.body.lines).toEqual([
      { purchase_item_id: "i1", reverse: [{ stock_batch_id: "b1", qty: 2 }] },
    ]);
    // ⚠️  `unit_cost` BO'SH `replace` bilan YUBORILMAYDI — server uni 400 bilan
    //     rad etadi (tannarxni partiyasiz tuzatib bo'lmaydi).
    expect(JSON.stringify(c.body)).not.toContain("unit_cost");
    expect(JSON.stringify(c.body)).not.toContain("replace");
  });

  it("IDENTIFIKATSIYA tuzatishi: teskari + o'rniga YANGI partiya (kirim muharriri bilan)", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP({ detail: DETAIL_ONE });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Partiya raqami xato yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "10");
    await u.click(screen.getByTestId("corr-replace-0"));
    // ⚠️  TAXMIN EMAS, BOSHLANG'ICH QIYMAT: identifikatsiya tuzatishining odatiy
    //     holi — «ayni miqdor, boshqa raqam/muddat/narx». Operator o'zgartira oladi.
    expect(screen.getByTestId("corr-rep-qty-0")).toHaveValue("10");
    expect(screen.getByTestId("corr-lots-0-qty-0")).toHaveValue("10");
    // FIFO tovar — muddat maydoni YO'Q (uni yuborish serverda 400 berardi).
    expect(screen.queryByTestId("corr-lots-0-expiry-0")).toBeNull();

    await u.type(screen.getByTestId("corr-rep-cost-0"), "7500");
    await u.type(screen.getByTestId("corr-lots-0-batch-0"), "B-9");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));

    expect(corrections(calls)[0].body.lines).toEqual([{
      purchase_item_id: "i1",
      reverse: [{ stock_batch_id: "b1", qty: 10 }],
      replace: [{ qty: 10, batch_number: "B-9" }],
      unit_cost: 7500,
    }]);
  });

  it("o'rniga qo'yishda TANNARX majburiy — taxmin qilinmaydi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP({ detail: DETAIL_ONE });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Partiya raqami xato yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "10");
    await u.click(screen.getByTestId("corr-replace-0"));
    await u.click(screen.getByTestId("corr-submit"));
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/себестоимость новой партии/i);
    expect(corrections(calls)).toHaveLength(0);
  });

  it("TO'LIQ BEKOR: butun qoldiq teskari qilinadi va hujjat yopiladi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP({
      detail: DETAIL_ONE,
      correction: { ...OK_RESP, reversed_total: 70000, delta_total: -70000, cancelled: true, purchase_status: "cancelled" },
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Hujjat butunlay xato");
    await u.click(screen.getByTestId("corr-reverse-all"));
    expect(screen.getByTestId("corr-rev-b1")).toHaveValue("10");
    // Butun qoldiq qaytsa — bu BEKOR QILISH, tugma ham, tasdiq ham shuni aytadi.
    expect(screen.getByTestId("corr-submit")).toHaveTextContent("Отменить документ");
    await u.click(screen.getByTestId("corr-submit"));
    const box = await screen.findByTestId("confirm");
    expect(box).toHaveTextContent(/Документ будет ОТМЕНЁН/);
    expect(box).toHaveTextContent(/Весь приход будет отменён/);
    await u.click(screen.getByTestId("confirm-ok"));

    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body.lines).toEqual([
      { purchase_item_id: "i1", reverse: [{ stock_batch_id: "b1", qty: 10 }] },
    ]);
    // Bekor qilingan hujjat keyingi `GET` da 404 beradi — ekran ro'yxatga qaytadi.
    await waitFor(() => expect(screen.queryByTestId("corr-modal")).toBeNull());
    expect(await screen.findByRole("button", { name: /Приход по фото/ })).toBeInTheDocument();
  });

  it("409 «kogorta tegilgan» — rad etish OPERATOR TILIDA ko'rinadi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const calls = mountP({
      detail: DETAIL_ONE,
      correction: {
        __status: 409,
        detail: "'Sut 1L': partiyadan 3 dona allaqachon harakatlangan — uning partiya "
          + "raqami, muddati va tannarxini tuzatib bo'lmaydi. Tegilgan kogortada faqat "
          + "MIQDORNI teskari qilish mumkin.",
      },
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    const before = calls.filter((c) => c.url.includes("/purchases/pur1")).length;
    await u.type(screen.getByTestId("corr-reason"), "Muddat xato yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "10");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));

    await waitFor(() => expect(screen.getByTestId("corr-error"))
      .toHaveTextContent(/из партии уже ушло 3 шт/i));
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/отменить только КОЛИЧЕСТВО/i);
    // ⚠️  Ekrandagi kogortalar eskirgan bo'lishi mumkin (boshqa smena sotdi) —
    //     rad etishdan keyin hujjat QAYTA o'qiladi.
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/purchases/pur1")).length)
      .toBe(before + 1));
    expect(corrections(calls)).toHaveLength(1);
  });

  it("IKKI marta tasdiqlash — BITTA so'rov", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    let release: ((v: any) => void) | null = null;
    const calls = mountP({
      detail: DETAIL_ONE,
      correction: () => new Promise((res) => { release = res; }),
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Takroriy bosish sinovi");
    await u.type(screen.getByTestId("corr-rev-b1"), "3");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await u.click(screen.getByTestId("confirm-ok"));
    // ⚠️  Tuzatish qoldiqni, qarzni VA kassani siljitadi: ikkinchi so'rov
    //     serverda dedup'ga tayanmasdan, MIJOZDA to'siladi.
    expect(corrections(calls)).toHaveLength(1);

    release!(OK_RESP);
    await waitFor(() => expect(screen.getByTestId("kd-corr-done")).toBeInTheDocument());
    expect(corrections(calls)).toHaveLength(1);
  });
});

// ═══ F11 — TUZATISHDAN TUG'ILGAN KOGORTANING MANBASI ════════════════════════
describe("Partiya manbai — `correction`", () => {
  it("uchala tilda O'Z nomi bor (ekranga xom kalit chiqmaydi)", () => {
    // Partiya ekranlari manbani `t("lot.src." + source_type)` bilan chizadi:
    // kalit yo'q bo'lsa operator «lot.src.correction» degan xom satrni ko'rardi.
    const CYR = /[Ѐ-ӿ]/;
    const uz = translate("uz", "lot.src.correction");
    const ru = translate("ru", "lot.src.correction");
    const uzc = translate("uzc", "lot.src.correction");
    expect(uz).not.toBe("lot.src.correction");
    // ⚠️  `translate` yo'q kalitni uz'ga QAYTARADI — «xom kalit emas» tekshiruvi
    //     ru/uzc lug'atidagi bo'shliqni ko'rmasdi. Yozuv bo'yicha ajratamiz.
    expect(CYR.test(uz)).toBe(false);
    expect(CYR.test(ru)).toBe(true);
    expect(CYR.test(uzc)).toBe(true);
    // Manba nomi qolganlaridan FARQ qilishi shart: «qabuldan» kelgan kogorta
    // bilan «tuzatishda o'rniga qo'yilgan» kogortani operator ajrata olsin.
    for (const lang of ["uz", "ru", "uzc"] as const) {
      const v = translate(lang, "lot.src.correction");
      for (const other of ["receiving", "opening", "legacy", "adjustment"]) {
        expect(v).not.toBe(translate(lang, "lot.src." + other));
      }
    }
  });
});

// ═══ F12 — TRANZIENT XATODAN KEYIN AYNI KALIT BILAN TAKRORLASH ══════════════
//
// ⚠️  Tier-2 dedup AYNAN shuning uchun bor: so'rov serverga yetib borib, javob
//     yo'qolsa (Railway 504 / tarmoq uzilishi) operator AYNI `client_uuid` bilan
//     takrorlaydi va server `duplicate: true` deydi. Mijoz tekshiruvi buni
//     to'sib qo'ysa — dedup umuman ishga tushmasdi.

/** AYNI hujjat, lekin tuzatish SERVERDA allaqachon yozilgan: b1 qoldig'i tugagan. */
const DETAIL_AFTER = {
  ...DETAIL,
  subtotal: 32000, total: 32000, paid_amount: 32000,
  corrections: [{ id: "c1", at: "2026-09-18T07:00:00+00:00", reason: "6 dona ortiqcha yozilgan", delta_total: -42000, employee: "Aziz" }],
  items: [
    {
      ...DETAIL.items[0],
      lots: [
        { ...DETAIL.items[0].lots[0], remaining_qty: 0, correctable: false },
        DETAIL.items[0].lots[1],
      ],
    },
    DETAIL.items[1],
  ],
};

describe("Tuzatish oynasi — TRANZIENT XATODAN KEYIN TAKROR", () => {
  it("javob yo'qolgan so'rov AYNI kalit bilan qayta yuboriladi, dedup javobi ko'rsatiladi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    invalidateBusinessDate();
    // Birinchi POST serverga YETIB BORADI (qoldiq kamayadi), javobi esa yo'qoladi.
    let applied = false;
    const calls = mockApi([
      [/\/purchases\/pur1/, () => (applied ? DETAIL_AFTER : DETAIL)],
      [/\/purchases/, PURCHASES],
      [/\/receiving\/r1\/corrections/, () => {
        if (!applied) { applied = true; throw new TypeError("Failed to fetch"); }
        return { ...OK_RESP, reversed_total: 42000, delta_total: -42000, duplicate: true };
      }],
      [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
      [/\/categories/, [{ id: "c1", name: "Ichimliklar" }]],
      [/\/lots\/products\//, { business_date: "2026-09-17", lots: [] }],
      [/\/products/, []],
    ]);
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "6 dona ortiqcha yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "6");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    // Rad etishdan keyin hujjat qayta o'qiladi — b1 endi bo'sh (qoldiq 0).
    await waitFor(() => expect(screen.getByTestId("corr-rev-b1")).toBeDisabled());
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/Failed to fetch/);

    // ⚠️  ASOSIY DA'VO: operator AYNI qoralamani takrorlaganda mijoz tekshiruvi
    //     («qoldiqdan katta») yo'lni to'smaydi — u jo'natish PAYTIDAGI holatga
    //     qarshi allaqachon o'tgan va hakam server.
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(2));

    const [first, second] = corrections(calls);
    expect(second.body.client_uuid).toBe(first.body.client_uuid);
    expect(second.body.lines).toEqual(first.body.lines);
    // Server «allaqachon yozilgan» dedi — ekran IKKINCHI tuzatish yozilgandek
    // ko'rsatmaydi.
    expect(await screen.findByTestId("kd-corr-done")).toHaveTextContent(/уже записана/i);
  });

  it("qoralama O'ZGARSA tekshiruv QAYTA ishlaydi — xato so'rov ketmaydi", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    invalidateBusinessDate();
    let applied = false;
    const calls = mockApi([
      [/\/purchases\/pur1/, () => (applied ? DETAIL_AFTER : DETAIL)],
      [/\/purchases/, PURCHASES],
      [/\/receiving\/r1\/corrections/, () => {
        if (!applied) { applied = true; throw new TypeError("Failed to fetch"); }
        return OK_RESP;
      }],
      [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
      [/\/categories/, [{ id: "c1", name: "Ichimliklar" }]],
      [/\/lots\/products\//, { business_date: "2026-09-17", lots: [] }],
      [/\/products/, []],
    ]);
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "6 dona ortiqcha yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "6");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId("corr-rev-b1")).toBeDisabled());

    // Operator boshqa kogortadan ham qo'shdi — bu ENDI takror emas, YANGI
    // tuzatish: b2 qoldig'i 1, 2 esa undan katta.
    await u.type(screen.getByTestId("corr-rev-b2"), "2");
    await u.click(screen.getByTestId("corr-submit"));
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/больше остатка партии/i);
    expect(corrections(calls)).toHaveLength(1);
  });
});

// ═══ F13 — ISH KUNI HUJJAT TEGISHLI FILIALNIKI ══════════════════════════════

/** Hujjat filialining ish kuni — operator turgan filialnikidan FARQ qiladi. */
const BIZ_DOC = "2026-09-20";
const DETAIL_EXPIRY = {
  ...DETAIL_ONE, branch_id: "b2", business_date: BIZ_DOC,
  items: [{
    ...DETAIL_ONE.items[0], track_expiry: true,
    lots: [{ ...DETAIL_ONE.items[0].lots[0], expiry_date: "2026-12-01" }],
  }],
};

describe("Tuzatish oynasi — ISH KUNI", () => {
  it("muddat HUJJAT filialining ish kuniga qarshi tekshiriladi, operatornikiga emas", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    // `/lots/products/` — operator TURGAN filial kuni (2026-09-17). Hujjat esa
    // boshqa filialniki: u yerda ish kuni allaqachon 2026-09-20.
    const calls = mountP({ detail: DETAIL_EXPIRY });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Muddat xato yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "10");
    await u.click(screen.getByTestId("corr-replace-0"));
    await u.type(screen.getByTestId("corr-rep-cost-0"), "7500");

    expect(screen.getByTestId("corr-lots-0-bizdate")).toHaveTextContent(BIZ_DOC);
    expect(screen.getByTestId("corr-lots-0-expiry-0")).toHaveAttribute("min", BIZ_DOC);

    // ⚠️  Operator filialida bu sana HALI kelmagan (17 < 18), hujjat filialida
    //     esa allaqachon O'TGAN (18 < 20) — server aynan shuni rad etadi.
    const dt = screen.getByTestId("corr-lots-0-expiry-0");
    await u.clear(dt);
    await u.type(dt, "2026-09-18");
    await u.click(screen.getByTestId("corr-submit"));

    expect(screen.getByTestId("corr-error")).toHaveTextContent(/бизнес-дат/i);
    expect(screen.getByTestId("corr-error")).toHaveTextContent(BIZ_DOC);
    expect(corrections(calls)).toHaveLength(0);
  });

  it("ESKI SERVER `business_date` yubormasa — eski xatti-harakat (filial probi)", async () => {
    const u = userEvent.setup();
    login(["xaridlar.edit"]);
    const { business_date: _omit, ...OLD } = DETAIL_EXPIRY;
    const calls = mountP({ detail: OLD });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);

    await u.type(screen.getByTestId("corr-reason"), "Muddat xato yozilgan");
    await u.type(screen.getByTestId("corr-rev-b1"), "10");
    await u.click(screen.getByTestId("corr-replace-0"));
    await u.type(screen.getByTestId("corr-rep-cost-0"), "7500");

    await waitFor(() => expect(screen.getByTestId("corr-lots-0-bizdate")).toHaveTextContent("2026-09-17"));
    // 2026-09-18 eski serverda ham, probda ham O'TMAGAN — so'rov ketaveradi.
    const dt = screen.getByTestId("corr-lots-0-expiry-0");
    await u.clear(dt);
    await u.type(dt, "2026-09-18");
    await u.type(screen.getByTestId("corr-lots-0-batch-0"), "B-9");
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body.lines[0].replace).toEqual([{ qty: 10, batch_number: "B-9", expiry_date: "2026-09-18" }]);
  });
});
