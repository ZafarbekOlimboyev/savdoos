// R7.2 — DESKTOP × KANONIK BACKEND SHARTNOMASI.
//
// NEGA BU FAYL BOR. `tests/receiving-lots.test.tsx` AI rozilik javobini O'ZI
// yasaydi. R7.1 gacha o'sha mock server qaytarmaydigan qiymatni ham o'z ichiga
// olardi (`provider: "openai"` — serverning `PROVIDERS` ro'yxatida yo'q,
// `revision`/`mode`/`protocol_version`/`disclosure_id` esa umuman yo'q edi).
// Mobil tomonda AYNI naqsh bitta P0 ga olib keldi (R7.0 topdi).
//
// Shu bois bu fayl soxta javob ISHLATMAYDI. U `contracts/ai_consent.samples.json`
// ni o'qiydi — bu fayl HAQIQIY FastAPI serveridan
// `apps/server/tests/test_r72_ai_consent_contract.py` tomonidan yozib olinadi
// va o'sha test uni serverga qarab QULFLAYDI.
//
// Desktop (`packages/shared/src/screens/Purchases.tsx::ensureAiConsent`)
// kanonik `AiReq` tipini o'qiydi va POST/skanda `revision`, `provider`,
// `disclosure_id`, `disclosure_version` ni QAYTARADI — kanonik
// `ConsentIn`/`ScanIn` da ular MAJBURIY. TypeScript tipi RUNTIME'da hech
// narsani tekshirmaydi, shu bois maydon yo'qolsa desktop jimgina `undefined`
// o'qib, dialogni umuman ko'rsatmay qo'yishi mumkin edi. Bu test shu jimlikni
// buzadi.
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

/** Etalonni topadi: joriy katalogdan yuqoriga chiqib boradi. */
function etalonYoli(): string {
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    const f = join(dir, "contracts", "ai_consent.samples.json");
    if (existsSync(f)) return f;
    const ota = dirname(dir);
    if (ota === dir) break;
    dir = ota;
  }
  throw new Error(
    "contracts/ai_consent.samples.json topilmadi. Serverda yozing: " +
      "BINOS_WRITE_AI_CONTRACT=1 pytest tests/test_r72_ai_consent_contract.py -k ETALON",
  );
}

interface Namuna {
  scenario: string;
  status: number;
  body: Record<string, unknown>;
}

type Tur = "boolean" | "string?" | "string" | "number";

/** `Purchases.tsx::ensureAiConsent` ichidagi `AiReq` tipi — AYNAN shu maydonlar. */
const AIREQ_MAYDONLARI: ReadonlyArray<readonly [string, Tur]> = [
  ["revision", "number"],
  ["mode", "string"],
  ["provider", "string?"],
  ["provider_name", "string?"],
  ["model", "string?"],
  ["disclosure_id", "string"],
  ["disclosure_version", "number"],
  ["protocol_version", "number"],
  ["required", "boolean"],
  ["granted", "boolean"],
  ["previous_provider", "string?"],
];

function turMos(qiymat: unknown, tur: Tur): boolean {
  if (tur === "boolean") return typeof qiymat === "boolean";
  if (tur === "number") return typeof qiymat === "number";
  if (tur === "string") return typeof qiymat === "string";
  return qiymat === null || typeof qiymat === "string";
}

const xom = JSON.parse(readFileSync(etalonYoli(), "utf-8")) as unknown[];
const shartnoma = (xom[0] as Record<string, Record<string, unknown>>).shartnoma;
const namunalar = xom.slice(1) as Namuna[];

/** Holat shaklidagi javoblar. `DELETE` kanonik backendda faqat `ok` qaytaradi. */
const holatlar = namunalar.filter(
  (n) => n.status === 200 && Object.prototype.hasOwnProperty.call(n.body, "mode"),
);

