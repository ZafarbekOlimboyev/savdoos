// Base64 — `atob`/`Buffer` ga suyanmasdan (Electron main, brauzer va jsdom'da bir xil ishlashi uchun).

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const LOOKUP: Int16Array = (() => {
  const t = new Int16Array(128).fill(-1);
  for (let i = 0; i < ALPHABET.length; i++) t[ALPHABET.charCodeAt(i)] = i;
  return t;
})();

const B64_RE = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

/** Qat'iy base64 (bo'shliqsiz, to'g'ri to'ldirilgan). */
export function isBase64(s: unknown): s is string {
  return typeof s === "string" && B64_RE.test(s);
}

/** Dekodlashdan OLDIN bayt uzunligi (logo raster o'lchamini tekshirish uchun). */
export function base64DecodedLength(s: string): number {
  if (!s) return 0;
  const pad = s.endsWith("==") ? 2 : s.endsWith("=") ? 1 : 0;
  return (s.length / 4) * 3 - pad;
}

/** Yaroqsiz kirishda null (tashlamaydi). */
export function base64Decode(s: string): Uint8Array | null {
  if (!isBase64(s)) return null;
  const out = new Uint8Array(base64DecodedLength(s));
  let o = 0;
  for (let i = 0; i < s.length; i += 4) {
    const a = LOOKUP[s.charCodeAt(i)];
    const b = LOOKUP[s.charCodeAt(i + 1)];
    const c = s[i + 2] === "=" ? 0 : LOOKUP[s.charCodeAt(i + 2)];
    const d = s[i + 3] === "=" ? 0 : LOOKUP[s.charCodeAt(i + 3)];
    const n = (a << 18) | (b << 12) | (c << 6) | d;
    if (o < out.length) out[o++] = (n >> 16) & 0xff;
    if (o < out.length) out[o++] = (n >> 8) & 0xff;
    if (o < out.length) out[o++] = n & 0xff;
  }
  return out;
}

export function base64Encode(bytes: ArrayLike<number>): string {
  let s = "";
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    s += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + ALPHABET[n & 63];
  }
  const rest = bytes.length - i;
  if (rest === 1) {
    const n = bytes[i] << 16;
    s += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + "==";
  } else if (rest === 2) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
    s += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + "=";
  }
  return s;
}
