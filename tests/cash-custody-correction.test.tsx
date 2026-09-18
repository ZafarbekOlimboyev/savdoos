import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Purchases } from "@/screens/Purchases";
import { invalidateBusinessDate } from "@/components/LotReceivingEditor";
import { useAuth } from "@/store/auth";
import { mockApi, renderApp, type Call } from "./util";

// QABULNI TUZATISH — KASSA MANBAI (Phase 5E, §A.4).
//
// ⚠️  BU YERDA SERVER QOIDALARI SINALMAYDI. «Qaysi kassadan pul o'tadi?» degan
//     savolning javobini SERVER beradi (`lot_correction.cash_custody_view` ->
//     `cutover_guard.preview_cash_custody`) va uning hakami backend sinovlari
//     (`tests/test_cash_custody_correction*.py`). Bu yerda tekshiriladigan narsa:
//     ekran har REJIMDA nima chizadi, serverga NIMA yuboradi va rad etishni
//     operator TILIDA ko'rsatadimi.
//
// ⚠️  IKKI XIL «PUL QIMIRLAMAYDI» BOR. Hujjat QARZ bo'lsa kassa umuman
//     qatnashmaydi (server: NOT_APPLICABLE); naqd hujjatda esa QORALAMANING
//     o'zi pulni siljitmasligi mumkin (sof identifikatsiya tuzatishi) — buni
//     faqat ekran biladi va o'shanda blok CHIZILMAYDI.

const OK_RESP = {
  ok: true, correction_id: "c1", receiving_id: "r1", purchase_id: "pur1",
  reversed_total: 14000, replaced_total: 0, delta_total: -14000,
  purchase_status: "received", cancelled: false, duplicate: false,
};

const PURCHASES = [{ id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", date: "2026-09-17", total: 70000, status: "received" }];

const BRANCH = { id: "b1", name: "Asosiy" };
/** Serverning hisob obyekti — AYNAN 4 maydon (§A.3 oshkorlik chegarasi). */
const TILL_1 = { id: "acc-till-1", type: "TILL", code: "TILL-01", currency: "UZS" };
const TILL_2 = { id: "acc-till-2", type: "TILL", code: "TILL-02", currency: "UZS" };
const SAFE_1 = { id: "acc-safe-1", type: "SAFE", code: "SAFE-01", currency: "UZS" };

/** `cash_custody` bloki — server HAR YO'LDA shu shaklni qaytaradi. */
const custody = (over: Record<string, any> = {}) => ({
  mode: "NOT_REQUIRED", reason: null, resolved: null, options: [], branch: BRANCH, ...over,
});

/** Bitta kuzatuvli qator, hech narsa ketmagan; NAQD hujjat (`paid == total`). */
const DETAIL = {
  id: "pur1", doc_no: "KIR-1", supplier: "Ta'minotchi", supplier_id: "s1",
  date: "2026-09-17", status: "received", payment: "cash",
  subtotal: 70000, total: 70000, paid_amount: 70000,
  receiving_id: "r1", correctable: true, correction_blocked_reason: null, corrections: [],
  branch_id: "b1",
  cash_custody: custody(),
  items: [{
    id: "i1", product_id: "p1", name: "Sut 1L", qty: 10, unit_cost: 7000, line_total: 70000,
    sell_price: 12000, unit: "dona", stock: 10, track_lots: true, track_expiry: false,
    lots: [{ id: "b1", batch_no: "A-1", expiry_date: null, received_qty: 10, remaining_qty: 10, consumed_qty: 0, unit_cost: 7000, status: "open", correctable: true }],
  }],
};

const doc = (cash: any, over: Record<string, any> = {}) => ({ ...DETAIL, cash_custody: cash, ...over });

function login() {
  useAuth.setState({
    token: "t",
    employee: {
      id: "e1", full_name: "Aziz", role_code: "menejer", role_name: "Menejer",
      status: "active", permissions: ["xaridlar.view", "xaridlar.edit"],
    } as any,
  });
}

function mount(detail: any, correction: any = OK_RESP): Call[] {
  invalidateBusinessDate();
  return mockApi([
    [/\/purchases\/pur1/, detail],
    [/\/purchases/, PURCHASES],
    [/\/receiving\/r1\/corrections/, correction],
    [/\/suppliers/, [{ id: "s1", name: "Ta'minotchi", phone: null, balance: 0 }]],
    [/\/categories/, [{ id: "c1", name: "Ichimliklar" }]],
    [/\/lots\/products\//, { business_date: "2026-09-17", lots: [] }],
    [/\/products/, []],
  ]);
}

const corrections = (calls: Call[]) => calls.filter((c) => c.url.includes("/corrections"));

async function openModal(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByText("KIR-1"));
  await screen.findByTestId("kd-qty-0");
  await u.click(screen.getByTestId("kd-correct"));
  await screen.findByTestId("corr-modal");
}

/** Pulni SILJITADIGAN qoralama: 2 dona teskari (−14 000), o'rniga qo'yish yo'q. */
async function moneyDraft(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByTestId("corr-reason"), "10 emas, 8 keldi");
  await u.type(screen.getByTestId("corr-rev-b1"), "2");
}

/** Pul QIMIRLAMAYDIGAN qoralama: 10 teskari + o'rniga AYNI miqdor, AYNI tannarx. */
async function neutralDraft(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByTestId("corr-reason"), "Partiya raqami xato yozilgan");
  await u.type(screen.getByTestId("corr-rev-b1"), "10");
  await u.click(screen.getByTestId("corr-replace-0"));
  await u.type(screen.getByTestId("corr-rep-cost-0"), "7000");
  await u.type(screen.getByTestId("corr-lots-0-batch-0"), "B-9");
}

