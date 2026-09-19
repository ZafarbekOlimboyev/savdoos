import { describe, expect, it } from "vitest";
import { CODEPAGE_HIGH, TRANSLIT, cleanText, decodeText, encodeText, strWidth, type CodepageName } from "@/receipt";

// Phase 5F F1: ESC/POS kod sahifalari. Jadvallar standart cp866/cp1251 bilan; har kirill harfi
// ikki tomonga aylanadi; matndan HECH QACHON 0x20 dan kichik bayt chiqmaydi.

const ALL_CYRILLIC: string[] = (() => {
  const out: string[] = [];
  for (let cp = 0x0410; cp <= 0x044f; cp++) out.push(String.fromCodePoint(cp)); // А..я
  out.push("Ё", "ё"); // Ё ё
  return out;
})();

describe("kod sahifa jadvallari", () => {
  for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
    it(`${cp}: 128 ta element, takrorsiz, hech biri boshqaruv belgisi emas`, () => {
      const t = CODEPAGE_HIGH[cp];
      expect(t.length).toBe(128);
      const defined = t.filter((x) => x >= 0);
      expect(new Set(defined).size).toBe(defined.length);
      for (const x of defined) {
        expect(x >= 0x20 && !(x >= 0x7f && x <= 0x9f)).toBe(true);
      }
    });

    it(`${cp}: А–я, Ё, ё — har biri bitta baytga va qaytib o'ziga`, () => {
      for (const ch of ALL_CYRILLIC) {
        const enc = encodeText(ch, cp);
        expect(enc.lossy, ch).toEqual([]);
        expect(enc.bytes.length, ch).toBe(1);
        expect(enc.bytes[0], ch).toBeGreaterThanOrEqual(0x80);
        expect(decodeText(enc.bytes, cp), ch).toBe(ch);
      }
      const text = ALL_CYRILLIC.join("");
      expect(decodeText(encodeText(text, cp).bytes, cp)).toBe(text);
    });
  }

  it("cp866 ma'lum kod nuqtalari: А=0x80, а=0xA0, р=0xE0, Ё=0xF0, №=0xFC, ў=0xF7", () => {
    const b = (s: string) => encodeText(s, "cp866").bytes[0];
    expect(b("А")).toBe(0x80);
    expect(b("Я")).toBe(0x9f);
    expect(b("а")).toBe(0xa0);
    expect(b("п")).toBe(0xaf);
    expect(b("р")).toBe(0xe0);
    expect(b("я")).toBe(0xef);
    expect(b("Ё")).toBe(0xf0);
    expect(b("ё")).toBe(0xf1);
    expect(b("Ў")).toBe(0xf6);
    expect(b("ў")).toBe(0xf7);
    expect(b("°")).toBe(0xf8);
    expect(b("№")).toBe(0xfc);
    expect(b("─")).toBe(0xc4);
    expect(b("█")).toBe(0xdb);
  });

  it("cp1251 ma'lum kod nuqtalari: А=0xC0, а=0xE0, Ё=0xA8, ё=0xB8, №=0xB9, ў=0xA2", () => {
    const b = (s: string) => encodeText(s, "cp1251").bytes[0];
    expect(b("А")).toBe(0xc0);
    expect(b("Я")).toBe(0xdf);
    expect(b("а")).toBe(0xe0);
    expect(b("я")).toBe(0xff);
    expect(b("Ё")).toBe(0xa8);
    expect(b("ё")).toBe(0xb8);
    expect(b("№")).toBe(0xb9);
    expect(b("Ў")).toBe(0xa1);
    expect(b("ў")).toBe(0xa2);
    expect(b("«")).toBe(0xab);
    expect(b("»")).toBe(0xbb);
    expect(b("—")).toBe(0x97);
    expect(b("€")).toBe(0x88);
    expect(CODEPAGE_HIGH.cp1251[0x98 - 0x80]).toBe(-1); // aniqlanmagan
  });
});

