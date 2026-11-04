// R6.9 §1 — DESKTOP: «TAKROR SHUBHASI» DARVOZASINI OPERATOR TASDIQLAY OLSIN.
//
// ⚠️  NEGA BU TESTLAR BOR. R6.8 serverga P0 darvozasini qo'ydi: 30 daqiqa
//     ichida AYNI mahsulot/miqdor/sabab-kodi bilan ikkinchi hisobdan
//     chiqarish `409 WRITEOFF_DUPLICATE_SUSPECTED` beradi va operatordan
//     `confirm_duplicate: true` so'raydi. Mobil ilova buni qo'llab-quvvatlaydi.
//
//     DESKTOP ESA QO'LLAB-QUVVATLAMAYDI. `Hisobdan.tsx:89` 409 ni oddiy
//     `catch` da ushlab, xom matnni ko'rsatadi va tasdiq varaqasini YOPADI.
//     Natijada desktop operatori 30 daqiqa ichida QONUNIY ikkinchi
//     chiqarishni UMUMAN bajara olmaydi — darvoza unga DEDUP bo'lib ko'rinadi.
//
// ⚠️  ENG MUHIM INVARIANT: qayta yuborishda `client_uuid` O'ZGARMASLIGI SHART.
//     U idempotentlik kaliti: agar birinchi so'rov AMALDA yozilgan bo'lsa
//     (javob yo'qolgan, server esa yozgan), ayni kalit bilan qayta yuborish
//     serverga `duplicate: true` qaytartiradi — ya'ni IKKI marta yozilmaydi.
//     Yangi kalit bu himoyani yo'q qilardi.
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hisobdan } from "@/screens/Hisobdan";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const LOTS = lotList([
  lot({ id: "l1", batch_number: "A-1", remaining_qty: 6, unit_cost: 12000 }),
]);

const DUP409 = {
  __status: 409,
  __headers: { "X-Error-Code": "WRITEOFF_DUPLICATE_SUSPECTED" },
  detail:
    "Bu hisobdan chiqarish shu filialda yaqinda allaqachon yozilgan. Agar bu " +
    "HAQIQATAN ikkinchi, alohida amal bo'lsa — tasdiqlang; aks holda qoldiq " +
    "ikki marta kamayadi.",
};

/** `/inventory/writeoff` javobini CHAQIRUVLAR KETMA-KETLIGI bo'yicha beradi. */
function writeoffSeq(...responses: any[]) {
  let i = 0;
  return () => responses[Math.min(i++, responses.length - 1)];
}

function mount(writeoffRes: any, over: Record<string, any> = {}) {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability(over)],
    [/\/lots\/batches/, LOTS],
    [/\/products\?/, [{ id: "p1", name: "Sut 1L", unit_code: "dona", stock: 10 }]],
    [/\/inventory\/writeoff/, writeoffRes],
  ]);
  renderApp(<Hisobdan />);
  return calls;
}

async function pickAndSubmit(u: ReturnType<typeof userEvent.setup>, qty = "2") {
  await u.type(screen.getByTestId("wo-product-input"), "Sut");
  await waitFor(() => screen.getByTestId("wo-product-opt-p1"), { timeout: 3000 });
  await u.click(screen.getByTestId("wo-product-opt-p1"));
  await waitFor(() => screen.getByTestId("wo-lot-l1"));
  await u.type(screen.getByTestId("wo-qty-l1"), qty);
  await u.click(screen.getByTestId("wo-submit"));
  // birinchi tasdiq (oddiy «chiqarasizmi?» varaqasi)
  await u.click(screen.getByTestId("confirm-ok"));
}

const wo = (calls: any[]) => calls.filter((c) => c.url.includes("/inventory/writeoff") && c.method === "POST");