describe("Kassa manbai — SERVER ANIQLAGAN (SERVER_RESOLVED)", () => {
  it("smena kassasi FAQAT O'QISH uchun ko'rinadi va so'rovga QO'SHILMAYDI", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(custody({ mode: "SERVER_RESOLVED", resolved: TILL_1 })));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    const box = screen.getByTestId("corr-cash");
    expect(within(box).getByTestId("corr-cash-resolved")).toHaveTextContent("TILL-01");
    expect(within(box).getByTestId("corr-cash-resolved")).toHaveTextContent(/касса/i);
    expect(box).toHaveTextContent(/сервер определил её сам/i);
    // ⚠️  TANLOV YO'Q: smena o'rtasida kassa almashtirilmaydi — mijoz taxmin
    //     qilgan hisob smena kassasidan farq qilsa, server butun tuzatishni
    //     rad etardi (`TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER`).
    expect(screen.queryByTestId("corr-cash-select")).toBeNull();

    expect(screen.getByTestId("corr-submit")).toBeEnabled();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body).not.toHaveProperty("cash_account_id");
  });
});

describe("Kassa manbai — OPERATOR TANLAYDI (OPERATOR_MUST_CHOOSE)", () => {
  const CHOOSE = custody({
    mode: "OPERATOR_MUST_CHOOSE", reason: "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER",
    options: [TILL_1, TILL_2, SAFE_1],
  });

  it("tanlanmaguncha YOZIB BO'LMAYDI; tanlangach AYNAN o'sha id ketadi", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(CHOOSE));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    const sel = screen.getByTestId("corr-cash-select") as HTMLSelectElement;
    // ⚠️  BIRINCHI HISOB AVTOMATIK TANLANMAYDI (bitta bo'lganda ham): pul
    //     qayerdan o'tganini taxmin qilish — aynan shu bo'limda taqiqlangan
    //     narsa. Boshlang'ich qiymat BO'SH.
    expect(sel.value).toBe("");
    expect(within(sel).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "— выберите кассу —", "TILL-01 · касса", "TILL-02 · касса", "SAFE-01 · сейф",
    ]);
    expect(screen.getByTestId("corr-submit")).toBeDisabled();
    expect(screen.getByTestId("corr-cash-need")).toHaveTextContent(/сервер не угадывает/i);

    // Ikkinchi kassa — birinchisi emas: yuborilgan id AYNAN tanlangani bo'lsin.
    await u.selectOptions(sel, TILL_2.id);
    expect(screen.getByTestId("corr-submit")).toBeEnabled();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body.cash_account_id).toBe(TILL_2.id);
  });

  it("SEYF ham tanlana oladi — ro'yxat kassalar bilan cheklanmaydi", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(CHOOSE));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    await u.selectOptions(screen.getByTestId("corr-cash-select"), SAFE_1.id);
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body.cash_account_id).toBe(SAFE_1.id);
  });

  it("filialda FAOL hisob yo'q: bo'sh «select» emas, ANIQ matn", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(custody({
      mode: "OPERATOR_MUST_CHOOSE", reason: "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER",
      options: [],
    })));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    // ⚠️  BO'SH RO'YXAT — «tanlang» degan ko'rsatma EMAS: tanlaydigan narsa yo'q.
    //     Operator nima qilishini bilsin (filial nomi bilan).
    expect(screen.queryByTestId("corr-cash-select")).toBeNull();
    const empty = screen.getByTestId("corr-cash-empty");
    expect(empty).toHaveTextContent(/нет активной кассы/i);
    expect(empty).toHaveTextContent("Asosiy");
    expect(screen.getByTestId("corr-submit")).toBeDisabled();
    expect(corrections(calls)).toHaveLength(0);
  });
});

