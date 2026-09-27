# BinOS — vertikal promo video (Remotion)

Kod bilan yig'iladigan, takrorlanadigan reklama videosi. **Mahsulot kodi emas**:
alohida paket, repo workspace'lariga kirmaydi, POS/Manager xulqiga tegmaydi.

```
1080 x 1920 · 9:16 · 30 fps · h264 + AAC
```

Hozirgi holat: **proof of style** (8 s) — vizual yo'nalish tasdiqlanishini kutmoqda.
To'liq 35–45 s versiya tasdiqdan KEYIN yig'iladi.

## Quvur

| bosqich | buyruq | natija |
|---|---|---|
| 1. lokal sintetik backend | `<venv python> capture/promo_backend.py` | `127.0.0.1:8000`, toza `.cache/promo.db` |
| 2. haqiqiy POS (brauzer) | `cd ../../apps/pos && npx vite --config vite.preview.config.ts --port 5199` | `localhost:5199` |
| 3. UI suratlari | `node capture/capture.mjs` (`PROMO_LANG=ru` — boshqa til) | `public/ui/pos/state-*.png`, `typed-*.png`, `manifest.json` |
| 4. musiqa + SFX | `python scripts/gen_audio.py 8` (numpy) | `public/audio/*.wav` |
| 5. render | `npm run render:proof` | `out/binos-proof-of-style.mp4` |
| ko'rib chiqish | `node scripts/stills.mjs ProofOfStyle 60 120 200` | `out/stills/f*.png` |

`<venv python>` — `apps/server` bog'liqliklari o'rnatilgan Python (masalan
asosiy checkout'dagi `apps/server/.venv/Scripts/python.exe`).

UI suratlari va audio repo'ga **kiritilgan** — render uchun backend ham, Python ham
shart emas. Ular 1–4-bosqichlar bilan qayta hosil qilinadi.

## Nima haqiqiy, nima video ramkasi

| haqiqiy BinOS (o'zgartirilmagan) | faqat video (kompozitsiya) |
|---|---|
| POS kassa ekrani, kartalar, savat qatorlari, JAMI, to'lov tugmasi | navy fon, nurlar, don |
| skan paytida qidiruv maydoniga yozilgan raqamlar (`typed-*.png`) | etiketka (EAN-13 stiker) va skaner nuri |
| gridning qayta tartiblanishi (savatdagilar oldinga chiqadi) | kamera: yaqinlashish, panorama, siqilish |
| BinOS logosi (asl fayl) | sarlavhalar, "Kassa" yorlig'i, "BinOS" yozuvi (Inter bilan terilgan) |

Harakat faqat haqiqiy piksellar bilan: savat qatori — keyingi holat suratining
o'sha qutisi (`Patch`), JAMI — ikki holat summalari "slot" kabi (`Roll`). Barcha
qutilar DOM'dan o'qiladi (`manifest.json`), qo'lda o'lchanmaydi.

## Ma'lumot xavfsizligi

- Faqat **lokal SQLite**. `promo_backend.py` `DATABASE_URL` ni o'zi o'rnatadi
  (muhitdagi qiymat ustidan yozadi) va 8000-port band bo'lsa to'xtaydi.
- `capture.mjs` faqat `localhost` ga ulanadi va promo mahsuloti ko'rinmasa to'xtaydi.
- Dataset (`capture/promo_dataset.py`): brendsiz nomlar, real narx tartibi, mijozlar —
  ism + bosh harf, soxta telefonlar. Uchinchi tomon savdo belgilari yo'q.
- Production'ga ulanish, kirish yoki yozish **yo'q**.

## Litsenziya va assetlar

- **Shrift:** Inter, SIL OFL 1.1 — `public/fonts/OFL-Inter.txt`. Mahsulot UI shrifti bilan bir xil.
- **Logo:** ega bergan asl fayl — `public/brand/PROVENANCE.md`. Rasmiy so'z-belgi fayli yo'q.
- **Musiqa/SFX:** `scripts/gen_audio.py` kod bilan sintez qiladi — namuna, loop yoki
  uchinchi tomon materiali yo'q. Vaqtinchalik: yakuniy versiyada litsenziyalangan
  trek `public/audio/music.wav` ni almashtiradi. Tijoriy musiqa repo'ga qo'yilmaydi.

## Tillar

Ekrandagi hamma matn `src/copy.ts` da; kompozitsiya kodida matn yo'q. UI suratlari
ham tilga bog'liq holda olinadi (`PROMO_LANG=ru node capture/capture.mjs` →
`public/ui/pos-ru/`; skript matnga emas, DOM tuzilishiga tayanadi — ruscha
suratlarda qutilar to'g'ri topilishi tekshirilgan). Tarjima yo'q til bilan render
xato beradi (jimgina o'zbekchaga tushmaydi).

⚠️ Hozircha kompozitsiya `public/ui/pos/` (o'zbekcha) manifestini to'g'ridan-to'g'ri
import qiladi. Tilga qarab papka tanlash to'liq versiyada qo'shiladi.
