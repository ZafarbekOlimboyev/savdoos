// R7.1 — DESKTOP × HAQIQIY BACKEND SHARTNOMASI.
//
// NEGA BU FAYL BOR. `tests/receiving-lots.test.tsx` AI rozilik javobini O'ZI
// yasaydi va o'sha mock server qaytarmaydigan qiymatni o'z ichiga oladi
// (masalan `provider: "openai"` — serverning `PROVIDERS` ro'yxatida bunday
// provayder YO'Q). Mobil tomonda AYNI naqsh bitta P0 ga olib keldi: fikstura
// yashil, mahsulot buzilgan (R7.0 topdi).
//
// Shu bois bu fayl soxta javob ISHLATMAYDI. U `contracts/ai_consent.samples.json`
// ni o'qiydi — bu fayl HAQIQIY FastAPI serveridan
// `apps/server/tests/test_r71_ai_consent_contract.py` tomonidan yozib olinadi
// va o'sha test uni serverga qarab QULFLAYDI.
//
// Desktop (`packages/shared/src/screens/Purchases.tsx::ensureAiConsent`)
// `St` tipi orqali AYNAN oltita maydonni o'qiydi. TypeScript tipi RUNTIME'da
// hech narsani tekshirmaydi — ya'ni server biror maydonni tushirib qoldirsa,
// desktop JIMGINA `undefined` ni o'qiydi va dialog noto'g'ri ishlaydi
// (`!st.required` -> `true` -> rozilik UMUMAN so'ralmaydi). Bu test shu
// jimlikni buzadi.
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
      "BINOS_WRITE_AI_CONTRACT=1 pytest tests/test_r71_ai_consent_contract.py -k ETALON",
  );
}

interface Namuna {
  scenario: string;
  status: number;
  body: Record<string, unknown>;
}

/** `Purchases.tsx::ensureAiConsent` ichidagi `St` tipi — AYNAN shu maydonlar. */
const ST_MAYDONLARI: ReadonlyArray<readonly [string, "boolean" | "string?" | "number"]> = [
  ["required", "boolean"],
  ["granted", "boolean"],
  ["provider", "string?"],
  ["provider_name", "string?"],
  ["previous_provider", "string?"],
  ["disclosure_version", "number"],
];

function turMos(qiymat: unknown, tur: "boolean" | "string?" | "number"): boolean {
  if (tur === "boolean") return typeof qiymat === "boolean";
  if (tur === "number") return typeof qiymat === "number";
  return qiymat === null || typeof qiymat === "string";
}

const xom = JSON.parse(readFileSync(etalonYoli(), "utf-8")) as unknown[];
const namunalar = xom.slice(1) as Namuna[];
const ok = namunalar.filter((n) => n.status === 200);

describe("AI rozilik shartnomasi — desktop o'qiydigan maydonlar", () => {
  it("etalonda kamida oltita holat bor", () => {
    expect(namunalar.length).toBeGreaterThanOrEqual(6);
    expect(ok.length).toBeGreaterThanOrEqual(6);
  });

  for (const [maydon, tur] of ST_MAYDONLARI) {
    it(`har bir holatda "${maydon}" (${tur}) MAVJUD va turi to'g'ri`, () => {
      for (const n of ok) {
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

  it("desktop POST qiladigan `disclosure_version` server kutgan qiymat bilan bir xil", () => {
    // Desktop AYNAN `{ disclosure_version: st.disclosure_version }` yuboradi
    // (`Purchases.tsx:1248`). Server boshqa versiyani kutsa 409 beradi.
    const versiyalar = new Set(ok.map((n) => n.body.disclosure_version));
    expect(versiyalar.size, `server bir nechta versiya qaytardi: ${[...versiyalar]}`).toBe(1);
    expect([...versiyalar][0]).toBe(1);
  });

  it("demo rejimda `required` false va `provider` null — dialog ko'rsatilmaydi", () => {
    const demo = ok.find((n) => n.scenario === "demo");
    expect(demo, "etalonda `demo` holati yo'q").toBeTruthy();
    expect(demo!.body.required).toBe(false);
    expect(demo!.body.provider).toBeNull();
  });

  it("provayder nomlangan holatlarda `provider_name` BO'SH EMAS", () => {
    // Dialog matni `st.provider_name` ga tayanadi; bo'sh bo'lsa operator
    // ma'lumot QAYSI kompaniyaga ketayotganini ko'rmaydi.
    for (const n of ok) {
      if (n.body.required !== true) continue;
      expect(typeof n.body.provider).toBe("string");
      expect((n.body.provider as string).length, `"${n.scenario}": provider bo'sh`).toBeGreaterThan(0);
      expect(typeof n.body.provider_name).toBe("string");
      expect(
        (n.body.provider_name as string).length,
        `"${n.scenario}": provider_name bo'sh — dialog kimga yuborilayotganini aytmaydi`,
      ).toBeGreaterThan(0);
    }
  });
});