describe("R6.9 — desktop: takror shubhasi darvozasi", () => {
  it("409 kelganda TUSHUNARLI tushuntirish va TASDIQLASH yo'li ko'rsatiladi", async () => {
    const u = userEvent.setup();
    const calls = mount(DUP409);
    await pickAndSubmit(u);

    await waitFor(() => expect(screen.getByTestId("wo-dup")).toBeInTheDocument());
    //  ⚠️  TASDIQ SERVER MATNIGA BOG'LANGAN, zaxira i18n matniga EMAS.
    //      Ilgari regex ikkala manbaga ham mos kelardi («ikki marta
    //      kamayadi» `lot.dupExplain` da ham bor), shu bois `dupMsg`
    //      butunlay bo'shatilsa ham test YASHIL qolardi — ya'ni
    //      tautologiya edi. Raqib tekshiruvi topdi.
    //      «Bu hisobdan chiqarish shu filialda» — FAQAT server javobida.
    expect(screen.getByTestId("wo-dup").textContent || "").toContain(
      "Bu hisobdan chiqarish shu filialda",
    );
    // Hali IKKINCHI so'rov KETMAGAN.
    expect(wo(calls)).toHaveLength(1);
  });

  it("oyna SOXTA KAFOLAT bermaydi — IKKINCHI yozuv yaratilishini AYTADI", async () => {
    //  ⚠️  R6.8 P1-A BILAN AYNI SINF. Ilgari uchinchi satr «agar birinchi
    //      urinish allaqachon yozilgan bo'lsa, u IKKI marta yozilmaydi»
    //      derdi. Bu SOXTA: server egizak so'rovini AYNI kalit bilan
    //      filtrlaydi (`inventory.py:311-312`), kalit dedup'i esa
    //      darvozadan OLDIN ishlaydi (`:427` -> `:443`, darvoza `:471`).
    //      Ya'ni 409 chiqqan HAR qanday holatda bu kalit bazada YO'Q —
    //      kafolat printsipial ravishda qo'llanilmaydi.
    const u = userEvent.setup();
    mount(DUP409);
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    const matn = screen.getByTestId("wo-dup").textContent || "";

    // Operator IKKINCHI yozuv bo'lishini bilishi SHART.
    expect(matn).toMatch(/IKKINCHI yozuv/i);
    expect(matn).toMatch(/qoldiq YANA kamayadi/i);
    // Va eski SOXTA kafolat QAYTIB KELMASIN.
    expect(matn).not.toMatch(/birinchi urinish allaqachon yozilgan/i);
  });

  it("TASDIQLANSA — AYNI client_uuid va AYNI tana, confirm_duplicate: true", async () => {
    const u = userEvent.setup();
    const calls = mount(writeoffSeq(DUP409, { ok: true }));
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    await u.click(screen.getByTestId("wo-dup-ok"));

    await waitFor(() => expect(wo(calls)).toHaveLength(2));
    const [birinchi, ikkinchi] = wo(calls);
    expect(ikkinchi.body.client_uuid).toBe(birinchi.body.client_uuid);
    expect(ikkinchi.body.product_id).toBe(birinchi.body.product_id);
    expect(ikkinchi.body.qty).toBe(birinchi.body.qty);
    expect(ikkinchi.body.reason).toBe(birinchi.body.reason);
    expect(ikkinchi.body.lots).toEqual(birinchi.body.lots);
    expect(ikkinchi.body.confirm_duplicate).toBe(true);
    // Birinchi so'rovda `confirm_duplicate` STANDART bo'yicha yoqilmagan.
    expect(birinchi.body.confirm_duplicate).toBeFalsy();
    await waitFor(() => expect(screen.getByTestId("writeoff-done")).toBeInTheDocument());
  });

  it("RAD ETILSA — boshqa so'rov ketmaydi va kalit SAQLANADI", async () => {
    const u = userEvent.setup();
    const calls = mount(writeoffSeq(DUP409, { ok: true }));
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    await u.click(screen.getByTestId("wo-dup-cancel"));

    expect(wo(calls)).toHaveLength(1);
    expect(screen.queryByTestId("writeoff-done")).toBeNull();

    // Kalit SAQLANGAN: ayni amalni qayta yuborganda server uchun u O'SHA amal.
    await u.click(screen.getByTestId("wo-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => expect(wo(calls)).toHaveLength(2));
    expect(wo(calls)[1].body.client_uuid).toBe(wo(calls)[0].body.client_uuid);
  });

  it("MUVAFFAQIYATLI yozuvda confirm_duplicate YUBORILMAYDI", async () => {
    const u = userEvent.setup();
    const calls = mount({ ok: true });
    await pickAndSubmit(u);
    await waitFor(() => expect(screen.getByTestId("writeoff-done")).toBeInTheDocument());
    expect(wo(calls)[0].body.confirm_duplicate).toBeFalsy();
    expect(screen.queryByTestId("wo-dup")).toBeNull();
  });

  it("tasdiqdan keyin server `duplicate: true` desa — MUVAFFAQIYAT deb AYTILMAYDI", async () => {
    const u = userEvent.setup();
    mount(writeoffSeq(DUP409, { ok: true, duplicate: true }));
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    await u.click(screen.getByTestId("wo-dup-ok"));

    //  ⚠️  Server «bu AYNI kalit, men hech narsa yozmadim» dedi. Ekran buni
    //      YASHIRMASLIGI kerak: operator qoldiq kamaymaganini BILISHI shart.
    await waitFor(() =>
      expect(screen.getByTestId("writeoff-error").textContent || "").toMatch(/allaqachon/i),
    );
    //  ⚠️  ENG MUHIM TASDIQ. Xato matni YETARLI EMAS: yashil «hisobdan
    //      chiqarildi» bayrog'i AYNI PAYTDA turса, operator qoldiq
    //      kamaygan deb o'ylaydi. Raqib tekshiruvi aynan shu holatni
    //      topdi — `setDone(...)` SHARTSIZ chaqirilardi.
    expect(screen.queryByTestId("writeoff-done")).toBeNull();
  });

  it("BOSHQA 409 (IDEMPOTENCY_KEY_REUSED) takror oynasini OCHMAYDI", async () => {
    const u = userEvent.setup();
    const calls = mount({
      __status: 409,
      __headers: { "X-Error-Code": "IDEMPOTENCY_KEY_REUSED" },
      detail: "IDEMPOTENCY_KEY_REUSED: bu kalit boshqa amal uchun band",
    });
    await pickAndSubmit(u);
    await waitFor(() => expect(screen.getByTestId("writeoff-error")).toBeInTheDocument());
    expect(screen.queryByTestId("wo-dup")).toBeNull();

    //  Kalit BAND — saqlash abadiy 409 halqasi bo'lardi, shu bois YANGILANADI.
    await u.click(screen.getByTestId("wo-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => expect(wo(calls)).toHaveLength(2));
    expect(wo(calls)[1].body.client_uuid).not.toBe(wo(calls)[0].body.client_uuid);
  });

  it("tasdiq so'rovi BOSHQA xato bersa — oyna YOPILADI, xato KO'RINADI", async () => {
    const u = userEvent.setup();
    mount(writeoffSeq(DUP409, { __status: 500, detail: "server ichki xatosi" }));
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    await u.click(screen.getByTestId("wo-dup-ok"));

    //  ⚠️  Oyna ochiq qolsa xato uning ORTIDA chizilardi va operator eng
    //      muhim ma'lumotni ko'rmasdi.
    await waitFor(() => expect(screen.queryByTestId("wo-dup")).toBeNull());
    expect(screen.getByTestId("writeoff-error").textContent || "").toMatch(/xato/i);
    expect(screen.queryByTestId("writeoff-done")).toBeNull();
  });

  it("ESKI muvaffaqiyat bayrog'i keyingi urinishda DARHOL tozalanadi", async () => {
    const u = userEvent.setup();
    mount(writeoffSeq({ ok: true }, DUP409));
    await pickAndSubmit(u, "2");
    await waitFor(() => expect(screen.getByTestId("writeoff-done")).toBeInTheDocument());

    //  Ikkinchi urinish 409 beradi — yashil bayroq QOLMASLIGI kerak.
    await u.type(screen.getByTestId("wo-qty-l1"), "1");
    await u.click(screen.getByTestId("wo-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("wo-dup"));
    expect(screen.queryByTestId("writeoff-done")).toBeNull();
  });

  it("tasdiq SO'ROVI ketayotganda qayta bosilsa IKKINCHI so'rov ketmaydi", async () => {
    const u = userEvent.setup();
    //  ⚠️  `mockApi` javobni BIR MARTA `await` qiladi (`util.tsx:28`), shu bois
    //      ikkinchi javob TO'G'RIDAN-TO'G'RI kutilayotgan `Promise` bo'lishi
    //      kerak. Uni yana bir funksiyaga o'rash javobni DARHOL tugatardi va
    //      test qo'riqchini umuman sinamasdi.
    let resolve!: (v: any) => void;
    const pending = new Promise((r) => (resolve = r));
    const calls = mount(writeoffSeq(DUP409, pending));
    await pickAndSubmit(u);
    await waitFor(() => screen.getByTestId("wo-dup"));
    await u.click(screen.getByTestId("wo-dup-ok"));
    await u.click(screen.getByTestId("wo-dup-ok")).catch(() => {});

    //  ⚠️  Ikkinchi so'rov HALI KETAYOTGAN paytda uchinchisi ketmasligi
    //      SHART. Bu `busy` qo'riqchisini (tugma `disabled` + `post()`
    //      ichidagi `setBusy(true)`) HAQIQATAN bosib o'tadi.
    expect(wo(calls)).toHaveLength(2);
    resolve({ ok: true });
    await waitFor(() => expect(screen.queryByTestId("wo-dup")).toBeNull());
    expect(wo(calls)).toHaveLength(2);
  });
});
