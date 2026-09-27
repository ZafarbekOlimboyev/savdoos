// EAN-13 kodlash (standart jadvallar). Stikerdagi chiziqlar HAQIQIY: videodagi
// shtrix-kodni telefon bilan skanerlasa ham aynan promo mahsuloti chiqadi.

const L = ['0001101', '0011001', '0010011', '0111101', '0100011', '0110001', '0101111', '0111011', '0110111', '0001011'];
const G = ['0100111', '0110011', '0011011', '0100001', '0011101', '0111001', '0000101', '0010001', '0001001', '0010111'];
const R = L.map((p) => [...p].map((c) => (c === '0' ? '1' : '0')).join(''));
const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];

export function checkDigit(d12: string): number {
  const s = [...d12].reduce((acc, c, i) => acc + Number(c) * (i % 2 ? 3 : 1), 0);
  return (10 - (s % 10)) % 10;
}

/** 95 modulli bit qatori ("1" — qora chiziq). Nazorat raqami noto'g'ri bo'lsa xato. */
export function ean13Bits(code: string): string {
  if (!/^\d{13}$/.test(code)) throw new Error(`EAN-13 emas: ${code}`);
  if (checkDigit(code.slice(0, 12)) !== Number(code[12])) throw new Error(`EAN-13 nazorat raqami noto'g'ri: ${code}`);
  const d = [...code].map(Number);
  let bits = '101';
  for (let i = 1; i <= 6; i++) bits += (PARITY[d[0]][i - 1] === 'L' ? L : G)[d[i]];
  bits += '01010';
  for (let i = 7; i <= 12; i++) bits += R[d[i]];
  return bits + '101';
}

/** Chiziqlarni birlashtirilgan to'rtburchaklar sifatida qaytaradi (modul birligida). */
export function ean13Runs(code: string): Array<{ x: number; w: number; guard: boolean }> {
  const bits = ean13Bits(code);
  const guards = new Set<number>();
  for (const [a, b] of [[0, 3], [45, 50], [92, 95]]) for (let i = a; i < b; i++) guards.add(i);
  const runs: Array<{ x: number; w: number; guard: boolean }> = [];
  let i = 0;
  while (i < bits.length) {
    if (bits[i] !== '1') { i++; continue; }
    let j = i;
    while (j < bits.length && bits[j] === '1') j++;
    runs.push({ x: i, w: j - i, guard: guards.has(i) });
    i = j;
  }
  return runs;
}
