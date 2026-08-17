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
Ilovalar GitHub'dagi **ochiq release repolardan** avto-yangilanadi (kod repo yopiq qoladi):
- POS → `ZafarbekOlimboyev/savdoos-pos-releases` · Manager → `ZafarbekOlimboyev/savdoos-manager-releases`

Foydalanuvchi "yangi versiya chiqar" desa:
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
