# Mobil E2E (Phase 5G, M6) — haqiqiy backend, 390×844

Flutter ilovasining HAQIQIY ekranlari (`apps/mobile`) haqiqiy backend'ga (Postgres) qarshi,
telefon o'lchamida (390×844 dp, DPR 3, Roboto shrifti) bosib chiqiladi. Har oqimdan keyin
natija ILOVADAN MUSTAQIL sessiya bilan serverdan o'qib tekshiriladi (`Probe`): yashil = yozuv
serverda HAQIQATAN bor (yoki salbiy oqimda — HAQIQATAN yo'q).

## Bitta buyruq

```bash
# mahalliy (Windows/Linux): o'z pgserver klasteri (PG16), backend 127.0.0.1:8010
export PATH="/c/flutter/bin:$PATH"          # Windows git-bash
apps/server/.venv/Scripts/python e2e/mobile/run_e2e.py

# CI (JSON hisobot + bajarilganlik tekshiruvi)
DATABASE_URL=postgresql://... APP_ENV=test python e2e/mobile/run_e2e.py \
  --report e2e/mobile/.run/flutter-e2e.jsonl
```

`run_e2e.py`: backend'ni ko'taradi (`start_backend.py`), `/api/v1/health` + tayyorlik faylini
kutadi, `flutter test test/e2e/flows_e2e.dart --dart-define=E2E_BASE=… --dart-define=E2E_MANIFEST=…`
ni ishga tushiradi, so'ng backend'ni (va O'Z pgserver klasterini) to'xtatadi. Chiqish kodi =
flutter kodi (va `--report` bo'lsa `verify_e2e_report.py` kodi).

Qo'lda (backend alohida):

```bash
apps/server/.venv/Scripts/python e2e/mobile/start_backend.py --stop-file e2e/mobile/.run/stop
cd apps/mobile && flutter --no-version-check test test/e2e/flows_e2e.dart \
  --dart-define=E2E_BASE=http://127.0.0.1:8010 \
  --dart-define=E2E_MANIFEST=$PWD/../../e2e/mobile/.run/manifest.json
touch e2e/mobile/.run/stop      # backend va pgserver toza to'xtaydi
```

⚠️ Fayllar ATAYLAB `*_e2e.dart` (`*_test.dart` emas): oddiy `flutter test` ularni YUKLAMAYDI
(skip ham yo'q, soxta yashil ham yo'q). `flutter test test/e2e` (papka) ham ularni
ishlatmaydi — faqat aniq fayl yo'li. `E2E_BASE` berilmasa fayl QATTIQ yiqiladi (skip emas).

## Stsenariy (`scenario.py`)

Alohida do'kon (`e2emob`), vendor provizioningining O'Z funksiyasi bilan: FRESH tenant, T0 =
yaratilish lahzasi (smenasiz naqd = `OPERATOR_MUST_CHOOSE`). Qolgani HAQIQIY marshrutlar orqali:
A (Markaz) va B (Chilonzor) filiallari; ega / omborchi(A) / kassir(A) / menejer(A) /
omborchi(B) (parol `E2e-mobil-sinov-2026`); kuzatuvsiz, partiyali (FIFO), muddatli mahsulotlar
shtrix-kodlar bilan, tarozi PLU 4121 mahsuloti; A: TILL+SAFE (qarz to'lovi bilan pul tushirilgan)
va ARXIV TILL, B: TILL+SAFE; ta'minotchi; qarzdor mijoz (150 000); tuzatish uchun NAQD kirim; B
filialning o'z qoldig'i. Manifest: `e2e/mobile/.run/manifest.json`.

Staging uchun (alohida sinov do'koni; hech qachon mavjud do'konga yozmaydi):

```bash
APP_ENV=staging DATABASE_URL=<staging url> python e2e/mobile/scenario.py \
  --tenant-code e2emob0919 --expect-system-identifier <staging sysid> \
  --manifest e2e/mobile/.run/staging.json
```

Rad etadi: `APP_ENV` dev/test/staging emas (yo'qligi ham), `RAILWAY_ENVIRONMENT_NAME`
production, Postgres emas, production `system_identifier` (7674898282858840119 — override yo'q),
staging'da `--expect-system-identifier` yo'q/mos emas, kod `e2e` bilan boshlanmaydi yoki do'kon
allaqachon bor. Darvoza sinovi: `python -m pytest e2e/mobile/test_scenario_guard.py`.

## Oqimlar (`apps/mobile/test/e2e/flows_e2e.dart`)

| # | Oqim | Server tekshiruvi |
|---|---|---|
| 0 | Login ekrani → PIN → qobiq, `/auth/context` (2 filial, aktor = A) | noto'g'ri parol — sessiya yo'q |
| 1 | Kamera kodi → `/products/scan` → mahsulot; tarozi yorlig'i; noma'lum kod | scan javobi |
| 2 | Partiyali kirim, 2 partiya, Σ≠qty rad | partiyalar paydo bo'ldi |
| 3+7 | Muddatli kirim (majburiy, o'tgan sana rad) NAQD: aniq TILL/SAFE, standart yo'q | partiya muddati, hujjat naqd |
| 4 | Sanoq: kuzatuvsiz + partiya bo'yicha (bo'sh = tegilmaydi) | qoldiq/partiyalar |
| 5 | Hisobdan chiqarish: partiya bo'yicha, FEFO, tannarx | partiyalar kamaydi |
| 6 | Tarix → hujjat → tuzatish, pul TANLANGAN kassaga | tuzatish, partiya, jami |
| 8 | Qarzdor → naqd to'lov, hisob tanlash majburiy | balans kamaydi |
| 9 | Filial A→B, B-ga biriktirilgan xodim | begona filial 403/404 |
| 10 | Kassir / menejer ruxsatsiz | 403 `PERMISSION_DENIED`, yozuv yo'q |
| ∞ | Server yo'q: aniq xato, qayta urinish = o'sha uuid; javob yo'qoldi → «allaqachon saqlangan» | bir marta yozildi |

## Vaqtlar (mahalliy, Windows, PG16 pgserver)

backend tayyor ≈ 14 s (pgserver 7 s + initdb 3.5 s + stsenariy 6 s), flutter ≈ 85 s (kompilyatsiya
≈ 20 s + 15 test ≈ 65 s), to'xtatish ≈ 1.5 s — jami ≈ 100 s.
