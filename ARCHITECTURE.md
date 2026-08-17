# SavdoOS — Arxitektura va Amalga Oshirish Rejasi

> **Stack:** Backend — FastAPI (Python) · Frontend/Desktop — Electron + React (TypeScript)
> **Prinsip:** Offline-first kassa · Markaziy analitika · Bosqichma-bosqich qurish

---

## Mundarija
1. [Umumiy arxitektura](#1-umumiy-arxitektura)
2. [Texnologiyalar](#2-texnologiyalar)
3. [Loyiha tuzilishi (monorepo)](#3-loyiha-tuzilishi-monorepo)
4. [Ma'lumotlar bazasi sxemasi](#4-malumotlar-bazasi-sxemasi)
5. [Offline-first va Sync strategiyasi](#5-offline-first-va-sync-strategiyasi)
6. [API dizayni](#6-api-dizayni)
7. [Frontend arxitekturasi](#7-frontend-arxitekturasi)
8. [Analitika qatlami (kelajak)](#8-analitika-qatlami-kelajak)
9. [Xavfsizlik va ruxsatlar](#9-xavfsizlik-va-ruxsatlar)
10. [Paketlash va deploy](#10-paketlash-va-deploy)
11. [Bosqichlar (roadmap)](#11-bosqichlar-roadmap)

---

## 1. Umumiy arxitektura

Uch qatlamli, offline-first tuzilma. Kassa hech qачон serverni kutmaydi.

```
┌───────────────────────────────────────────────────────────┐
│  KASSA TERMINAL  —  desktop .exe  (har do'kon/kassada)     │
│                                                            │
│   Electron (main process)                                  │
│    ├─ better-sqlite3   → LOKAL baza (offline-first)        │
│    ├─ IPC / preload    → xavfsiz ko'prik (renderer ↔ main) │
│    ├─ printer          → chek chop etish (ESC/POS)         │
│    └─ auto-update      → yangilanish                       │
│                                                            │
│   React (renderer)  ← mavjud dizayn shu yerga ko'chadi     │
│    ├─ UI ekranlar (Kassa, Ombor, Hisobot, ...)            │
│    ├─ Zustand         → app holati                         │
│    └─ TanStack Query  → server bilan sync                  │
└──────────────────────────┬────────────────────────────────┘
                           │  HTTPS / REST (internet bo'lganda, fon rejimida)
                           ▼
┌───────────────────────────────────────────────────────────┐
│  MARKAZIY BACKEND  —  FastAPI (Python)                     │
│                                                            │
│    ├─ REST API (async, Pydantic v2)                        │
│    ├─ SQLAlchemy 2.0 + Alembic (migratsiya)                │
│    ├─ JWT auth + rol/ruxsat (RBAC)                          │
│    ├─ Sync endpointlar (push/pull)                         │
│    └─ Celery + Redis (fon vazifalar: ETL, hisobot)         │
│                                                            │
│           ┌──────────────┐        ┌────────────────────┐   │
│           │ PostgreSQL   │        │ DuckDB / ClickHouse │   │
│           │ (asosiy OLTP)│  ───▶  │ (analitika / OLAP)  │   │
│           └──────────────┘        └────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

**Nega shunday:**
- Kassa lokal SQLite bilan **darhol** sotadi — internet uzilsa ham to'xtamaydi.
- Server (FastAPI) — ko'p filial ma'lumotini yig'adi, hisobot/analitikani markazda hisoblaydi.
- Sotuvlar **append-only** (faqat qo'shiladi) → sync konflikti deyarli bo'lmaydi.

---

## 2. Texnologiyalar

### Frontend / Desktop
| Rol | Texnologiya | Izoh |
|---|---|---|
| Shell | **Electron** + electron-builder | `.exe` (NSIS installer), Windows |
| UI | **React 18 + TypeScript + Vite** | Tez dev, tipli |
| Holat (client) | **Zustand** | Yengil, savat/UI holati |
| Holat (server) | **TanStack Query** | Sync, cache, retry |
| Lokal baza | **better-sqlite3** | Sinxron, tez, main process'da |
| Routing | **React Router** | Ekranlar orasida |
| Ikonlar/shrift | **Phosphor** + **Inter** | Mavjud dizayn bilan bir xil |
| Chek / barcode | **node-thermal-printer**, keyboard-wedge scanner | Skaner = klaviatura kiritishi (F2 tayyor) |
| Auto-update | **electron-updater** | Masofadan yangilash |

### Backend
| Rol | Texnologiya | Izoh |
|---|---|---|
| API | **FastAPI** + **Uvicorn/Gunicorn** | async, OpenAPI avtomatik |
| Modellar | **Pydantic v2** | So'rov/javob validatsiyasi |
| ORM | **SQLAlchemy 2.0** + **Alembic** | Migratsiya |
| Asosiy DB | **PostgreSQL 16** | OLTP, ko'p filial |
| Analitika DB | **DuckDB** (embedded) → **ClickHouse** (kerak bo'lsa) | OLAP |
| Data | **Polars / pandas** | Katta hisob-kitob |
| Auth | **python-jose** (JWT) + **passlib[bcrypt]** | Token + parol |
| Fon vazifa | **Celery + Redis** yoki **APScheduler** | ETL, hisobot yig'ish |
| ML (keyin) | **scikit-learn**, **Prophet** | Sotuv bashorati |
| Test | **pytest** | |

### Umumiy / DevOps
- **pnpm workspaces** (monorepo), **uv** yoki **Poetry** (Python paket)
- **openapi-typescript** → FastAPI OpenAPI'dan TS tiplarini avtomatik generatsiya (frontend ↔ backend kontrakti)
- **Docker + docker-compose** (server tomoni), **GitHub Actions** (CI/CD)

---

## 3. Loyiha tuzilishi (monorepo)

```
savdoos/
├─ apps/
│  ├─ desktop/                  # Electron + React
│  │  ├─ electron/
│  │  │  ├─ main.ts             # main process: oyna, SQLite, IPC, printer
│  │  │  ├─ preload.ts          # xavfsiz API (contextBridge)
│  │  │  ├─ db/                 # better-sqlite3: schema, migratsiya, repo
│  │  │  ├─ sync/               # outbox, pull/push agent
│  │  │  └─ services/           # printer, scanner, updater
│  │  ├─ src/                   # React ilova (renderer)
│  │  │  ├─ screens/            # Kassa, Sotuvlar, Ombor, Hisobot, ...
│  │  │  ├─ components/         # umumiy UI (Sidebar, Modal, Table)
│  │  │  ├─ store/              # Zustand
│  │  │  ├─ api/                # TanStack Query hooklar
│  │  │  ├─ lib/                # ipc(), format(fmt), hotkeys
│  │  │  └─ styles/             # dizayn tokenlari (Inter, ranglar)
│  │  ├─ electron-builder.yml
│  │  └─ vite.config.ts
│  │
│  └─ server/                   # FastAPI
│     ├─ app/
│     │  ├─ main.py             # FastAPI ilova
│     │  ├─ core/               # config, security (JWT), deps
│     │  ├─ models/             # SQLAlchemy modellar
│     │  ├─ schemas/            # Pydantic sxemalar
│     │  ├─ api/v1/             # routerlar (auth, sales, catalog, sync, reports)
│     │  ├─ services/           # biznes-mantiq
│     │  ├─ analytics/          # DuckDB/ETL, hisobot querylar
│     │  └─ db/                 # session, base
│     ├─ alembic/               # migratsiyalar
│     ├─ tests/
│     └─ pyproject.toml
│
├─ packages/
│  └─ shared-types/             # OpenAPI'dan generatsiya qilingan TS tiplari
│
├─ infra/
│  └─ docker-compose.yml        # postgres, redis, server
├─ docs/
└─ ARCHITECTURE.md              # (shu fayl)
```

---

## 4. Ma'lumotlar bazasi sxemasi

Domen mavjud prototipdan olingan. To'liq, normalizatsiya qilingan (3NF), analitikaga
tayyor sxema alohida faylda: **[`db/schema.sql`](db/schema.sql)** (PostgreSQL DDL) va
**[`db/README.md`](db/README.md)** (modullar xaritasi, konvensiyalar, analitika ombori).

> **Loyihaning oltin qoidasi:** hech qanday ma'lumot yo'qolmaydi. Har savdo qatorida
> narx **va tannarx** o'sha ondagi holatida saqlanadi (snapshot) — kelajakda narx
> o'zgarsa ham tarixiy marja/foyda to'g'ri hisoblanadi. O'chirish — **soft-delete**
> (`deleted_at`), hech narsa fizik o'chirilmaydi.

### Umumiy ustunlar (har jadvalda)
`id UUID` · `created_at` · `updated_at` · `created_by` · `deleted_at` (soft-delete) ·
`client_uuid` (offline idempotentlik) · `row_version bigint` (sync) · ko'pchiligida `branch_id`.

### Modullar (13 ta domen · ~55 jadval)
| # | Modul | Asosiy jadvallar |
|---|---|---|
| 1 | **Tashkilot** | companies, branches, terminals |
| 2 | **Auth / RBAC** | employees, roles, permissions, role_permissions, employee_permissions, employee_branches, auth_sessions |
| 3 | **Katalog** | categories (ierarxiya), products, product_barcodes, units, brands, product_prices (narx tarixi), product_suppliers |
| 4 | **Ombor** | inventory, stock_movements (fakt), stock_batches (partiya/muddat), stock_counts + items, stock_transfers + items |
| 5 | **Xaridlar** | suppliers, purchases + purchase_items, supplier_payments, supplier_ledger |
| 6 | **Sotuvlar** | sales, sale_items (snapshot narx/tannarx), sale_payments, sale_discounts |
| 7 | **Qaytarishlar** | returns (reason, restock), return_items |
| 8 | **Mijozlar / Qarz** | customers, customer_groups, credit_transactions (daftar), customer_payments, loyalty_transactions |
| 9 | **Smena / Kassa** | shifts, cash_movements |
| 10 | **Sozlamalar** | settings (scoped JSONB), payment_methods, tax_rates, receipt_templates |
| 11 | **Sync** | sync_log, sync_cursors, devices (+ har jadvaldagi row_version) |
| 12 | **Audit** | audit_log (before/after JSONB), activity_events |
| 13 | **Analitika (OLAP)** | dim_* + fact_* yulduz-sxema (DuckDB/ClickHouse), reporting materialized view'lar |

Batafsil ustunlar, FK'lar, indekslar, ENUM'lar va munosabatlar `db/schema.sql` da.

---

## 5. Offline-first va Sync strategiyasi

### Prinsip
- **Server = haqiqat manbai** katalog, narx, mijoz, sozlama uchun (kassa bularni **pull** qiladi).
- **Kassa = haqiqat manbai** sotuv/qaytarish/smena uchun (serverga **push** qiladi).
- Har yozuv `id = UUID` → terminalda yaratilgan sotuv serverga ko'chsa ham konflikt bo'lmaydi.

### Push (kassa → server) — *Outbox pattern*
1. Sotuv lokal SQLite'ga yoziladi + `outbox`ga qatorga qo'yiladi.
2. Sync agent (fon) internet bo'lganda `outbox`ni serverga yuboradi.
3. Har so'rovda **idempotency key** (= yozuv UUID) → takror yuborilsa ham ikki marta yozilmaydi.
4. Server tasdiqlagach `outbox.sent = true`.

### Pull (server → kassa)
- `updated_at > last_pulled_at` bo'yicha o'zgargan katalog/mijoz/sozlamalar tortiladi (delta sync).
- Narx faqat serverdan keladi → kassada narx o'zgartirilmaydi.

### Konflikt yechimi
| Ma'lumot | Kim yutadi |
|---|---|
| Sotuv, qaytarish, smena | Kassa (append-only, konflikt yo'q) |
| Narx, katalog, sozlama | Server (last-write-wins, server manbai) |
| Ombor qoldig'i | Serverda qayta hisoblanadi (harakatlar yig'indisi) |

---

## 6. API dizayni

`/api/v1/...` · JSON · JWT (Bearer) · OpenAPI avtomatik (`/docs`).

```
# Auth
POST   /auth/login                 # PIN/parol → JWT
POST   /auth/refresh

# Katalog
GET    /products                   # ?category=&q=&updated_since=
POST   /products                   # (Administrator/Omborchi)
PATCH  /products/{id}
GET    /categories

# Ombor
GET    /inventory                  # ?branch=&low_stock=
POST   /stock-movements            # kirim/chiqim/tuzatish

# Xaridlar
GET    /purchases
POST   /purchases                  # kirim hujjati + itemlar

# Mijozlar / Qarz
GET    /customers                  # ?q=&only_debt=
POST   /customers
GET    /customers/{id}             # profil + qarz + tarix
POST   /customers/{id}/payments    # qarzni yopish (Qarzni yopish modali)

# Katalog import (1C / Excel / CSV)
POST   /products/import/upload     # fayl → preview qatorlar
POST   /products/import/validate   # ustun-mapping + xato tekshirish
POST   /products/import/commit     # tasdiqlangan qatorlarni yozish

# Sotuvlar
GET    /sales                      # ?date=&cashier=&method=&q=
GET    /sales/{id}
POST   /returns                    # {reason, restock, items[]}

# Smena
POST   /shifts/open
POST   /shifts/{id}/close

# Sozlamalar
GET    /settings
PUT    /settings

# Xodimlar (RBAC)
GET    /employees
POST   /employees
PATCH  /employees/{id}/permissions

# === SYNC ===
POST   /sync/push                  # {outbox: [...]}  → idempotent
GET    /sync/pull?since=...        # delta: katalog+mijoz+sozlama

# === HISOBOT / ANALITIKA ===
GET    /reports/pnl?period=        # foyda-zarar (Hisobotlar sahifasi)
GET    /reports/sales-dynamics
GET    /reports/top-products
GET    /reports/alerts             # kam qoldiq / zararga / kamaygan
GET    /reports/export?format=csv|pdf
```

---

## 7. Frontend arxitekturasi

### Mavjud dizaynni ko'chirish (muhim yutuq)
Hozirgi `.dc.html` fayllar allaqachon **React mantig'ida**:
- `class Component extends DCLogic` + `renderVals()` → oddiy **React funksional komponent** + `useMemo` (derived props)
- `this.state` / `this.setState` → **`useState`** yoki **Zustand**
- `sc-for` / `sc-if` / `{{ }}` → JSX (`.map()` / shartli render)
- `localStorage` feature-flag'lar → serverdagi `settings` + lokal cache

➡️ Bu **mexanik ko'chirish** — dizayn, ranglar, F2/F4 hotkeylar, savat mantig'i saqlanadi.

### Qatlam
```
React (renderer)
  └─ ipc bridge (preload) ──▶ Electron main
                                ├─ better-sqlite3 (lokal o'qish/yozish — tez)
                                └─ sync agent ──▶ FastAPI
```
- **O'qish/yozish avval lokal SQLite'ga** (bir zumda) → keyin fon rejimida serverga sync.
- TanStack Query serverdan pull'ni, Zustand kassaning joriy holatini (savat) boshqaradi.

### Ekranlar (mavjud prototipdan)
`Dashboard · POS Kassa · Mahsulotlar(+Ombor) · Xaridlar · Sotuvlar · Sotuvlarim · Qaytarishlar · Mijozlar · Smena · Hisobotlar · Xodimlar · Sozlamalar`

---

## 8. Analitika qatlami (kelajak)

1. **ETL:** `sales`/`sale_items` → Celery orqali **DuckDB** (yoki ClickHouse) warehouse'ga yig'iladi (kunlik/soatlik).
2. **Oldindan hisoblangan** (materialized) ko'rinishlar: kunlik savdo, kategoriya foydasi, top mahsulot → Hisobotlar sahifasi tez ochiladi.
3. **P&L** allaqachon dizaynda bor (sof tushum, foyda, marja, QQS) → real ma'lumot bilan to'ldiriladi.
4. **Bashorat (ML):** Prophet bilan sotuv prognozi → "qachon zaxira tugaydi", avtomatik buyurtma tavsiyasi.
5. **Alertlar** (kam qoldiq / zararga sotilgan / sotuvi kamaygan) — prototipda bor, real querylarga ulanadi.

Python/DuckDB bu bosqichda eng kuchli — aynan shu sabab FastAPI tanlandi.

---

## 9. Xavfsizlik va ruxsatlar

- **JWT** token + **PIN/parol** (bcrypt). Kassir tez kirishi uchun 4-6 xonali PIN.
- **RBAC** — prototipdagi rollar (Sidebar `savdoos_role` + Xodimlar ruxsatlari):
  - `Administrator` → hamma modul (egasi)
  - `Menejer` → Dashboard, Sotuvlar, Qaytarish, Mijozlar, Mahsulotlar, Hisobot, Smena
  - `Omborchi` → Mahsulotlar/Ombor, Xaridlar
  - `Kassir` → Kassa, Sotuvlarim, Qaytarish, Mijozlar
- **Ikki qatlamli ruxsat:** `role_permissions` (rol standarti) + `employee_permissions`
  (har xodimga alohida toggle — Xodimlar sahifasidagi ruxsat kalitlari aynan shu).
- Har API endpoint rol/ruxsatni tekshiradi (FastAPI dependency).
- Lokal SQLite shifrlanishi mumkin (SQLCipher) — nozik narx/foyda ma'lumoti uchun.
- **Audit log** — kim nimani, qachon o'zgartirdi (before/after JSONB), fizik o'chirish yo'q (soft-delete).

---

## 10. Paketlash va deploy

**Desktop (.exe):**
- `electron-builder` → **NSIS** installer (`SavdoOS-Setup-x.y.z.exe`)
- `electron-updater` → avtomatik yangilanish (server yoki S3'dan)
- Windows 11 ✓ (sizning muhitingiz)

**Server:**
- `docker-compose`: `postgres` + `redis` + `fastapi` (+ `nginx` reverse proxy, HTTPS)
- Migratsiya: `alembic upgrade head`
- Backup: Postgres kunlik dump; kassa SQLite fayli ham zaxiralanadi

---

## 11. Bosqichlar (roadmap)

### Bosqich 0 — Poydevor (1 hafta)
- Monorepo (pnpm), Electron+Vite+React skeleton, FastAPI skeleton, Docker, CI
- Dizayn tokenlari (Inter, ranglar, Phosphor), umumiy komponentlar (Sidebar, Modal, Table)

### Bosqich 1 — MVP: Offline kassa (2-4 hafta) 🎯
- Lokal SQLite schema + repo
- **POS Kassa** (savat, to'lov: naqd/karta, qaytim, chek chop etish)
- **Mahsulotlar + Ombor**, **Smena** (ochish/yopish), **Sotuvlarim**
- Bitta do'kon, serversiz — **to'liq offline ishlaydi**

### Bosqich 2 — Server va sync (3-4 hafta)
- FastAPI + PostgreSQL + JWT/RBAC
- Push/pull sync (outbox), ko'p filial
- **Xaridlar**, **Mijozlar/Qarz**, **Xodimlar/Ruxsatlar**, **Sozlamalar** (serverda)

### Bosqich 3 — Analitika (3-4 hafta)
- **Hisobotlar** real ma'lumot bilan (P&L, dinamika, top, alert)
- DuckDB warehouse + ETL, CSV/PDF eksport (dizaynda bor)
- Dashboard jonli ko'rsatkichlar

### Bosqich 4 — Kengaytmalar
- Sotuv bashorati (Prophet), avto-buyurtma tavsiyasi
- Telegram bot / mobil hisobot, fiskal modul integratsiyasi (soliq)

---

## Xulosa
Offline-first kassa (Electron+React+SQLite) + markaziy FastAPI (Postgres→DuckDB) — sizning
**.exe + katta ma'lumot + analitika** talablaringizga to'liq mos. Mavjud dizayn deyarli
o'zgarishsiz React'ga ko'chadi, shuning uchun Bosqich 1'ni tez ishga tushirish mumkin.

---

## 12. UI o'zgarishlari (2026-08-16 prototip yangilanishi)

So'nggi zip'da qo'shilgan funksiyalar va ularning backend/DB ta'siri:

| UI o'zgarishi | DB / API ta'siri |
|---|---|
| **Rollarga bo'lingan Sidebar** (Administrator/Menejer/Omborchi, `savdoos_role`) | `roles`, `role_permissions` — menyu ruxsat bo'yicha filtrlanadi |
| **Xodimlar — har xodim ruxsat toggle'lari** | `employee_permissions` (rol ustidan override) |
| **Mahsulotlar — Excel/CSV/1C import ustasi** (3 bosqich, ustun-mapping) | `POST /products/import/*`, `import_jobs` + `import_rows` (xato/holat) |
| **Mahsulotlar — Artikul ustuni** | `products.article_code` (unique), qidiruvda indeks |
| **Mijozlar — "Qarzni yopish" modali + to'lov tarixi** | `customer_payments` + `credit_transactions` (daftar) |
| **Mijozlar — qarz feature-flag** (o'chsa kartalar almashadi) | `settings` (payments.qarz) → server tomonida ham |
| **Qaytarishlar — sabab + omborga qaytarish/hisobdan chiqarish** | `returns.reason`, `returns.restock` (bool) |
| **POS — artikul bo'yicha qidiruv, elektron chek** | `products.article_code`, `sales` chek uid/receipt_no |
| **Xaridlar — "Yangi qoldiq" ko'rsatkichi** | `stock_movements` + `inventory` (kirim oldindan ko'rsatiladi) |

> ⚠️ **Rol nomlari:** Sidebar `Menejer`, Xodimlar sahifasi `Kassir` ishlatadi.
> `roles` jadvalida to'rttasi ham bor: **Administrator, Menejer, Omborchi, Kassir**.
