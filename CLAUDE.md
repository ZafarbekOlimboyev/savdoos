# SavdoOS — loyiha yo'riqnomasi (CLAUDE.md)

Do'kon/market uchun offline-first POS tizimi.
- **Backend:** FastAPI + PostgreSQL/SQLite (`apps/server`)
- **Desktop:** ikki mustaqil Electron ilova — **SavdoOS POS** (`apps/pos`, kassir) va
  **SavdoOS Manager** (`apps/manager`, admin). Umumiy kod: `packages/shared`.

## ⚡ Push qoidasi (MUHIM)
Foydalanuvchi **"push qil"** desa — **savol bermasdan** quyidagini bajar:
```bash
git add -A
git commit -m "<qisqa, mazmunli xabar>"
git push origin main
```
- Agar hech o'zgarish bo'lmasa — buni ayt, bo'sh commit qilma.
- Agar push **login/parol** so'rasa yoki **"Authentication failed"** bersa — darrov
  foydalanuvchini ogohlantir: GitHub **token (PAT)** yoki `gh auth login` kerak.
- Sirlarni (`.env`, `*.db`, `node_modules`, `release/`) hech qachon commit qilma
  (`.gitignore` da sozlangan).

## Ishga tushirish
- Backend: `run.bat` (ildizda) — SQLite bilan, hech narsa o'rnatmasdan. Login PIN: 1234 / 1111.
- Desktop dev: `npm install` (ildizda) → `cd apps/pos && npm run dev` (yoki `apps/manager`).
- `.exe` yig'ish: `npm run dist:pos` · `npm run dist:manager`.

## Tekshirish (o'zgarish kiritgach)
- Frontend: mos ilova papkasida `npx tsc --noEmit`.
- Backend: `cd apps/server` da SQLite bilan tez e2e (TestClient) yoki `uvicorn app.main:app`.