describe("Kassa manbai — YOPIQ (BLOCKED)", () => {
  const LEGACY = custody({ mode: "BLOCKED", reason: "LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER" });

  it("sabab OPERATOR TILIDA ko'rinadi, tanlov BERILMAYDI, yozish YOPIQ", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(LEGACY));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    const blocked = screen.getByTestId("corr-cash-blocked");
    // Kontekst (nega aynan HOZIR yopiq) + SERVER kodining tarjimasi
    // (`serverErrorsCash.ts`) — xom kod ekranga chiqmaydi.
    expect(blocked).toHaveTextContent(/Это исправление двигает деньги/i);
    expect(blocked).toHaveTextContent(/смена открыта по-старому/i);
    expect(blocked).not.toHaveTextContent("LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER");
    // ⚠️  EXPLICIT HISOB HAM QUTQARMAYDI (server: smena shoxi hisobdan OLDIN
    //     hal bo'ladi) — shu bois tanlov KO'RSATILMAYDI.
    expect(screen.queryByTestId("corr-cash-select")).toBeNull();
    expect(screen.getByTestId("corr-submit")).toBeDisabled();
    expect(corrections(calls)).toHaveLength(0);
  });

  it("PUL QIMIRLAMAYDIGAN tuzatish YOPIQ rejimda ham yoziladi", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(LEGACY));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await neutralDraft(u);

    // ⚠️  ASOSIY DA'VO: sof identifikatsiya tuzatishi (raqam/muddat) kassaga
    //     TEGMAYDI — server ham hisob so'ramaydi (`ret_amt == 0`). Blokni
    //     ko'rsatish smenasiz menejerni muddat xatosi bilan qamab qo'yardi.
    expect(screen.queryByTestId("corr-cash")).toBeNull();
    expect(screen.getByTestId("corr-submit")).toBeEnabled();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body).not.toHaveProperty("cash_account_id");
  });
});

describe("Kassa manbai — BLOK KO'RSATILMAYDIGAN YO'LLAR", () => {
  it("QARZ hujjati (NOT_APPLICABLE): pul siljisa ham hech narsa so'ralmaydi", async () => {
    const u = userEvent.setup();
    login();
    const calls = mount(doc(custody({ mode: "NOT_APPLICABLE" })));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    expect(screen.queryByTestId("corr-cash")).toBeNull();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body).not.toHaveProperty("cash_account_id");
  });

  it("T0'gacha (NOT_REQUIRED): ekran hech narsa ko'rsatmaydi, hech narsa yubormaydi", async () => {
    // Bugungi Fayzan AYNAN shu holatda: `cutover_at` qatori yo'q.
    const u = userEvent.setup();
    login();
    const calls = mount(doc(custody({ mode: "NOT_REQUIRED" })));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    expect(screen.queryByTestId("corr-cash")).toBeNull();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body).not.toHaveProperty("cash_account_id");
  });

  it("ESKI SERVER (`cash_custody` yo'q): oqim 5D'dagidek ishlaydi", async () => {
    const u = userEvent.setup();
    login();
    const { cash_custody: _omit, ...OLD } = DETAIL;
    const calls = mount(OLD);
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);

    expect(screen.queryByTestId("corr-cash")).toBeNull();
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));
    await waitFor(() => expect(corrections(calls)).toHaveLength(1));
    expect(corrections(calls)[0].body).not.toHaveProperty("cash_account_id");
  });
});

