import { describe, expect, it } from "vitest";
import { createWedge, isEditableTarget, WEDGE_MIN_LEN } from "@/lib/scanWedge";

// ═══ WEDGE HOLAT MASHINASI — SOF TESTLAR ═════════════════════════════════════
//
// Integratsiya testlari (`pos-hardware-scan.test.tsx`) butun ekranni yuritadi va
// shu sababli holat mashinasining CHEGARALARINI qo'pol o'lchaydi. Bu fayl uni
// yolg'iz, DOM'siz va vaqtsiz qulflaydi — har bir qoida o'zgartirilsa JIM
// o'tmasdan yiqiladi.

const push = (w: ReturnType<typeof createWedge>, keys: string[]) =>
  keys.map((k) => w.push(k));
const last = <T,>(a: T[]) => a[a.length - 1];

describe("createWedge — da'vo qilish chegaralari", () => {
  it("to'liq burst + Enter → barkod da'vo qilinadi", () => {
    const w = createWedge();
    const out = push(w, [..."4700040115745", "Enter"]);
    expect(out.slice(0, -1).every((x) => x === null)).toBe(true);
    expect(last(out)).toBe("4700040115745");
    expect(w.peek()).toBe("");
  });

  it("min-uzunlik chegarasi AYNAN qulflangan: minLen−1 → null, minLen → da'vo", () => {
    expect(WEDGE_MIN_LEN).toBe(4);
    const qisqa = createWedge();
    expect(last(push(qisqa, [..."123", "Enter"]))).toBeNull();
    const yetarli = createWedge();
    expect(last(push(yetarli, [..."1234", "Enter"]))).toBe("1234");
  });

  it("modifikatorlar burstni BUZMAYDI (skaner katta harf uchun Shift yuboradi)", () => {
    const w = createWedge();
    const out = push(w, ["Shift", "A", "Shift", "B", "1", "2", "3", "4", "Enter"]);
    expect(last(out)).toBe("AB1234");
  });

  it("`+`/`-`/`=`/`_` buferga TUSHMAYDI (POS yorliqlari o'g'irlanmasin)", () => {
    for (const k of ["+", "-", "=", "_"]) {
      const w = createWedge();
      w.push(k);
      expect(w.peek()).toBe("");
    }
  });
});

describe("createWedge — UZILGAN burst DA'VO QILINMAYDI (pul nuqsoni gardi)", () => {
  //  ⚠️  ADVERSARIAL KO'RIKDA O'LCHANGAN NUQSON. Ilgari burst yarmidagi
  //      `-` buferni jimgina tozalardi va `Enter` qolgan DUMNI da'vo qilardi:
  //      `ART-12-345678` etiketkasi `345678` bo'lib ketib, agar u BOSHQA
  //      mahsulotning barkodi bo'lsa — boshqa mahsulot sotilardi.
  it("`9988-1001` dumi («1001») da'vo QILINMAYDI", () => {
    const w = createWedge();
    const out = push(w, [..."9988", "-", ..."1001", "Enter"]);
    expect(last(out)).toBeNull();
    expect(w.peek()).toBe("");
  });

  it("`ART-12-345678` dumi («345678») da'vo QILINMAYDI", () => {
    const w = createWedge();
    //  `A`,`R`,`T` harflari yig'iladi, `-` uzadi — natija: HECH NARSA.
    expect(last(push(w, [..."ART", "-", ..."12", "-", ..."345678", "Enter"]))).toBeNull();
  });

  it("kirill sxemasi: harf O'RTADA bo'lsa dum da'vo QILINMAYDI", () => {
    const w = createWedge();
    //  `ф` — `BARCODE_CHAR` dan o'tmaydi (lotin harf/raqam emas). U O'RTADA
    //  bo'lsa burst uziladi va dum da'vo qilinmaydi.
    expect(last(push(w, [..."12", "ф", ..."345678", "Enter"]))).toBeNull();
  });

  it("kirill harfi BOSHIDA bo'lsa burst TOZA (server ham raqamsizni olib tashlaydi)", () => {
    const w = createWedge();
    //  ⚠️  Bu ATAYLAB toza: bo'sh buferdagi uzilish burstni ifloslatmaydi.
    //      Va bu TO'G'RI xulq — server barkodni saqlashda raqam bo'lmagan
    //      belgilarni olib tashlaydi (`products._norm_barcode`), ya'ni
    //      «АБ345678» etiketkasi bazada `345678` bo'lib turadi: dum AYNI
    //      mahsulotni topadi. Xavf faqat O'RTADAGI ajratuvchida.
    expect(last(push(w, ["ф", "и", ..."345678", "Enter"]))).toBe("345678");
  });

  it("Tab yoki F2 bilan uzilgan burst ham da'vo QILINMAYDI", () => {
    for (const brk of ["Tab", "F2", "Escape", "ArrowLeft"]) {
      const w = createWedge();
      expect(last(push(w, [..."4780", brk, ..."001234567", "Enter"]))).toBeNull();
    }
  });

  it("BO'SH buferdagi uzilish TOZA qoladi — skaner prefiksi skanni buzmaydi", () => {
    const w = createWedge();
    //  Ko'p skaner sozlanadigan prefiks yuboradi (`~`, STX…). U bo'sh buferga
    //  tushadi, ya'ni burstni «iflos» qilmasligi SHART.
    expect(last(push(w, ["~", ..."4700040115745", "Enter"]))).toBe("4700040115745");
  });

  it("`reset()` iflos bayrog'ini ham tozalaydi (keyingi skan toza)", () => {
    const w = createWedge();
    push(w, [..."9988", "-"]);          // iflos
    w.reset();
    expect(last(push(w, [..."1234", "Enter"]))).toBe("1234");
  });

  it("uzilgandan keyingi YANGI burst (Enter'dan so'ng) toza ishlaydi", () => {
    const w = createWedge();
    expect(last(push(w, [..."9988", "-", ..."1001", "Enter"]))).toBeNull();
    //  `Enter` bayroqni tozalaydi — keyingi skan jarima to'lamaydi.
    expect(last(push(w, [..."4700040115745", "Enter"]))).toBe("4700040115745");
  });
});

describe("isEditableTarget", () => {
  it("INPUT/TEXTAREA/SELECT va contentEditable — TAHRIRLANADIGAN", () => {
    for (const tag of ["input", "textarea", "select"]) {
      expect(isEditableTarget(document.createElement(tag))).toBe(true);
    }
    const ce = document.createElement("div");
    //  jsdom `isContentEditable` ni hisoblamaydi — xossani to'g'ridan qo'yamiz.
    Object.defineProperty(ce, "isContentEditable", { value: true });
    expect(isEditableTarget(ce)).toBe(true);
  });

  it("BODY/DIV/BUTTON — tahrirlanadigan EMAS (skaner yo'li shu yerda ishlaydi)", () => {
    expect(isEditableTarget(document.body)).toBe(false);
    expect(isEditableTarget(document.createElement("div"))).toBe(false);
    expect(isEditableTarget(document.createElement("button"))).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});
