// ESC/POS kod sahifalari: cp866 (Epson "PC866 Cyrillic #2", ESC t 17) va cp1251 (WPC1251).
// Yuqori yarim (0x80–0xFF) to'liq jadval; pastki yarim — ASCII 0x20–0x7E o'zi.
//
// ⚠️  Matndan HECH QACHON 0x20 dan kichik bayt chiqmaydi: jadvalda yo'q belgi → transliteratsiya →
//     (lotin diakritikasi bo'lsa) asosiy harf → aks holda "?" va `lossy:<belgi>` ogohlantirishi.
//     Printer buyrug'i matn ichidan kirib kela olmasligining kafolati shu.

import { isMark } from "./text";

export type CodepageName = "cp866" | "cp1251";

// cp866: 0x80–0xFF, har element — shu baytning Unicode kod nuqtasi.
const CP866_HIGH: readonly number[] = [
  // 0x80–0x9F: А–Я
  0x0410, 0x0411, 0x0412, 0x0413, 0x0414, 0x0415, 0x0416, 0x0417,
  0x0418, 0x0419, 0x041a, 0x041b, 0x041c, 0x041d, 0x041e, 0x041f,
  0x0420, 0x0421, 0x0422, 0x0423, 0x0424, 0x0425, 0x0426, 0x0427,
  0x0428, 0x0429, 0x042a, 0x042b, 0x042c, 0x042d, 0x042e, 0x042f,
  // 0xA0–0xAF: а–п
  0x0430, 0x0431, 0x0432, 0x0433, 0x0434, 0x0435, 0x0436, 0x0437,
  0x0438, 0x0439, 0x043a, 0x043b, 0x043c, 0x043d, 0x043e, 0x043f,
  // 0xB0–0xDF: psevdografika
  0x2591, 0x2592, 0x2593, 0x2502, 0x2524, 0x2561, 0x2562, 0x2556,
  0x2555, 0x2563, 0x2551, 0x2557, 0x255d, 0x255c, 0x255b, 0x2510,
  0x2514, 0x2534, 0x252c, 0x251c, 0x2500, 0x253c, 0x255e, 0x255f,
  0x255a, 0x2554, 0x2569, 0x2566, 0x2560, 0x2550, 0x256c, 0x2567,
  0x2568, 0x2564, 0x2565, 0x2559, 0x2558, 0x2552, 0x2553, 0x256b,
  0x256a, 0x2518, 0x250c, 0x2588, 0x2584, 0x258c, 0x2590, 0x2580,
  // 0xE0–0xEF: р–я
  0x0440, 0x0441, 0x0442, 0x0443, 0x0444, 0x0445, 0x0446, 0x0447,
  0x0448, 0x0449, 0x044a, 0x044b, 0x044c, 0x044d, 0x044e, 0x044f,
  // 0xF0–0xFF: Ё ё Є є Ї ї Ў ў ° ∙ · √ № ¤ ■ NBSP
  0x0401, 0x0451, 0x0404, 0x0454, 0x0407, 0x0457, 0x040e, 0x045e,
  0x00b0, 0x2219, 0x00b7, 0x221a, 0x2116, 0x00a4, 0x25a0, 0x00a0,
];

// cp1251: 0x80–0xFF; 0x98 — aniqlanmagan (−1).
const CP1251_HIGH: readonly number[] = [
  // 0x80–0x8F
  0x0402, 0x0403, 0x201a, 0x0453, 0x201e, 0x2026, 0x2020, 0x2021,
  0x20ac, 0x2030, 0x0409, 0x2039, 0x040a, 0x040c, 0x040b, 0x040f,
  // 0x90–0x9F
  0x0452, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014,
  -1, 0x2122, 0x0459, 0x203a, 0x045a, 0x045c, 0x045b, 0x045f,
  // 0xA0–0xAF
  0x00a0, 0x040e, 0x045e, 0x0408, 0x00a4, 0x0490, 0x00a6, 0x00a7,
  0x0401, 0x00a9, 0x0404, 0x00ab, 0x00ac, 0x00ad, 0x00ae, 0x0407,
  // 0xB0–0xBF
  0x00b0, 0x00b1, 0x0406, 0x0456, 0x0491, 0x00b5, 0x00b6, 0x00b7,
  0x0451, 0x2116, 0x0454, 0x00bb, 0x0458, 0x0405, 0x0455, 0x0457,
  // 0xC0–0xDF: А–Я
  0x0410, 0x0411, 0x0412, 0x0413, 0x0414, 0x0415, 0x0416, 0x0417,
  0x0418, 0x0419, 0x041a, 0x041b, 0x041c, 0x041d, 0x041e, 0x041f,
  0x0420, 0x0421, 0x0422, 0x0423, 0x0424, 0x0425, 0x0426, 0x0427,
  0x0428, 0x0429, 0x042a, 0x042b, 0x042c, 0x042d, 0x042e, 0x042f,
  // 0xE0–0xFF: а–я
  0x0430, 0x0431, 0x0432, 0x0433, 0x0434, 0x0435, 0x0436, 0x0437,
  0x0438, 0x0439, 0x043a, 0x043b, 0x043c, 0x043d, 0x043e, 0x043f,
  0x0440, 0x0441, 0x0442, 0x0443, 0x0444, 0x0445, 0x0446, 0x0447,
  0x0448, 0x0449, 0x044a, 0x044b, 0x044c, 0x044d, 0x044e, 0x044f,
];

export const CODEPAGE_HIGH: Readonly<Record<CodepageName, readonly number[]>> = Object.freeze({
  cp866: CP866_HIGH,
  cp1251: CP1251_HIGH,
});