describe("transliteratsiya va yo'qotish", () => {
  it("qirg'iz/o'zbek harflari yaqin harfga, № cp866 da jadvaldan, cp1251 da ham jadvaldan", () => {
    const t = (s: string, cp: CodepageName = "cp866") => decodeText(encodeText(s, cp).bytes, cp);
    expect(t("Қўғирчоқ ҳаммаёқда")).toBe("Кўгирчок хаммаёкда");
    expect(t("жаңы өрүк Үй Ң Ө")).toBe("жаны орук Уй Н О");
    expect(t("Oʻzbekiston gʻalla")).toBe("O'zbekiston g'alla");
    expect(t("“Quote” «a» – — …")).toBe('"Quote" "a" - - ...');
    expect(t("2 × 3 ✓")).toBe("2 x 3 v");
    expect(t("№ 5")).toBe("№ 5");
    expect(t("№ 5", "cp1251")).toBe("№ 5");
    expect(t("Ўзбек", "cp1251")).toBe("Ўзбек");
    // cp1251 da « » bor — to'g'ridan-to'g'ri
    expect(t("«a»", "cp1251")).toBe("«a»");
  });

  it("lotin diakritikasi asosiy harfga (1 belgi — kenglik saqlanadi)", () => {
    const enc = encodeText("Café Ürün Şeker", "cp866");
    expect(decodeText(enc.bytes, "cp866")).toBe("Cafe Urun Seker");
    expect(enc.lossy).toEqual([]);
  });

  it("noma'lum belgi → '?' va lossy:<belgi> (takrorsiz)", () => {
    const enc = encodeText("茶茶 ☃ x", "cp866");
    expect(decodeText(enc.bytes, "cp866")).toBe("?? ? x");
    expect(enc.lossy).toEqual(["茶", "☃"]);
  });

  it("boshqaruv belgilari hech qachon baytga o'tmaydi: ESC p, GS V, DLE DC4 → '?'", () => {
    const C = String.fromCharCode;
    const enc = encodeText(`a${C(0x1b, 0x70, 0x00)}b${C(0x1d, 0x56)}c${C(0x10, 0x14)}${C(0x7f)}${C(0x9b)}`, "cp866");
    expect(enc.bytes.every((x) => x >= 0x20 && x !== 0x7f)).toBe(true);
    expect(enc.lossy).toEqual(["U+001B", "U+0000", "U+001D", "U+0010", "U+0014", "U+007F", "U+009B"]);
  });

  it("BUTUN BMP bo'ylab: har qanday belgi uchun baytlar faqat 0x20–0x7E yoki 0x80–0xFF", () => {
    const MARK = /^\p{M}$/u;
    for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
      for (let c = 0; c <= 0xffff; c++) {
        if (c >= 0xd800 && c <= 0xdfff) continue;
        const ch = String.fromCharCode(c);
        const { bytes } = encodeText(ch, cp);
        for (const x of bytes) {
          if (x < 0x20 || x === 0x7f) throw new Error(`${cp}: U+${c.toString(16)} → 0x${x.toString(16)}`);
        }
        // Birlashuvchi belgi (kengligi 0) — 0 bayt; "…" cp866 da "..." (3); qolgani aynan 1.
        const want = MARK.test(ch) ? 0 : c === 0x2026 && cp === "cp866" ? 3 : 1;
        if (bytes.length !== want) throw new Error(`${cp}: U+${c.toString(16)} ${bytes.length} bayt (${want} kutilgan)`);
      }
    }
  });

  it("BUTUN BMP: tozalangan belgining printer bayti HECH QACHON layout kengligidan oshmaydi (satr qog'ozga sig'adi)", () => {
    for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
      for (let c = 0x20; c <= 0xffff; c++) {
        if (c >= 0xd800 && c <= 0xdfff) continue;
        const t = cleanText(String.fromCharCode(c));
        const n = encodeText(t, cp).bytes.length;
        if (n > strWidth(t)) throw new Error(`${cp}: U+${c.toString(16)} ${n} bayt > kenglik ${strWidth(t)}`);
      }
    }
  });

  it("o'zbek tutuq belgisining boshqa yozilishlari (´ ˊ ʹ ʽ ˈ ˋ) → ' (1 bayt, '?' emas)", () => {
    const C = String.fromCharCode;
    for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
      for (const a of [0x00b4, 0x02ca, 0x02b9, 0x02bd, 0x02c8, 0x02cb]) {
        const enc = encodeText(`O${C(a)}zbekiston g${C(a)}alla`, cp);
        expect(decodeText(enc.bytes, cp), `${cp} U+${a.toString(16)}`).toBe("O'zbekiston g'alla");
        expect(enc.lossy, `${cp} U+${a.toString(16)}`).toEqual([]);
        expect(TRANSLIT[C(a)]).toBe("'");
      }
    }
  });

  it("birlashuvchi urg'u U+0301 → baytsiz (asos harf qoladi); boshqa birlashuvchi belgi ham baytsiz, lossy'da", () => {
    const C = String.fromCharCode;
    for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
      const acute = encodeText(`ба${C(0x301)}лан`, cp); // kirill а + urg'u: oldindan tuzilgan shakli yo'q
      expect(decodeText(acute.bytes, cp)).toBe("балан");
      expect(acute.lossy).toEqual([]);
      const other = encodeText(`ы${C(0x308)}x`, cp);
      expect(decodeText(other.bytes, cp)).toBe("ыx");
      expect(other.lossy).toEqual(["U+0308"]);
    }
  });

  it("TRANSLIT qiymatlari o'zi kod sahifasida mavjud (ichma-ich '?' yo'q)", () => {
    for (const cp of ["cp866", "cp1251"] as CodepageName[]) {
      for (const v of Object.values(TRANSLIT)) {
        const enc = encodeText(v, cp);
        expect(enc.lossy, `${cp} ${v}`).toEqual([]);
      }
    }
  });
});
