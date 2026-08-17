# SavdoOS

Do'kon/market uchun offline-first POS tizimi.
**Backend:** FastAPI + PostgreSQL/SQLite · **Desktop:** Electron + React (TypeScript).

Arxitektura: [ARCHITECTURE.md](ARCHITECTURE.md) · DB: [db/README.md](db/README.md)

## Tuzilma (monorepo)
```
apps/
  server/     FastAPI backend (API, modellar, auth, seed)
  pos/        SavdoOS POS — kassir ilovasi (Electron)
  manager/    SavdoOS Manager — admin ilovasi (Electron)
packages/
  shared/     ikkala ilova uchun umumiy kod (lib, store, screens, ui, styles)
db/           schema.sql + hujjat
infra/        docker-compose (postgres, redis, caddy)
```
**Ikki alohida `.exe`:** kassirlar **POS**ni, egasi/menejer **Manager**ni o'rnatadi.
Kod umumiy (`packages/shared`), lekin ilovalar mustaqil (o'z installeri).

## Tez ishga tushirish (DEMO — hech narsa o'rnatilmaydi)

Demo **SQLite** bilan ishlaydi — Docker ham, Postgres ham shart emas.

### 1) Backend
```bash
cd apps/server
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/Mac: source .venv/bin/activate)
pip install -e .
copy .env.example .env            # Windows   (Linux/Mac: cp .env.example .env)
python -m app.initdb              # SQLite jadvallarini yaratadi (savdoos.db)
python -m app.seed                # rollar, 19 mahsulot, mijoz, xodim (PIN 1234)
uvicorn app.main:app --reload     # http://localhost:8000/docs
```

### 2) Desktop (ikki ilova)
```bash
# umumiy runtime kutubxonalari (bir marta, ildizda):
npm install

# POS (kassir):
cd apps/pos && npm install && npm run dev
# Manager (admin) — alohida terminalda:
cd apps/manager && npm install && npm run dev
```
**Login:** Administrator — PIN **1234** · Kassir — PIN **1111**

> Talablar: **Python 3.11+** va **Node.js 18+**. Demo uchun DB kerak emas (SQLite).

## Serverga qo'yish (deploy) — production

Backend serverda ishlaydi, kassalar (`.exe`) unga internet orqali ulanadi.
Stack: **PostgreSQL + FastAPI + Caddy (avtomatik HTTPS)** — hammasi Docker'da.

### 1) Server tayyorlash
- Ubuntu VPS oling (2GB RAM yetadi) va **domen** (masalan `api.dokonim.uz`) ni serverning IP'siga **A-record** bilan yo'naltiring.
- Docker o'rnating:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ```

### 2) Loyihani serverga ko'chirib, ishga tushirish
```bash
# loyihani serverga ko'chiring (git yoki scp), keyin:
cd savdoOS/infra
cp .env.prod.example .env
nano .env        # DOMAIN, POSTGRES_PASSWORD, SECRET_KEY ni to'ldiring
docker compose -f docker-compose.prod.yml up -d --build
```
Caddy avtomatik **HTTPS sertifikat** oladi. Tekshirish: `https://api.dokonim.uz/api/v1/health`

> `SECRET_KEY` uchun: `openssl rand -hex 32`

### 3) Kassalarni serverga ulash
Har kassada `.exe`ni oching → **Login ekrani → "⚙ Server sozlamalari"** →
server manzilini kiriting (`https://api.dokonim.uz`) → **Saqlash**. Tamom —
bitta `.exe` istalgan serverga ulanadi, qayta yig'ish shart emas.

> Lokal (localhost) rejimga qaytish: shu yerda **"Lokal (localhost)"** tugmasi.

### Fayllar
`infra/docker-compose.prod.yml` · `infra/Caddyfile` · `infra/.env.prod.example`

## Desktop `.exe` yig'ish (ikkita alohida installer)
```bash
npm install                          # ildizda bir marta (umumiy react/zustand)
npm run dist:pos                     # apps/pos/release/SavdoOS-POS-Setup-0.1.0.exe
npm run dist:manager                 # apps/manager/release/SavdoOS-Manager-Setup-0.1.0.exe
```
Natija:
- **`apps/pos/release/SavdoOS-POS-Setup-0.1.0.exe`** — kassir ilovasi (~79 MB)
- **`apps/manager/release/SavdoOS-Manager-Setup-0.1.0.exe`** — admin ilovasi (~79 MB)

Imzosiz — birinchi ochilishda Windows SmartScreen ogohlantirishi normal ("Batafsil → Baribir ishga tushirish").

> **Admin bo'lmagan Windows'da** electron-builder `winCodeSign` macOS symlink'larida
> to'xtashi mumkin. Yechim: **Developer Mode** yoqing, yoki `winCodeSign-2.6.0.7z` ni
> `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\` ga qo'lda oching
> (2 ta darwin symlink xatosini e'tiborsiz qoldiring) — keyin `npm run dist` ishlaydi.

## Holat — DEMO TAYYOR ✅

**Backend** (31 API endpoint, end-to-end tekshirilgan):
- 53 jadval modeli, JWT auth + RBAC (4 rol), offline-idempotent savdo
- Savdo → ombor kamayishi + tannarx snapshot + nasiya daftari (bitta tranzaksiya)
- Xarid (kirim), qaytarish (sabab/restock), qarz to'lov, smena, hisobot (P&L)

**Desktop** — **ikki alohida ilova** (umumiy kod, TypeScript 0 xato, `.exe` yig'ilgan):

**SavdoOS POS** (kassir): Kassa · Sotuvlarim · Qaytarishlar · Mijozlar · Smena
**SavdoOS Manager** (admin): Dashboard · Mahsulotlar · Sotuvlar · Xaridlar · Hisobotlar · Mijozlar · Qaytarishlar · Xodimlar · Smena · Sozlamalar

- Login (PIN), onlayn/oflayn indikator, server manzili sozlanadigan
- **POS Kassa**: mahsulot to'ri, savat, to'lov (Naqd/Karta/QR/Qarz+mijoz), **barcode skan (Enter)**, **chek chop etish (80mm)**, qaytim
- **SavdoOS Manager (admin)**: boy Dashboard (qarz bloki, haftalik grafik, to'lov usullari, kam qolgan),
  Mahsulotlar (qo'shish/tahrir/o'chirish + kategoriya), Sotuvlar (filtr+detal), Mijozlar (tafsilot+tarix+qarz),
  Xaridlar (kirim+beruvchi), Hisobotlar (P&L + **CSV eksport**), Xodimlar (**ruxsat toggle'lari**), Smena, Sozlamalar
- **Offline-first**: katalog keshi + sotuvlar navbati (outbox) + avto-sync (idempotent `client_uuid`)
- **Ikkita `.exe` installer**: `apps/pos/release/SavdoOS-POS-Setup-0.1.0.exe` · `apps/manager/release/SavdoOS-Manager-Setup-0.1.0.exe`
- **Bir tugmali backend**: ildizda `run.bat`

**Tekshiruv:** to'liq backend e2e **38/38 PASS** (auth, katalog CRUD, savdo, sync-idempotentlik,
qaytarish, mijoz/qarz, xodim ruxsatlari, xarid, hisobot, smena) + frontend tsc 0 + `.exe` build exit 0.

## Keyingi bosqichlar (ixtiyoriy)
- Kassada lokal SQLite (better-sqlite3) — hozir offline navbat localStorage'da
- Alembic migratsiyalari, DuckDB analitika, kod imzosi (SmartScreen uchun)

Batafsil: [ARCHITECTURE.md §11](ARCHITECTURE.md).
