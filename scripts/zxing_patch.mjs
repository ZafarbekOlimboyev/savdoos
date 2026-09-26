#!/usr/bin/env node
// Yuklanadigan ZXing faylini ASL npm artefaktidan qayta yasaydi.
//
//   yuklanadigan = apps/mobile/test/fixtures/zxing/zxing-0.19.1.upstream.min.js
//                  + apps/mobile/test/fixtures/zxing/patches.json dagi yamoqlar
//
// Yamoqning MAZMUNI va NEGA kerakligi `patches.json` da (bitta manba: bu skript
// ham, Dart testi ham, vitest ham o'shani o'qiydi). Qisqasi: minifikatsiyalangan
// 0.19.1 build'da guard-naqsh oynasi buzuq surilib, kod qatorning boshida
// bo'lmasa shtrix-kod UMUMAN topilmaydi.
//
//   node scripts/zxing_patch.mjs          — qayta yasaydi (idempotent)
//   node scripts/zxing_patch.mjs --check  — yuklanadigan fayl kutilganidek ekanini tekshiradi
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FIX = path.join(ROOT, 'apps/mobile/test/fixtures/zxing');
export const SPEC = JSON.parse(fs.readFileSync(path.join(FIX, 'patches.json'), 'utf8'));
export const UPSTREAM = path.join(FIX, SPEC.upstream_file);
export const VENDOR = path.join(ROOT, SPEC.shipped_file);
export const PATCHES = SPEC.patches;

/** Asl matndan yuklanadigan matnni yasaydi. Har bir yamoq topilishi SHART. */
export function yasa(asl) {
  let matn = asl;
  for (const p of PATCHES) {
    if (!matn.includes(p.eski)) throw new Error(`TO‘XTADI: ${p.nima} uchun kutilgan matn asl faylda yo‘q`);
    matn = matn.replace(p.eski, p.yangi);
  }
  return matn;
}

export function holat(matn) {
  return PATCHES.map((p) => ({ nima: p.nima, tuzatilgan: matn.includes(p.yangi), buzuq: matn.includes(p.eski) }));
}

function main() {
  const asl = fs.readFileSync(UPSTREAM, 'utf8');
  const kutilgan = yasa(asl);
  if (process.argv.includes('--check')) {
    const bor = fs.readFileSync(VENDOR, 'utf8');
    if (bor === kutilgan) { console.log('OK: yuklanadigan fayl = asl artefakt + hujjatlashtirilgan yamoqlar'); process.exit(0); }
    console.error('TO‘XTADI: yuklanadigan fayl kutilganidan farq qiladi — `node scripts/zxing_patch.mjs` ni yurgizing');
    for (const x of holat(bor)) console.error(`  ${x.tuzatilgan ? 'tuzatilgan' : 'TUZATILMAGAN'} ${x.nima}${x.buzuq ? ' (buzuq idioma bor)' : ''}`);
    process.exit(1);
  }
  fs.writeFileSync(VENDOR, kutilgan);
  console.log(`yasaldi: ${SPEC.shipped_file}  (${PATCHES.length} yamoq)`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
