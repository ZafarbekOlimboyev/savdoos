// CODE128 (faqat B to'plami) — modullar satri ("1" = qora modul). Faqat OFLAYN namuna chek uchun:
// haqiqiy chekda modullarni server hisoblaydi (DTO `barcode.modules`).

// Qiymat 0..106 → chiziq/bo'shliq kengliklari (b s b s b s; stop 7 element). ISO/IEC 15417 jadvali.
export const CODE128_WIDTHS: readonly string[] = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
  "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
  "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
  "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
  "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
  "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
  "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
  "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
  "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
];

const START_B = 104;
const STOP = 106;

function modulesOf(value: number): string {
  const w = CODE128_WIDTHS[value];
  let s = "";
  for (let i = 0; i < w.length; i++) s += (i % 2 === 0 ? "1" : "0").repeat(Number(w[i]));
  return s;
}

/** B to'plami: ASCII 0x20–0x7E, 1..64 belgi. Boshqa kirish → null (namuna shtrix-kodsiz chiqadi). */
export function code128Modules(payload: string): string | null {
  if (typeof payload !== "string" || !/^[\x20-\x7e]{1,64}$/.test(payload)) return null;
  const values = [START_B];
  for (let i = 0; i < payload.length; i++) values.push(payload.charCodeAt(i) - 32);
  let sum = START_B;
  for (let i = 1; i < values.length; i++) sum += values[i] * i;
  values.push(sum % 103, STOP);
  return values.map(modulesOf).join("");
}