## 🚀 Yangi versiya chiqarish (avto-yangilanish)
Ilovalar GitHub'dagi **ochiq release repolardan** avto-yangilanadi:
> ⚠️  **DIQQAT (2026-09-28 da o'lchandi):** `ZafarbekOlimboyev/savdoos` kod repositoriysi
> ham **OCHIQ** (`private=false`). Bu yerda ilgari "kod repo yopiq qoladi" deb yozilgan edi
> va bir nechta joy shu taxminga tayangan. Amaliy oqibat: GitHub'ga kirgan **har qanday
> hisob** Actions artefaktlarini yuklab oladi — ya'ni tungi backup nusxalarini ham.
> Ularning yagona himoyasi — `BACKUP_PASSPHRASE`. Batafsil va qaror variantlari:
> `RELEASE_SAFETY_RUNBOOK.md` §6.
- POS → `ZafarbekOlimboyev/savdoos-pos-releases` · Manager → `ZafarbekOlimboyev/savdoos-manager-releases`

Foydalanuvchi "yangi versiya chiqar" desa:
0. **AVVAL SERVER, KEYIN KLIENT.** Phase 5F dan boshlab POS/Manager onlayn chekni serverdan
   (`GET /sales/{id}/receipt`) oladi. Klient release qilishdan OLDIN production serverda shu marshrut
   borligini tekshir: `GET /api/v1/receipt/profile` → 401/200 bo'lishi kerak, **404 bo'lsa release
   qilma** (server hali eski — avval server deploy). Klientlar tarqalgach serverni 5F dan oldingi SHA
   ga qaytarish ham chekni buzadi (klientda faqat o'z sotuvi uchun eski usulga zaxira bor).
1. `apps/pos/package.json` va `apps/manager/package.json` da `version`ni oshir (masalan 0.2.0 → 0.3.0).
   **DIQQAT:** package.json'ni faqat BOM'siz UTF-8 da yoz (PowerShell `Set-Content -Encoding utf8` BOM qo'shadi — vite buziladi).
2. `npm run dist:pos` va `npm run dist:manager` (ildizda).
3. Har bir ilova uchun release chiqar (`gh` yo'li: `C:\Program Files\GitHub CLI\gh.exe`):
   `gh release create v<versiya> --repo ZafarbekOlimboyev/savdoos-<pos|manager>-releases <Setup.exe> <Setup.exe.blockmap> latest.yml`
4. Tekshir: `https://github.com/ZafarbekOlimboyev/savdoos-<pos|manager>-releases/releases/latest/download/latest.yml` → HTTP 200, yangi versiya.

O'rnatilgan ilova har ishga tushganda + har 4 soatda tekshiradi, fonda yuklab, "Yangilanish tayyor" dialogi ko'rsatadi.

## Server (Railway)
Backend: `https://savdoos-production.up.railway.app` (loyiha: `trustworthy-enchantment`, servis: `savdoos` + `Postgres-d29B`).
Deploy: `apps/server` da `railway up --ci --service savdoos`. Tayyor .exe'lar shu serverga avto-ulanadi
(`packages/shared/src/lib/api.ts` dagi `PROD_SERVER`); dev rejim — `localhost:8000`.

## Arxitektura / DB
Batafsil: `ARCHITECTURE.md`, `db/schema.sql`, `db/README.md`.
Deploy (Postgres + HTTPS): `infra/docker-compose.prod.yml`.
Dizayn prototipi: `POS Kassa main screen live.zip` (ildizda) — UI ga tegishda AVVAL shu bilan solishtir (piksel-aniqlik talab).

## Graphify-Assisted Development & Smart Testing

### A. Avval qayta ishlat (reuse-first)
Nontrivial ish boshlashdan OLDIN mavjud BinOS modullarini ko'r; tasdiqlangan
implementatsiyani afzal bil, mavjud interfeys yoki xavfsiz adapter orqali ulan.
POS, to'lov, naqd oqimi, inventar, qarz, qaytarish va avtorizatsiya mantig'ini
TAKRORLAMA. Tasdiqlangan moliyaviy yadroni aniq sabab bo'lmasa refaktor qilma.

### B. Graphify — yordamchi, hokim emas
Muhim modul o'zgarishlarida: `built_at_commit` ni `git rev-parse HEAD` bilan solishtir →
simvol/chaqiruvchi/bog'liqlikni ko'r → **har muhim topilmani manbada tekshir** → zarurda
oddiy repo qidiruviga qayt. Mayda UI/matn tahririda O'Z INITSIATIVAM bilan ishlatma
(foydalanuvchi `/graphify` desa — global skill qoidasi ustun).

`graphify` PATH da YO'Q va graf repodan TASHQARIDA — absolyut yo'l + `--graph` SHART
(`query`/`path`/`explain`/`affected` hammasi qabul qiladi). Yo'llar muhitga xos, tekshir:
```bash
"C:/Users/Developer/.local/bin/graphify.exe" affected "create_sale" --depth 2 \
  --graph C:/Users/Developer/Desktop/binos-graph/graphify-out/graph.json
```

O'lchangan cheklovlar (2026-10-13, graf `ddc03eb`):
- HTTP (TestClient) testlari servis funksiyalariga **bog'lanmagan** — `client.post("/sales")`
  ishlatadigan 21 test fayli `affected create_sale` ga depth 2 da ham, 4 da ham tushmaydi.
- `Depends(require(...))` ruxsat aloqalari AMALDA yo'q — app kodida 112 joy, grafda
  `require()` ga 1 `calls` edge (u ham testdan); ruxsat ta'sirini
  `grep -rn "Depends(require(" apps/server/app` bilan top.
- Dart: 187 fayl struktura sifatida bor, `calls` edge 0 — Flutter chaqiruv grafi yo'q.
- SQL sxema grafda UMUMAN yo'q (0 node) — `--code-only` `db/schema.sql` va
  `app/db/cash/*.sql` ni indekslamaydi (faqat `--postgres DSN` bilan kirardi).

**Graf aloqa ko'rsatmasa — bu "ta'sir yo'q" degani EMAS.**

### C. Kichik batch'lar
Bitta batch ≈ 2–3 bog'liq funksiya yoki bitta kichik izchil xatti-harakat. Tartib:
kutilgan natijani belgila → kichik o'zgarish → fokuslangan testlar → bevosita ta'sirlangan
regressiya → nuqsonni tuzat → diff'ni ko'r → mezon bajarilgach davom et.
10–15 biznes funksiyasini testsiz yozma; mayda o'zgarishga ortiqcha checkpoint ham yasama.

### D. Riskka mos testlash
Maqsad — test SONI emas, turli yiqilish YO'LLARI. Yo'riq (kvota EMAS):
LOW 1–3 · MEDIUM 3–6 · HIGH ~5–10 maqsadli test.
Turlarni aralashtir: muvaffaqiyatli yo'l · noto'g'ri kirish · chegara · holat/ruxsat to'siqi ·
tegishli integratsiya · dublikat yoki parallel harakat. Bir xil narsani qayta isbotlovchi
testdan voz kech; qimmatli mavjud regressiyani saqla.

### E. Test tanlash — nontrivial o'zgarishda uch manba birgalikda
(1) Graphify bog'liqlik tahlili · (2) manba va mavjud testlar bo'yicha qidiruv ·
(3) kritik biznes invariantlari. **Graf yolg'iz to'liq test to'plamini belgilamaydi**;
graf ishlatilmagan yoki eskirgan bo'lsa (2)+(3) yetarli — graf TALAB emas.
Alohida e'tibor: sotuv/qaytarish · naqd oqimi va smena rekonsiliatsiyasi · nasiya qarzi ·
inventar miqdori · seriya raqamlari · idempotentlik · tenant izolyatsiyasi.
Qachon: kichik batch'dan keyin fokuslangan · modul tugagach modul regressiyasi ·
integratsiya bosqichida kengroq regressiya · umumiy moliyaviy semantika o'zgarsa DARHOL
tegishli kritik-yadro regressiyasi. Bazaviy tekshiruv — yuqoridagi «Tekshirish» bo'limi.

### F. Graf saqlash
Har mayda o'zgarishdan keyin qayta qurma: `built_at_commit` ni tekshir, bosqich oxirida
yoki eskirish muhim bo'lganda yangila. Tasdiqlangan yo'l (sintaksisni oldin tekshir):
```bash
"C:/Users/Developer/.local/bin/graphify.exe" extract . --code-only --out C:/Users/Developer/Desktop/binos-graph
"C:/Users/Developer/.local/bin/graphify.exe" cluster-only C:/Users/Developer/Desktop/binos-graph --no-label
```
Ikkinchi buyruq SHART — `extract` `GRAPH_REPORT.md`/`graph.html` ni yangilamaydi.
`graphify update .` ni BinOS repo'sida ISHLATMA: u chiqishni DOIM `<yo'l>/graphify-out` ga
yozadi (bir marta 817 fayl / 111 MB tashlagan). Avval `.gitignore` da `graphify-out/`
borligini tekshir: `git check-ignore -v graphify-out/graph.json` («push qil» = `git add -A`).
Git hook, fonda indeksatsiya yoki CI integratsiyasini ruxsatsiz yoqma.

### G. Hisobot qisqa
Har batch uchun: qayta ishlatilgan narsa · qo'shilgan xatti-harakat · ishlatilgan testlar
va natija · ochiq muammolar. Routine o'zgarishga katta arxitektura hisoboti yozma.

### H. Xavfsizlik va parallel sessiyalar
Parallel sessiyalar ishiga tegma — ishchi daraxtdagi va boshqa worktree'lardagi begona
o'zgarishlarni AYNAN saqla. Production/staging ma'lumotini aniq ruxsatsiz o'zgartirma.
**Batch tugaganining o'zi** push/merge/deploy uchun asos EMAS; push faqat yuqoridagi
«Push qoidasi» bo'yicha, foydalanuvchi aytganda. Commit boshqa: bir mantiqiy birlik ish
tugab testlar yashil bo'lgach commit qilinadi (commit ≠ push).
Branch/deploy xavfsizligi qoidalari shu faylda EMAS — `RELEASE_SAFETY_RUNBOOK.md` va
`BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` da; tegishdan oldin o'qi.
