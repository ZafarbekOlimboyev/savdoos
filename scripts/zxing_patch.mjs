#!/usr/bin/env node
// Vendored ZXing 0.19.1 dagi `findGuardPattern` sirg'aluvchi oynasini tuzatadi.
//
// NUQSON. ZXing'ning 1D o'quvchilari qatorni "yugurish uzunliklari" bo'yicha
// surib boradi. Oyna mos kelmasa Java'da hisoblagichlar ikki pozitsiyaga
// SURILADI (`System.arraycopy(counters, 2, counters, 0, counterPosition-1)`).
// TS portining minifikatsiyalangan buildida bu `slice(2, length-1)` ga
// aylangan: 3 elementli massiv uchun natija BO'SH, ya'ni `counters[0]`
// `undefined` bo'lib qoladi. Keyingi hamma solishtirish `NaN` beradi va
// start-guard BOSHQA HECH QACHON topilmaydi.
//
// OQIBATI (o'lchangan, taxmin emas). Shtrix-kod faqat skanerlash qatorining
// ENG BOSHIDA turgandagina o'qiladi. Kesimga kodgacha bo'lgan qorong'i narsa
// (mahsulot, javon, soya) tushsa — o'qilmaydi. Do'konda bu deyarli HAR DOIM
// shunday: iPhone 16 Pro'da katta, tiniq EAN-13 o'qilmagani shundan.
//
// TUZATISH. Ikkala chaqiruv joyida (Code128 start-pattern va UPC/EAN guard)
// `slice` o'rniga Java bilan bir xil `copyWithin(0, 2, counterPosition+1)`.
// Massiv `Int32Array` — `slice` uni QISQARTIRADI ham, `copyWithin` esa joyida
// o'zgartiradi, ya'ni uzunlik saqlanadi.
//
//   node scripts/zxing_patch.mjs          — tuzatadi (idempotent)
//   node scripts/zxing_patch.mjs --check  — tuzatilganini tekshiradi (CI/test)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const VENDOR = path.join(ROOT, 'apps/mobile/web/vendor/zxing/zxing-0.19.1.min.js');

/** Aniq matn almashtirishlari: ikkisi ham topilishi SHART. */
export const PATCHES = [
  { nima: 'Code128Reader.findStartPattern',
    eski: 's+=i[0]+i[1],i=i.slice(2,i.length-1),i[n-1]=0,i[n]=0,n--',
    yangi: 's+=i[0]+i[1],i.copyWithin(0,2,n+1),i[n-1]=0,i[n]=0,n--' },
  { nima: 'UPCEANReader.findGuardPattern',
    eski: 'a+=i[0]+i[1];let t=i.slice(2,i.length-1);for(let e=0;e<o-1;e++)i[e]=t[e];i[o-1]=0,i[o]=0,o--',
    yangi: 'a+=i[0]+i[1];i.copyWithin(0,2,o+1);i[o-1]=0,i[o]=0,o--' },
];

export function holat(matn) {
  return PATCHES.map((p) => ({
    nima: p.nima,
    tuzatilgan: matn.includes(p.yangi),
    buzuq: matn.includes(p.eski),
  }));
}

function main() {
  const check = process.argv.includes('--check');
  let matn = fs.readFileSync(VENDOR, 'utf8');
  if (check) {
    const h = holat(matn);
    for (const x of h) console.log(`${x.tuzatilgan ? 'OK  ' : 'YO‘Q'} ${x.nima}${x.buzuq ? '  (BUZUQ IDIOMA HALI BOR)' : ''}`);
    process.exit(h.every((x) => x.tuzatilgan && !x.buzuq) ? 0 : 1);
  }
  for (const p of PATCHES) {
    if (matn.includes(p.yangi)) { console.log(`o‘zgarishsiz: ${p.nima} allaqachon tuzatilgan`); continue; }
    if (!matn.includes(p.eski)) throw new Error(`TO‘XTADI: ${p.nima} uchun kutilgan matn topilmadi — vendor build boshqacha`);
    matn = matn.replace(p.eski, p.yangi);
    console.log(`tuzatildi: ${p.nima}`);
  }
  fs.writeFileSync(VENDOR, matn);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
