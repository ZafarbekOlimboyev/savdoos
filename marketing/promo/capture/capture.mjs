// BinOS promo: HAQIQIY POS ekranini deterministik holatlarda suratga oladi.
//
//   1) <venv python> capture/promo_backend.py            (lokal, sintetik baza)
//   2) apps/pos: npx vite --config vite.preview.config.ts --port 5199
//   3) node capture/capture.mjs
//
// Natija: public/ui/pos/state-N.png (1920x1080 CSS, DSF 2 → 3840x2160) va
// public/ui/pos/manifest.json — savat qatorlari, JAMI, qidiruv maydoni va h.k.
// koordinatalari DOM'dan o'qiladi (qo'lda o'lchanmaydi), shu bois video
// "yamoqlari" haqiqiy piksellarga aniq tushadi.
//
// ⚠️  FAQAT LOKAL. POS manzili localhost bo'lmasa yoki sahifada promo dataset
//     mahsuloti ko'rinmasa TO'XTAYDI — boshqa (masalan real do'kon) ma'lumotini
//     reklamaga tushirish mumkin emas.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_BASE = path.resolve(HERE, '../public/ui');
const POS = process.env.PROMO_POS_URL || 'http://localhost:5199';
if (!/^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(POS)) throw new Error(`TO'XTADI: POS lokal emas: ${POS}`);
const DSF = 2;
// Reklama tili: uz (asosiy) | ru | ky | uzc — POS o'zi qo'llaydigan tillar.
const LANG = process.env.PROMO_LANG || 'uz';
if (!['uz', 'ru', 'ky', 'uzc'].includes(LANG)) throw new Error(`Noma'lum til: ${LANG}`);
// Har til o'z papkasiga: uz — public/ui/pos, boshqalar — public/ui/pos-<til>.
// Skan ketma-ketligi (promo_dataset.py dagi shtrix-kodlar).
const SCANS = [
  { barcode: '4780012340016', name: 'Limonad 0.5L' },
  { barcode: '4780012340139', name: 'Shokolad 90g' },
  { barcode: '4780012340108', name: 'Sut 1L' },
];

const OUT = path.join(OUT_BASE, LANG === 'uz' ? 'pos' : `pos-${LANG}`);
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: DSF, locale: 'uz-UZ' });
const page = await ctx.newPage();
await page.addInitScript(() => {
  try {
    if (!sessionStorage.getItem('__promo')) {
      sessionStorage.setItem('__promo', '1');
      localStorage.clear();
      localStorage.setItem('savdoos_lang', 'ru');   // kirish oqimi RU matnlari bilan
    }
  } catch { /* ignore */ }
});

// Kirish: demo egasi paroli (faqat lokal seed'da mavjud).
await page.goto(`${POS}/#/login`);
await page.getByRole('button', { name: 'Администратор? Вход по паролю' }).click();
await page.locator('input').first().fill('+998901234567');
await page.locator('input[type="password"]').fill('demo1234');
await page.getByRole('button', { name: 'Войти', exact: true }).click();
await page.getByText('Онлайн').first().waitFor({ timeout: 20000 });

// Reklama tili.
await page.evaluate((l) => localStorage.setItem('savdoos_lang', l), LANG);
await page.reload();
// Tilga bog'liq bo'lmagan tayyorlik belgisi: promo mahsuloti gridda ko'rindi.
await page.getByText('Limonad 0.5L').first().waitFor({ timeout: 20000 })
  .catch(() => { throw new Error("TO'XTADI: promo dataset topilmadi — backend promo_backend.py emas"); });
// Kursor/fokus halqasi va animatsiyalar suratga tushmasin.
await page.addStyleTag({ content: '*{caret-color:transparent!important;transition:none!important;animation:none!important}' });
await page.mouse.move(5, 1075);

async function boxes() {
  return page.evaluate(() => {
    const r = (el) => { const b = el.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; };
    const aside = document.querySelector('aside');
    // ⚠️  Matn bo'yicha qidirilmaydi ("JAMI", "barcode") — rus/qirg'iz suratlarida
    //     ham xuddi shu skript ishlashi kerak. Tuzilma bo'yicha: qidiruv — sahifadagi
    //     birinchi placeholder'li input; JAMI summasi — savat panelidagi ENG YIRIK
    //     yozuv, uning ota-elementi — JAMI qutisi.
    const search = document.querySelector('input[placeholder]');
    const spans = aside ? [...aside.querySelectorAll('span')] : [];
    const amountEl = spans.reduce((best, el) =>
      (!best || parseFloat(getComputedStyle(el).fontSize) > parseFloat(getComputedStyle(best).fontSize) ? el : best), null);
    // Savat qatorlari: o'ng panelda 42x42 harf-avatarining qator konteyneri.
    const rows = [];
    if (aside) {
      for (const el of aside.querySelectorAll('div')) {
        const b = el.getBoundingClientRect();
        if (Math.round(b.width) === 42 && Math.round(b.height) === 42) rows.push(r(el.parentElement));
      }
    }
    const payBtn = aside ? [...aside.querySelectorAll('button')].pop() : null;
    // JAMI summasi (faqat raqam qismi) va quti foni — videoda summa "slot" kabi
    // aylanadi; fon rangi DOM'dan olinadi, taxmin qilinmaydi.
    const box = amountEl ? amountEl.parentElement : null;
    const cs = box ? getComputedStyle(box) : null;
    return {
      aside: aside ? r(aside) : null,
      search: search ? r(search.closest('div')) : null,
      total: box ? r(box) : null,
      pay: payBtn ? r(payBtn) : null,
      amount: amountEl ? r(amountEl) : null,
      totalStyle: cs ? { background: cs.backgroundColor, radius: cs.borderRadius } : null,
      rows,
    };
  });
}

const manifest = { viewport: { width: 1920, height: 1080 }, dsf: DSF, capturedWith: 'capture/capture.mjs', states: [] };
async function shot(i, label) {
  const file = `state-${i}.png`;
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, file) });
  manifest.states.push({ file, label, boxes: await boxes() });
  console.log(`  ${file}  ${label}`);
}

await shot(0, 'bo‘sh savat');
const search = page.locator('input[placeholder]').first();
const typedFiles = [];
for (let i = 0; i < SCANS.length; i++) {
  // Haqiqiy HID skaner qanday qilsa — fokuslangan maydonga raqamlar + Enter.
  await search.click();
  await search.fill('');
  await page.keyboard.type(SCANS[i].barcode, { delay: 3 });
  // Enter'dan OLDINGI lahza: skaner raqamlarni maydonga yozib bo'lgan. Videoda
  // shu maydonning o'zi (haqiqiy piksellar) ko'rsatiladi.
  await page.mouse.move(5, 1075);
  await page.waitForTimeout(250);
  const typed = `typed-${i + 1}.png`;
  await page.screenshot({ path: path.join(OUT, typed) });
  typedFiles.push(typed);
  await search.click();
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await page.getByText(SCANS[i].name).nth(1).waitFor({ timeout: 5000 });   // savatda paydo bo'ldi
  await page.mouse.move(5, 1075);
  await page.locator('body').click({ position: { x: 5, y: 1075 } });        // fokus maydondan chiqsin
  await shot(i + 1, `+ ${SCANS[i].name}`);
}
manifest.lang = LANG;
manifest.scans = SCANS.map((sc, i) => ({ ...sc, typed: typedFiles[i] }));
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log(`manifest: ${path.join(OUT, 'manifest.json')}`);
await browser.close();
