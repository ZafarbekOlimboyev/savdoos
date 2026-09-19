// Chek uchun son formatlash — aniq o'nlik arifmetika (BigInt), float YO'Q.
//
// Nega: chekdagi har summa server bilan tiyinigacha mos bo'lishi shart. `0.1 + 0.2` kabi float xatosi
// yoki `Intl` ning lokalga bog'liq ajratgichi (NBSP) termal printer kod sahifasida "?" bo'lib chiqardi.
// Shu bois hamma narsa satr ↔ BigInt orqali, deterministik.
import type { ReceiptLang } from "./types";

interface Dec {
  m: bigint; // butun mantissa (ishorali)
  s: number; // kasr xonalari soni
}

// Faqat oddiy o'nlik yozuv (+ JS `String(number)` beradigan kichik eksponent: "1e-7").
const DEC_RE = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d{1,2}))?$/;
const MAX_DIGITS = 60;

function parse(v: string): Dec {
  const src = typeof v === "string" ? v.trim() : String(v);
  const r = DEC_RE.exec(src);
  if (!r || (!r[2] && !r[3])) throw new Error(`decimal: noto'g'ri qiymat "${src}"`);
  const frac = r[3] || "";
  let digits = (r[2] || "") + frac;
  let scale = frac.length - (r[4] ? parseInt(r[4], 10) : 0);
  if (scale < 0) {
    digits += "0".repeat(-scale);
    scale = 0;
  }
  if (digits.length > MAX_DIGITS) throw new Error(`decimal: juda uzun qiymat`);
  const m = BigInt(digits || "0");
  return { m: r[1] === "-" ? -m : m, s: scale };
}

const TEN = BigInt(10);
const ZERO = BigInt(0);
const TWO = BigInt(2);

function pow10(n: number): bigint {
  return TEN ** BigInt(n);
}

/** Mantissani boshqa masshtabga o'tkazadi; kamaytirishda ROUND_HALF_UP (noldan uzoqqa, Python kabi). */
function rescale(d: Dec, s: number): bigint {
  if (s >= d.s) return d.m * pow10(s - d.s);
  const f = pow10(d.s - s);
  const neg = d.m < ZERO;
  const a = neg ? -d.m : d.m;
  let q = a / f;
  if ((a % f) * TWO >= f) q += BigInt(1);
  return neg ? -q : q;
}

function render(m: bigint, s: number): string {
  const neg = m < ZERO;
  let a = (neg ? -m : m).toString();
  if (s > 0) {
    a = a.padStart(s + 1, "0");
    a = a.slice(0, a.length - s) + "." + a.slice(a.length - s);
  }
  return (neg ? "-" : "") + a;
}

/** Qiymat yaroqli o'nlik satrmi (tashlamaydi). */
export function isDecimal(v: unknown): v is string {
  if (typeof v !== "string") return false;
  try {
    parse(v);
    return true;
  } catch {
    return false;
  }
}

/** a × b, `scale` xonaga ROUND_HALF_UP. */
export function decMul(a: string, b: string, scale: number): string {
  const x = parse(a);
  const y = parse(b);
  return render(rescale({ m: x.m * y.m, s: x.s + y.s }, scale), scale);
}

function addSub(a: string, b: string, sign: 1 | -1, scale?: number): string {
  const x = parse(a);
  const y = parse(b);
  const common = Math.max(x.s, y.s);
  const m = rescale(x, common) + (sign === 1 ? rescale(y, common) : -rescale(y, common));
  const out = scale ?? common;
  return render(rescale({ m, s: common }, out), out);
}

/** a + b; natija masshtabi = `scale` yoki kirishlarning kattasi (aniq). */
export function decAdd(a: string, b: string, scale?: number): string {
  return addSub(a, b, 1, scale);
}

/** a − b; natija masshtabi = `scale` yoki kirishlarning kattasi (aniq). */
export function decSub(a: string, b: string, scale?: number): string {
  return addSub(a, b, -1, scale);
}

/** −1 | 0 | 1 (masshtabdan qat'i nazar: "1.50" == "1.5"). */
export function decCmp(a: string, b: string): -1 | 0 | 1 {
  const x = parse(a);
  const y = parse(b);
  const common = Math.max(x.s, y.s);
  const p = rescale(x, common);
  const q = rescale(y, common);
  return p < q ? -1 : p > q ? 1 : 0;
}

/** Qiymatni `scale` xonaga ROUND_HALF_UP bilan keltiradi ("0.35200000000000004" → "0.352"). */
export function decRound(v: string, scale: number): string {
  return render(rescale(parse(v), scale), scale);
}

/** Σ values (bo'sh ro'yxat → 0), `scale` xonada. */
export function decSum(values: readonly string[], scale: number): string {
  let acc = "0";
  for (const v of values) acc = decAdd(acc, v);
  return decRound(acc, scale);
}

export function decNeg(v: string): string {
  const d = parse(v);
  return render(-d.m, d.s);
}

export function decIsZero(v: string): boolean {
  return parse(v).m === ZERO;
}

// Minglik ajratgich — ODDIY bo'shliq (U+0020): NBSP kod sahifalarida yo'q yoki boshqa baytda.
function group(int: string): string {
  let out = "";
  for (let i = 0; i < int.length; i++) {
    if (i > 0 && (int.length - i) % 3 === 0) out += " ";
    out += int[i];
  }
  return out;
}

function human(m: bigint, s: number, trimZeros: boolean): string {
  const neg = m < ZERO;
  const plain = render(neg ? -m : m, s);
  const dot = plain.indexOf(".");
  const int = dot < 0 ? plain : plain.slice(0, dot);
  let frac = dot < 0 ? "" : plain.slice(dot + 1);
  if (trimZeros) frac = frac.replace(/0+$/, "");
  return (neg ? "-" : "") + group(int) + (frac ? "," + frac : "");
}

/**
 * Pul: "24224.00" → "24 224", "4224.50" → "4 224,50". Kasr faqat nolga teng bo'lmasa chiqadi.
 * Barcha tillarda bir xil ko'rinish (bo'shliq + vergul) — chek printeri uchun ASCII.
 * Yaroqsiz kirish → o'zi qaytadi (layout uni oldindan tekshirib, ogohlantirish qo'shadi).
 */
export function fmtMoney(v: string, _lang?: ReceiptLang): string {
  let d: Dec;
  try {
    d = parse(v);
  } catch {
    return String(v);
  }
  const m = rescale(d, 2);
  const whole = m % BigInt(100) === ZERO;
  return whole ? human(m / BigInt(100), 0, false) : human(m, 2, false);
}

const CURRENCY: Readonly<Record<ReceiptLang, string>> = Object.freeze({
  uz: "so'm",
  uzc: "сўм",
  ru: "сом",
  ky: "сом",
});

export function currencyLabel(lang: ReceiptLang): string {
  return CURRENCY[lang] ?? CURRENCY.ru;
}

/** Miqdor: tortiladigan → doim 3 xona ("0,352"); dona → ortiqcha nolsiz ("2", "1,5"). */
export function fmtQty(v: string, weighted: boolean): string {
  let d: Dec;
  try {
    d = parse(v);
  } catch {
    return String(v);
  }
  return human(rescale(d, 3), 3, !weighted);
}