function buildEncode(high: readonly number[]): ReadonlyMap<number, number> {
  const m = new Map<number, number>();
  high.forEach((cp, i) => {
    if (cp >= 0) m.set(cp, 0x80 + i);
  });
  return m;
}

const ENCODE: Readonly<Record<CodepageName, ReadonlyMap<number, number>>> = {
  cp866: buildEncode(CP866_HIGH),
  cp1251: buildEncode(CP1251_HIGH),
};

/**
 * Kod sahifasida yo'q belgilar uchun transliteratsiya (SPEC §6). Jadvalda BOR belgi (masalan ў cp866 da
 * 0xF7, № cp1251 da 0xB9) jadvaldan olinadi — bu ro'yxat faqat yo'qlari uchun ishlaydi.
 * "…" → "..." dan tashqari hammasi 1 belgi: layout kengligi buzilmasin (… layout'da oldindan almashadi);
 * birlashuvchi urg'u (kengligi 0) → "" (0 bayt).
 */
// Kalitlar \u bilan: manba faylidagi ko'zga o'xshash belgilar (ʻ/‘, –/‐) adashmasin.
export const TRANSLIT: Readonly<Record<string, string>> = Object.freeze({
  "ў": "у", "Ў": "У", // ў→у Ў→У
  "қ": "к", "Қ": "К", // қ→к Қ→К
  "ғ": "г", "Ғ": "Г", // ғ→г Ғ→Г
  "ҳ": "х", "Ҳ": "Х", // ҳ→х Ҳ→Х
  "ң": "н", "Ң": "Н", // ң→н Ң→Н
  "ө": "о", "Ө": "О", // ө→о Ө→О
  "ү": "у", "Ү": "У", // ү→у Ү→У
  "ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "′": "'", // ʻ ʼ ‘ ’ ′
  // O'zbek o'/g' tutuq belgisining boshqa yozilishlari: ´ ˊ ʹ ʽ ˈ ˋ (hammasi 1 belgi → 1 bayt).
  "\u00b4": "'", "\u02ca": "'", "\u02b9": "'", "\u02bd": "'", "\u02c8": "'", "\u02cb": "'",
  // Birlashuvchi urg'u (U+0301): kenglik modelida 0 ustun — baytsiz (asos harf qoladi).
  "\u0301": "",
  "‚": ",", // ‚
  "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"', // “ ” „ « » ″
  "–": "-", "—": "-", "‐": "-", "‑": "-", "‒": "-", "−": "-", // – — ‐ ‑ ‒ −
  "…": "...", // …
  "№": "N", // №
  "×": "x", // ×
  "✓": "v", // ✓
  "•": "*", // •
});

export interface EncodedText {
  bytes: number[];
  /** "?" bilan almashgan yoki tashlab yuborilgan (birlashuvchi) belgilar (takrorsiz, uchragan tartibda). */
  lossy: string[];
}

/** Ko'rinmas/boshqaruv/birlashuvchi belgi ogohlantirishda o'qiladigan ko'rinishda (U+001B). */
function describe(ch: string): string {
  const cp = ch.codePointAt(0) ?? 0;
  if (cp < 0x20 || (cp >= 0x7f && cp <= 0x9f) || cp === 0x2028 || cp === 0x2029 || isMark(ch)) {
    return "U+" + cp.toString(16).toUpperCase().padStart(4, "0");
  }
  return ch;
}

function lookup(ch: string, map: ReadonlyMap<number, number>): number | null {
  const cp = ch.codePointAt(0) ?? 0;
  if (cp >= 0x20 && cp <= 0x7e) return cp;
  const b = map.get(cp);
  return b === undefined ? null : b;
}

/** Matnni tanlangan kod sahifasiga kodlaydi. Chiqish baytlari faqat 0x20–0x7E va 0x80–0xFF. */
export function encodeText(text: string, cp: CodepageName): EncodedText {
  const map = ENCODE[cp] ?? ENCODE.cp866;
  const bytes: number[] = [];
  const lossy: string[] = [];
  for (const ch of text) {
    const direct = lookup(ch, map);
    if (direct !== null) {
      bytes.push(direct);
      continue;
    }
    const tr = TRANSLIT[ch];
    if (tr !== undefined) {
      for (const t of tr) {
        const b = lookup(t, map);
        bytes.push(b === null ? 0x3f : b);
      }
      continue;
    }
    // Qolgan birlashuvchi belgi (kengligi 0) — baytsiz: "?" qo'shilsa satr layout kengligidan oshardi.
    if (isMark(ch)) {
      const d = describe(ch);
      if (!lossy.includes(d)) lossy.push(d);
      continue;
    }
    // Lotin diakritikasi (é, ü, ş...) — asosiy ASCII harf (1 belgi, kenglik saqlanadi).
    let base = "";
    try {
      base = ch.normalize("NFD").charAt(0);
    } catch {
      base = "";
    }
    const bb = base && base !== ch ? lookup(base, map) : null;
    if (bb !== null && bb >= 0x20 && bb <= 0x7e) {
      bytes.push(bb);
      continue;
    }
    bytes.push(0x3f); // "?"
    const d = describe(ch);
    if (!lossy.includes(d)) lossy.push(d);
  }
  return { bytes, lossy };
}

/** Baytlarni qayta matnga (sinov va inson o'qiydigan golden uchun). */
export function decodeText(bytes: ArrayLike<number>, cp: CodepageName): string {
  const high = CODEPAGE_HIGH[cp] ?? CP866_HIGH;
  let s = "";
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i];
    if (b >= 0x20 && b <= 0x7e) s += String.fromCharCode(b);
    else if (b >= 0x80 && high[b - 0x80] >= 0) s += String.fromCodePoint(high[b - 0x80]);
    else s += "�";
  }
  return s;
}