describe("kanonik AI shartnomasi — desktop o'qiydigan maydonlar", () => {
  it("etalon kanonik holat mashinasining har rejimini qamraydi", () => {
    const sahnalar = new Set(namunalar.map((n) => n.scenario));
    for (const kerak of ["paused", "demo", "active_rozilik_yoq", "active_berilgan",
      "provayder_ozgardi", "qaytarib_olindi"]) {
      expect(sahnalar.has(kerak), `etalonda "${kerak}" sahnasi yo'q`).toBe(true);
    }
    expect(holatlar.length).toBeGreaterThanOrEqual(4);
  });

  it("shartnoma e'loni kutilgan versiyalarda", () => {
    expect(shartnoma.protocol_version).toBe(2);
    expect(shartnoma.disclosure_version).toBe(1);
    expect(typeof shartnoma.disclosure_id).toBe("string");
    expect((shartnoma.disclosure_id as string).length).toBeGreaterThan(0);
  });

  for (const [maydon, tur] of AIREQ_MAYDONLARI) {
    it(`har bir holatda "${maydon}" (${tur}) MAVJUD va turi to'g'ri`, () => {
      for (const n of holatlar) {
        expect(
          Object.prototype.hasOwnProperty.call(n.body, maydon),
          `"${n.scenario}" holatida "${maydon}" YO'Q — desktop undefined o'qiydi`,
        ).toBe(true);
        expect(
          turMos(n.body[maydon], tur),
          `"${n.scenario}" holatida "${maydon}" turi noto'g'ri: ${JSON.stringify(n.body[maydon])}`,
        ).toBe(true);
      }
    });
  }

  it("desktop fail-closed tekshiruvi HAR holatda o'tadi", () => {
    // `ensureAiConsent` AYNAN shu shartlarni tekshiradi; biri buzilsa rasm
    // yuborilmaydi. Kanonik javob ularning HAMMASINI qanoatlantirishi kerak,
    // aks holda desktop ishlaydigan serverda ham fail-closed bo'lib qolardi.
    for (const n of holatlar) {
      const b = n.body as Record<string, any>;
      expect(b.protocol_version, n.scenario).toBe(2);
      expect(typeof b.revision, n.scenario).toBe("number");
      expect(b.revision, n.scenario).toBeGreaterThanOrEqual(1);
      expect(typeof b.disclosure_id, n.scenario).toBe("string");
      expect((b.disclosure_id as string).length, n.scenario).toBeGreaterThan(0);
      expect(b.disclosure_version, n.scenario).toBe(1);
      expect(typeof b.required, n.scenario).toBe("boolean");
      expect(typeof b.granted, n.scenario).toBe("boolean");
      expect(["active", "demo"], n.scenario).toContain(b.mode);
    }
  });

  it("PAUSED holati 503 — desktop uni xato sifatida ko'radi, holat sifatida EMAS", () => {
    const n = namunalar.find((x) => x.scenario === "paused")!;
    expect(n.status).toBe(503);
    // `mode: paused` HECH QACHON holat sifatida o'qilmaydi: `ensureAiConsent`
    // `mode in {active, demo}` ni talab qiladi va 503 `get()` da throw bo'ladi.
    expect(Object.prototype.hasOwnProperty.call(n.body, "mode")).toBe(false);
  });

  it("DELETE javobi faqat `ok` qaytaradi — holat emas", () => {
    const n = namunalar.find((x) => x.scenario === "qaytarib_olindi")!;
    expect(n.status).toBe(200);
    expect((n.body as Record<string, unknown>).ok).toBe(true);
    expect(Object.prototype.hasOwnProperty.call(n.body, "mode")).toBe(false);
  });

  it("demo rejimda provider/nom/model NULL — dialog ko'rsatilmaydi", () => {
    const demo = holatlar.find((n) => n.scenario === "demo")!;
    expect(demo.body.mode).toBe("demo");
    expect(demo.body.required).toBe(false);
    expect(demo.body.granted).toBe(false);
    expect(demo.body.provider).toBeNull();
    expect(demo.body.provider_name).toBeNull();
    expect(demo.body.model).toBeNull();
  });

  it("active rejimda provider, nom va model BO'SH EMAS", () => {
    for (const n of holatlar.filter((x) => x.body.required === true)) {
      expect(n.body.mode, n.scenario).toBe("active");
      expect(typeof n.body.provider, n.scenario).toBe("string");
      expect((n.body.provider as string).length, n.scenario).toBeGreaterThan(0);
      // Dialog matni `provider_name` ga tayanadi; bo'sh bo'lsa operator
      // ma'lumot QAYSI kompaniyaga ketayotganini ko'rmaydi.
      expect(typeof n.body.provider_name, n.scenario).toBe("string");
      expect((n.body.provider_name as string).length, n.scenario).toBeGreaterThan(0);
      expect(typeof n.body.model, n.scenario).toBe("string");
      expect((n.body.model as string).length, n.scenario).toBeGreaterThan(0);
    }
  });

  it("provayder o'zgarsa reviziya ham o'zgaradi va rozilik bekor bo'ladi", () => {
    const gemini = holatlar.find((n) => n.body.provider === "gemini")!;
    const anthropic = holatlar.find((n) => n.body.provider === "anthropic")!;
    expect(gemini.body.revision).not.toBe(anthropic.body.revision);
    expect(anthropic.body.granted).toBe(false);
    expect(anthropic.body.previous_provider).toBe("gemini");
  });

  it("desktop POST qiladigan to'rt maydon etalonning HAR holatida bor", () => {
    // `ensureAiConsent` AYNAN shu to'rtligini qaytaradi; kanonik `ConsentIn`
    // da ular MAJBURIY, ya'ni biri yo'q bo'lsa server 422 beradi.
    for (const n of holatlar) {
      for (const k of ["revision", "provider", "disclosure_id", "disclosure_version"]) {
        expect(
          Object.prototype.hasOwnProperty.call(n.body, k),
          `"${n.scenario}": POST uchun kerakli "${k}" yo'q`,
        ).toBe(true);
      }
    }
  });
});
