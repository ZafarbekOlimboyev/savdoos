// Chek matni: tozalash, kenglik o'lchash, so'z bo'yicha o'rash, tekislash.
//
// Nega o'zimiz: chekka tushadigan HAR satr (mahsulot nomi, do'kon nomi, footer — hammasi foydalanuvchi
// kiritgan) printerga BAYT bo'lib boradi. Boshqaruv belgisi (ESC, GS, DLE...) o'tib ketsa — printer
// buyrug'i (masalan pul qutisini ochish `ESC p`) bo'lib ishlaydi. Bidi/zero-width belgilar esa ekranda
// bir, qog'ozda boshqa narsa ko'rsatadi. Shu bois tozalash layout'ning birinchi qadami.

// \n dan boshqa barcha Cc (C0, DEL, C1) va Cf (bidi U+202A–202E/2066–2069, LRM/RLM, ZWSP/ZWNJ/ZWJ,
// BOM, soft hyphen, tag belgilari...) olib tashlanadi.
const STRIP_RE = /(?!\n)[\p{Cc}\p{Cf}]/gu;
const LONE_SURROGATE_RE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
const NEWLINE_RE = /\r\n|[\r\u2028\u2029]/g; // CRLF, CR, LS, PS
const SPACE_RE = /[\t\p{Zs}]/gu; // NBSP, tor bo'shliq va h.k. → oddiy bo'shliq (kod sahifasida bor)

/** Matnni chek uchun tozalaydi; `\n` saqlanadi (qatorga bo'lish uchun). */
export function cleanText(input: unknown): string {
  if (input === null || input === undefined) return "";
  let s = typeof input === "string" ? input : String(input);
  try {
    s = s.normalize("NFC"); // "и"+U+0306 → "й": kenglik va kod sahifasi bitta belgi ko'radi
  } catch {
    /* normalize yo'q muhit — o'zgarishsiz */
  }
  return s
    .replace(NEWLINE_RE, "\n")
    .replace(LONE_SURROGATE_RE, "?")
    .replace(SPACE_RE, " ")
    .replace(STRIP_RE, "")
    // "…" ESC/POS da "..." (3 bayt) bo'ladi — kenglik HTML va printerda bir xil bo'lsin deb shu yerda.
    .replace(/\u2026/g, "...");
}

/** Bir qatorli maydon: `\n` ham bo'shliqqa aylanadi. */
export function cleanLine(input: unknown): string {
  return cleanText(input).replace(/\n/g, " ").replace(/ {2,}/g, " ").trim();
}

// Keng (2 ustunli) belgilar: CJK, Hangul, to'liq kenglikdagi shakllar, emoji. Printer ularni baribir
// "?" (1 ustun) qiladi — 2 deb hisoblash HTML'da ham, qog'ozda ham satr sig'ishini kafolatlaydi.
function isWide(cp: number): boolean {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x1f000 && cp <= 0x1faff) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
  );
}

export function charWidth(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0;
  return isWide(cp) ? 2 : 1;
}

/** Monospace ustunlar soni (kod nuqtasi bo'yicha; keng belgi = 2). */
export function strWidth(s: string): number {
  let w = 0;
  for (const ch of s) w += charWidth(ch);
  return w;
}

/** So'zni `width` ustunlik bo'laklarga qattiq bo'ladi (kamida 1 belgi — cheksiz sikl bo'lmasin). */
function hardBreak(word: string, width: number): string[] {
  const out: string[] = [];
  let cur = "";
  let w = 0;
  for (const ch of word) {
    const cw = charWidth(ch);
    if (w + cw > width && cur) {
      out.push(cur);
      cur = "";
      w = 0;
    }
    cur += ch;
    w += cw;
  }
  if (cur) out.push(cur);
  return out;
}

/**
 * Tozalangan matnni `width` ustunga o'raydi: `\n` — majburiy qator, bo'shliqlar bo'yicha so'z o'rash,
 * kenglikdan uzun so'z qattiq bo'linadi. Bo'sh paragraf bo'sh qator bo'lib qoladi (shablondagi niyat).
 * Natijadagi HECH bir satr `width` dan uzun emas.
 */
export function wrapText(text: string, width: number): string[] {
  const w = Math.max(1, Math.floor(width));
  const out: string[] = [];
  for (const para of text.split("\n")) {
    const words = para.split(" ").filter((x) => x.length > 0);
    if (words.length === 0) {
      out.push("");
      continue;
    }
    let cur = "";
    for (const word of words) {
      const ww = strWidth(word);
      if (ww > w) {
        if (cur) out.push(cur);
        const parts = hardBreak(word, w);
        cur = parts.pop() ?? "";
        out.push(...parts);
      } else if (!cur) {
        cur = word;
      } else if (strWidth(cur) + 1 + ww <= w) {
        cur += " " + word;
      } else {
        out.push(cur);
        cur = word;
      }
    }
    out.push(cur);
  }
  return out;
}

/** Markazlash (o'ng tomon to'ldirilmaydi — ortiqcha bayt kerak emas). */
export function center(text: string, width: number): string {
  const pad = Math.max(0, Math.floor((width - strWidth(text)) / 2));
  return " ".repeat(pad) + text;
}

/**
 * Chap matn + o'ngga tekislangan qiymat. Sig'masa chap matn yuqori qatorlarga o'raladi va qiymat
 * oxirgi qatorga (joy bo'lsa) yoki alohida qatorga o'ngga tekislanadi — hech narsa kesilmaydi.
 */
export function pairLines(left: string, right: string, width: number, indent = 0): string[] {
  const ind = " ".repeat(Math.max(0, Math.min(indent, width - 1)));
  const rightParts = strWidth(right) > width ? hardBreak(right, width) : [right];
  const lastRight = rightParts.pop() ?? "";
  const rw = strWidth(lastRight);
  const lefts = left ? wrapText(left, width - ind.length).map((l) => ind + l) : [];
  const out: string[] = [];
  const last = lefts.pop();
  out.push(...lefts);
  const alignRight = (s: string) => " ".repeat(Math.max(0, width - strWidth(s))) + s;
  if (rightParts.length) {
    // Juda uzun qiymat (amalda bo'lmaydi) — chap alohida, qiymat bo'laklari o'ngda.
    if (last !== undefined) out.push(last);
    for (const p of rightParts) out.push(alignRight(p));
    out.push(alignRight(lastRight));
    return out;
  }
  if (last === undefined) {
    out.push(alignRight(lastRight));
  } else if (!lastRight) {
    out.push(last);
  } else if (strWidth(last) + 1 + rw <= width) {
    out.push(last + " ".repeat(width - strWidth(last) - rw) + lastRight);
  } else {
    out.push(last);
    out.push(alignRight(lastRight));
  }
  return out;
}