describe("Kassa manbai — «PUL QIMIRLAYDIMI» HISOBI YOZUVCHINIKI", () => {
  it("hujjat jami to'langan summadan farq qilsa — blok delta NOL bo'lsa ham chiqadi", async () => {
    // ⚠️  SHARTNOMA EMAS, KOD. Yozuvchi kassa hisobini `ret_amt = paid_amount -
    //     new_total` nolga teng bo'lmaganda so'raydi (`_correct_once` §13), ya'ni
    //     `delta` ning o'zi bilan EMAS. Odatdagi naqd hujjatda `paid == total`
    //     va ikkalasi bir xil natija beradi; eski ma'lumotdagi farq esa aynan shu
    //     yerda ajraladi — `delta` ga qarasak, ekran «hech narsa kerak emas» deb
    //     ko'rsatib, server 400 berardi.
    const u = userEvent.setup();
    login();
    mount(doc(custody({
      mode: "OPERATOR_MUST_CHOOSE", reason: "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER",
      options: [TILL_1],
    }), { paid_amount: 68000 }));
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await neutralDraft(u);          // delta = 0, lekin ret_amt = 68 000 − 70 000

    expect(screen.getByTestId("corr-cash-select")).toBeInTheDocument();
    expect(screen.getByTestId("corr-submit")).toBeDisabled();
  });
});

describe("Kassa manbai — SERVER RAD ETSA", () => {
  it("400 «hisob yaroqsiz» xatosi operator TILIDA ko'rinadi", async () => {
    // ⚠️  KASSA RAD ETISHIDA `X-Error-Code` SARLAVHASI YO'Q — kod MATNGA
    //     prefiks bo'lib keladi (`cutover_guard._fail`: "KOD: matn"), shu bois
    //     tarjima `serverErrorsCash.ts` da PREFIKS bo'yicha qidiradi. Sinov
    //     server yozganidek xom matn beradi: lug'at jimgina tushib qolsa qizaradi.
    const u = userEvent.setup();
    login();
    const calls = mount(doc(custody({
      mode: "OPERATOR_MUST_CHOOSE", reason: "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER",
      options: [TILL_1],
    })), {
      __status: 400,
      detail: "CASH_CUSTODY_ACCOUNT_INVALID: 'receiving_correction_cash': ko'rsatilgan "
        + "kassa hisobi yaroqsiz (boshqa filial, arxivlangan yoki mavjud emas)",
    });
    renderApp(<Purchases />, { lang: "ru" });
    await openModal(u);
    await moneyDraft(u);
    await u.selectOptions(screen.getByTestId("corr-cash-select"), TILL_1.id);
    await u.click(screen.getByTestId("corr-submit"));
    await u.click(await screen.findByTestId("confirm-ok"));

    // ⚠️  MATN OPERATOR QILA OLADIGAN ISHNI AYTADI (Phase 5E): «hisob bu amalga
    //     to'g'ri kelmaydi» + boshqa filialdagi ochiq smena holati uchun yo'l.
    await waitFor(() => expect(screen.getByTestId("corr-error"))
      .toHaveTextContent(/Денежный счёт не подходит для этой операции/i));
    expect(screen.getByTestId("corr-error")).toHaveTextContent(/другом филиале/i);
    expect(screen.getByTestId("corr-error")).not.toHaveTextContent("CASH_CUSTODY_ACCOUNT_INVALID");
    expect(corrections(calls)).toHaveLength(1);
  });
});
