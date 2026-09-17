import { afterEach, describe, expect, it, vi } from "vitest";
import { useLang } from "@/store/lang";
import { translateLotError } from "@/lib/serverErrorsLots";
import { api } from "@/lib/api";

// Phase 5B: sotuv va qarzni yopish darvozalari endi xom istisno matni (UUID, `≠`,
// `[SQL: …]`) o'rniga ANIQ matn yuboradi; qaysi darvoza ekanini `X-Error-Code`
// aytadi. Matnlar server bilan AYNAN mos (`apps/server/tests/test_lot_error_texts.py`).
const SALE =
  "Savdoni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.";
const RESOLVE =
  "Qarzni yopib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.";
const fefo = (name: string) =>
  `'${name}': sotuvga yaroqli partiya yetarli emas (kerak 5.000, yaroqli 2.000). ` +
  "Muddati o'tgan yoki hisobga olinmagan tovar bo'lishi mumkin — inventarizatsiya qiling.";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Partiya darvozasi matnlari tarjima qilinadi", () => {
  it("sotuv darvozasi: ru va uzc, uz da null (asl matn allaqachon o'zbekcha)", () => {
    useLang.getState().set("ru");
    expect(translateLotError(SALE)).toBe(
      "Продажа не записана — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.");
    useLang.getState().set("uzc");
    expect(translateLotError(SALE)).toBe(
      "Савдони ёзиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.");
    useLang.getState().set("uz");
    expect(translateLotError(SALE)).toBeNull();
  });

  it("qarzni yopish darvozasi: ru va uzc, uz da null", () => {
    useLang.getState().set("ru");
    expect(translateLotError(RESOLVE)).toBe(
      "Долг не закрыт — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.");
    useLang.getState().set("uzc");
    expect(translateLotError(RESOLVE)).toBe(
      "Қарзни ёпиб бўлмади — партия ва қолдиқ мос келмади. Амал БАЖАРИЛМАДИ; қўллаб-қувватлашга мурожаат қилинг.");
    useLang.getState().set("uz");
    expect(translateLotError(RESOLVE)).toBeNull();
  });

  it("FEFO rad etishi: mahsulot nomida «: » bo'lsa ham to'liq tarjima, nom o'zgarmaydi", () => {
    useLang.getState().set("ru");
    const ru = translateLotError(fefo("Sok: olma 1L"));
    expect(ru).toBe(
      "«Sok: olma 1L»: годных к продаже партий недостаточно (нужно 5.000, годных 2.000). " +
      "Возможно, товар просрочен или не учтён — проведите пересчёт.");
    useLang.getState().set("uzc");
    expect(translateLotError(fefo("Sok: olma 1L"))).toContain("«Sok: olma 1L»: сотувга яроқли партия етарли эмас");
    useLang.getState().set("uz");
    expect(translateLotError(fefo("Sok: olma 1L"))).toBeNull();
  });
});

describe("api(): barqaror xato kodi `X-Error-Code` dan", () => {
  function stub(status: number, detail: string, headers: Record<string, string> = {}) {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail }), {
      status, headers: { "Content-Type": "application/json", ...headers },
    })));
  }

  it("sarlavha bo'lsa err.code o'rnatiladi, matn esa tarjima qilinadi", async () => {
    useLang.getState().set("ru");
    stub(409, SALE, { "X-Error-Code": "LOT_INVARIANT_BROKEN" });
    const err: any = await api("/sales", { method: "POST", body: "{}" }).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBe(409);
    expect(err.code).toBe("LOT_INVARIANT_BROKEN");
    expect(err.message).toBe(
      "Продажа не записана — партии и остаток не сходятся. Операция НЕ выполнена; обратитесь в поддержку.");
  });

  it("sarlavha bo'lmasa (eski server) err.code undefined — xulq o'zgarmagan", async () => {
    useLang.getState().set("ru");
    stub(409, "Narxlar yangilandi — savat qayta hisoblandi, tekshirib qayta urining");
    const err: any = await api("/sales", { method: "POST", body: "{}" }).catch((e) => e);
    expect(err.status).toBe(409);
    expect(err.code).toBeUndefined();
  });
});
