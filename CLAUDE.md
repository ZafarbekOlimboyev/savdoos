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

## Arxitektura / DB
Batafsil: `ARCHITECTURE.md`, `db/schema.sql`, `db/README.md`.
Deploy (Postgres + HTTPS): `infra/docker-compose.prod.yml`.
