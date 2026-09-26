# Phase 6A — Admin Console + Subscription platformasi: REJA

**Holat: REJA (kod yozilmagan).** Bu hujjat implementatsiyadan OLDINGI beshta majburiy
yetkazmani o'z ichiga oladi: mavjud holat matritsasi, arxitektura, sxema, migratsiya va
majburlash (enforcement) matritsasi.

| | |
|---|---|
| Worktree | `.claude/worktrees/admin-6a` (asosiy checkout'dan ALOHIDA) |
| Branch | `p6a-admin-subscription` |
| Boshlang'ich SHA | `a0ea7ae91639be5552f141d2aae4c609419f380c` |
| Parallel fork | `p6b-pwa-iphone-rebrand` (`.claude/worktrees/pwa-6b`) — TEGILMAYDI |

---

## 1. CURRENT STATE MATRIX

Auditning yagona eng muhim xulosasi: **platforma-admin allaqachon bor, obuna esa umuman yo'q.**

### 1.1 Bor va qayta ishlatiladi

| Tushuncha | Qayerda | Hozir nima | Phase 6A da |
|---|---|---|---|
| Vendor admin API | `apps/server/app/api/v1/admin.py` (12 marshrut) | do'kon yaratish, ro'yxat, tafsilot, tarif, suspend, parol tiklash, soft-delete | **asos sifatida kengaytiriladi** |
| Vendor auth | `admin.py:251-284` `require_vendor` | master kalit + **majburiy TOTP** + IP ro'yxati → qisqa sessiya | saqlanadi, ustiga **rol** qatlami qo'shiladi |
| Vendor sessiyasi | `models/vendor.py:25-42`, TTL 2 soat | `jti` bilan bazada, **bekor qilinadi** | `admin_id` FK qo'shiladi (kim ekani ma'lum bo'lsin) |
| Rate-limit | `admin.py:146-180`, `VendorAuthAttempt` | Postgres'da, **fail-closed** (o'lchab bo'lmasa 503) | o'zgarishsiz |
| Vendor portal UI | `app/static/vendor_portal.html` (335 satr) | bitta statik HTML | **o'rnini `apps/admin` egallaydi**, HTML qoladi (zaxira) |
| Tenant izolyatsiyasi | `core/deps.py:12-45` | HAR autentifikatsiyalangan so'rovda bitta darvoza | **majburlash nuqtasi shu** |
| Ruxsat tizimi | `core/deps.py:121-155` `require()` | Role→Permission, ega/administrator **shartsiz o'tadi** | platforma-admin uchun ISHLATILMAYDI (pastga qarang) |
| audit_log | `models/sync.py:66-82`, `services/audit.py:13-32` | actor/action/entity/before/after | admin auditi uchun **yaramaydi** (sabab 1.3) |
| `/health`, `/health/ready` | `api/v1/health.py` | kalitlar **muzlatilgan** (`test_capability_gate.py`) | kalit qo'shilmaydi |
| Tarif limitlari | `branches.py:27-44`, `employees.py:326-327` | `PLAN_LIMITS`, `USER_LIMITS` | **read-through** orqali yangi modeldan o'qiydi |

### 1.2 Yo'q — noldan quriladi

| Nima | Isbot |
|---|---|
| Obuna / billing / litsenziya / trial kodi | butun `apps/server` va `packages` bo'ylab qidirildi — **hech narsa yo'q** |
| Kompaniya darajasida holat ustuni | `models/org.py:11-19` — `status`/`is_active` **yo'q**, faqat `deleted_at` |
| Platforma-admin shaxsi | vendor amallari `actor_id=None` bilan yoziladi (`admin.py:322,441,513,668,695,710`) |
| To'lov reyestri | yo'q |
| `apps/admin` | yo'q; eng yaqin naqsh — `apps/manager` + `vite.preview.config.ts` |

### 1.3 Uchta strukturaviy nuqson (Phase 6A aynan shularni tuzatadi)

1. **Tarif va suspend — jadval emas, `settings` JSON qatori.**
   `Setting(key='plan', value={'plan':...})` va `Setting(key='suspended', value={'on':true})`.
   «Kimning obunasi ertaga tugaydi?» degan so'rov JSONB bo'ylab skan talab qiladi — indekslab bo'lmaydi.
2. **`ux_settings_company_key` KAFOLATLANMAGAN** (`required_schema.py:519`, OPTIONAL ro'yxatda).
   Eski bazada bitta `(company, key)` uchun IKKI qator bo'lishi mumkin, va `deps.py:40-42`,
   `auth.py:79`, `admin.py:536-538` `.first()` ni **tartibsiz** chaqiradi → nodeterministik.
   **Obuna holati bu naqshni NUSXALAMAYDI.**
3. **audit_log admin auditi uchun yaramaydi:** `company_id` ustuni yo'q, `actor_id` FK'si
   `employees` ga (vendor operatorini yozib bo'lmaydi), `/audit` INNER JOIN qiladi
   (`audit.py:32-34`) — `actor_id=None` qatorlar **ko'rinmaydi**, o'zgarmaslik (immutability)
   to'sig'i yo'q, indeks yo'q.

---

## 2. ARCHITECTURE PLAN

### 2.1 Platforma-admin shaxsi — yangi jadval, `employees` EMAS

`employees` ga qo'shish **rad etildi**, uchta aniq sabab bilan:
- `Employee.company_id` **NOT NULL** (`models/auth.py:41`) — «kompaniyasiz» admin modelga sig'maydi;
  soxta kompaniyaga bog'lash tenant izolyatsiyasini buzadi.
- Parolli akkaunt telefoni **global noyob** (`ux_employees_phone_pw`) — admin telefoni mijoz
  do'konidagi telefon bilan to'qnashadi.
- `require(...)` da **ega/administrator shartsiz o'tadi** (`deps.py:128`) — «faqat platforma admini»
  darvozasini ruxsat kodi bilan qurish **xavfli**.

**Qaror:** `platform_admins` jadvali + `vendor_sessions.admin_id`. Tashqi darvoza o'zgarmaydi
(kalit + TOTP + IP), ichkarida **rol** tekshiriladi.

```
so'rov → require_vendor (kalit+TOTP+IP+sessiya)  [MAVJUD]
       → require_platform_role(SUPER_ADMIN|ADMIN|SUPPORT_READONLY)  [YANGI]
       → marshrut
```

Tenant foydalanuvchisi (`get_current_employee`) `/admin/**` ga **hech qachon** kira olmaydi:
ikki dependency turli, birini ikkinchisi qondirmaydi. Bu testda qulflanadi.

### 2.2 Obuna holati — birinchi darajali jadvallar

`settings` JSON naqshi **takrorlanmaydi**. Yangi jadvallar: `plans`, `subscriptions`,
`subscription_payments`, `admin_audit_log`.

### 2.3 Tarif limitlari — read-through, mirror EMAS

Hozir `branches.py`/`employees.py` `settings['plan']` ni o'qiydi. Ikki manba (jadval + JSON mirror)
xavfli, shuning uchun bitta yordamchi:

```python
# app/services/subscription/plan_limits.py
resolve_plan(db, company_id) -> str
#  1) subscriptions → plans.code   (yangi, agar obuna yozuvi bo'lsa)
#  2) settings['plan']             (eski, grandfathered)
#  3) "start"                      (standart, hozirgi xulq)
```

Mavjud limit chaqiruvlari shu yordamchiga o'tadi. **Mirror yozuv yo'q, ikki haqiqat manbai yo'q.**

### 2.4 Admin frontend — `apps/admin`, brauzer uchun

- `apps/manager` **naqshi**, lekin Electron'siz: `vite-plugin-electron`, `electron*` **olinmaydi**.
- Tayyor shablon: `apps/manager/vite.preview.config.ts` — brauzer-only Vite konfiguratsiyasi
  allaqachon mavjud va Playwright E2E'da isbotlangan.
- `@` alias = `packages/shared/src` (vite `resolve.alias` **va** tsconfig `paths` — ikkalasida).
- `dedupe: ["react","react-dom","react-router-dom","zustand"]` — majburiy (har app o'z
  `node_modules`iga ega).
- Hash router (statik hostda SPA-fallback rewrite kerak emas).
- CI `frontend` jobiga ikki qadam qo'shiladi: `Install admin deps` + `Typecheck admin`.

⚠️ Brauzerda `window.savdoosSecure` yo'q → shared API klienti tokenni **ochiq localStorage**ga
yozadi. Admin uchun bu qabul qilinmaydi: `apps/admin` o'z token saqlagichini beradi
(`sessionStorage`, tab yopilsa yo'qoladi) — vendor sessiyasi TTL'i 2 soat bo'lgani uchun bu mos.

---

## 3. SCHEMA PLAN

Hammasi `public` sxemada, `FullMixin` bilan (`id`, `created_at`, `updated_at`, `deleted_at`,
`row_version`, `client_uuid`), `app/models/subscription.py` da; `models/__init__.py` ga import.

### 3.1 `plans`

| Ustun | Tur | Izoh |
|---|---|---|
| `code` | String | `pilot` \| `start` \| `business` \| `network` |
| `name` | String | ko'rinadigan nom |
| `billing_period` | String | `monthly` (hozircha yagona) |
| `price` | Numeric(14,2) | **kodda qotirilmaydi** |
| `currency` | String(3) | `UZS` |
| `grace_days` | Integer | standart 3 |
| `max_branches` / `max_users` / `max_tills` | Integer \| NULL | NULL = cheksiz |
| `is_active` | Boolean | |

Indeks: `ux_plans_code` (noyob, `deleted_at IS NULL`).

### 3.2 `subscriptions`

| Ustun | Tur |
|---|---|
| `company_id` | UUID FK `companies.id` |
| `plan_id` | UUID FK `plans.id` |
| `started_at`, `current_period_start`, `current_period_end`, `grace_until` | timestamptz |
| `status` | String: `ACTIVE` \| `GRACE` \| `RESTRICTED` \| `CANCELLED` |
| `cancelled_at`, `restricted_at` | timestamptz \| NULL |

- **Har kompaniyaga BITTA faol obuna:** `ux_subscriptions_company` (noyob, `deleted_at IS NULL`).
- Vaqt hisoblash uchun: `ix_subscriptions_period_end` (`current_period_end`) va
  `ix_subscriptions_grace` (`grace_until`) — «ertaga tugaydiganlar» so'rovi indeksli bo'lsin.
- Barcha vaqtlar **timezone-aware UTC**; ko'rsatishda filial zonasiga o'giriladi.

### 3.3 `subscription_payments` — O'ZGARMAS

`company_id`, `subscription_id`, `amount`, `currency`, `method` (`CASH`\|`BANK_TRANSFER`\|`QR`\|`OTHER`),
`paid_at`, `period_from`, `period_to`, `reference`, `note`, `created_by_admin` (FK `platform_admins`),
`client_uuid`, `created_at`.

- **UPDATE/DELETE yo'q.** Tuzatish — `reversal_of_id` (o'ziga FK) bilan **yangi qator**.
- `ux_subscription_payments_client_uuid` (noyob, `client_uuid IS NOT NULL`) — idempotentlik.

### 3.4 `platform_admins`

`login` (noyob), `password_hash`, `totp_secret`, `role` (`SUPER_ADMIN`\|`ADMIN`\|`SUPPORT_READONLY`),
`is_active`, `last_login_at`. Parol/TOTP hech qachon javobga chiqmaydi.

### 3.5 `admin_audit_log` — ALOHIDA va O'ZGARMAS

Mavjud `audit_log` **ishlatilmaydi** (1.3-band). Yangi jadval:
`actor_admin_id`, `action`, `target_type`, `target_id`, `company_id` (nullable), `before_summary`
(JSONB), `after_summary` (JSONB), `reason`, `request_id`, `created_at`.

- Parol/token/sir **yozilmaydi** — yozuvchi funksiya oq-ro'yxat bilan filtrlaydi.
- O'zgarmaslik: `cash.fn_block_mutation` naqshidagi trigger (UPDATE/DELETE to'siladi).
- `ix_admin_audit_company_created`, `ix_admin_audit_actor_created`.

---

## 4. MIGRATION PLAN

Loyihada **Alembic yo'q**. Konvensiya (audit tasdiqladi): model → `models/__init__.py` importi →
`create_all` boot'da jadvalni yaratadi; indeks **IKKI joyda** (model `__table_args__` **va**
`initdb._ensure_indexes`).

**ANIQ (versiyalangan) migratsiya KERAK EMAS** — faqat yangi jadval qo'shilmoqda, mavjud ustun
tipi o'zgarmaydi, ma'lumot ko'chirilmaydi.

### 4.1 Grandfathering — eng muhim qoida

> **Obuna yozuvi YO'Q = majburlash YO'Q.**

Mavjud ijarachilar (Fayzan ham) `subscriptions` da qatorsiz qoladi va **hech qachon avtomatik
cheklanmaydi**. Enrollment faqat aniq admin amali bilan. Bu §24 talabining to'g'ridan-to'g'ri
bajarilishi va u **testda qulflanadi**: «qatorsiz kompaniya har qanday yozuvni bajaradi».

⚠️ Bu ataylab qilingan qaror, jim fail-open emas: yozuv yo'qligi «to'lanmagan» degani emas,
«ro'yxatga olinmagan» degani.

### 4.2 Boot darvozasiga BOG'LANMAYDI

Yangi obyektlar `REQUIRED_COLUMNS`/`REQUIRED_INDEXES` ga **qo'shilmaydi**: u ro'yxatlarga qo'shish
prod boot'ini ularga bog'laydi (`initdb.py:1936-1940` → `RuntimeError` → `start.sh set -e` → konteyner
ko'tarilmaydi). Tasnif: noyob indekslar → `OPTIONAL_UNIQUE_INDEXES`, tezlik → `PERFORMANCE_INDEXES`.
Majburiy darajaga ko'tarish — **majburlash yoqilgan relizda**, alohida qaror.

### 4.3 Qulf xavfi

`create_all` bitta tranzaksiya; yangi jadvallarning FK'lari `companies` ga **SHARE ROW EXCLUSIVE**
qulf oladi. Deploy tinch oynada; `lock_timeout=2s` × 5 urinish, keyin boot FATAL (fail-closed).

### 4.4 Test qo'riqchilari (loyiha konvensiyasi)

- `IDEMPOTENCY_INDEXES` ga qo'shilsa — `test_runtime_columns.py:325` dagi literal to'plam ham yangilanadi.
- Yangi jadval FK'lari `REQUIRED_FOREIGN_KEYS` ga **qo'shilmaydi** (test ikki tomonlama moslikni talab qiladi).
- PG-only testlar `ci.yml:238-245` **va** `252-267` dagi `FILES` ro'yxatiga qo'shiladi.

---

## 5. ENFORCEMENT MATRIX

### 5.1 Holat — so'rov vaqtida hisoblanadi (scheduler AUTHORITATIVE EMAS)

Yagona kanonik funksiya — `services/subscription/state.evaluate_subscription_access(sub, now)`.
Natija **enum emas, uchlik**: `managed` · `effective_status` · `reason` (nega aynan shu natija).

```
1. yozuv yo'q                          -> managed=False, status=None, GRANDFATHERED
2. CANCELLED                           -> RESTRICTED, CANCELLED           (terminal)
3. qo'lda RESTRICTED (`restricted_at`) -> RESTRICTED, MANUAL_RESTRICTION  (vaqtdan USTUN)
4. now <  current_period_end           -> ACTIVE,     PERIOD_ACTIVE
5. now <  grace_until                  -> GRACE,      GRACE_PERIOD
6. aks holda                           -> RESTRICTED, EXPIRED
```

⚠️  **«Boshqaruvda emas» ≠ ACTIVE.** Yozuvsiz do'kon `managed=False` va `effective_status=None`
qaytaradi. Uni `ACTIVE` deb ko'rsatish keyinchalik «ACTIVE = to'lagan» degan yolg'on hisobotga
olib kelardi — u ro'yxatga OLINMAGAN, pul haqida hech narsa deyilmagan.

**Saqlangan `status` va hisoblangan holat — ikki boshqa narsa.** Bazaga faqat `ACTIVE`,
`RESTRICTED`, `CANCELLED` yoziladi; **`GRACE` hech qachon saqlanmaydi**, shu sabab saqlangan
qiymat eskira olmaydi. Ustun amallar jurnali EMAS — jurnal `admin_audit_log`.

### 5.2 Toifa bo'yicha siyosat

| Toifa | ACTIVE | GRACE | RESTRICTED |
|---|---|---|---|
| Sotuv, qaytarish | ✅ | ✅ ogohlantirish | ⛔ |
| Kirim, kirim tuzatish | ✅ | ✅ | ⛔ |
| Inventarizatsiya, hisobdan chiqarish, ko'chirish | ✅ | ✅ | ⛔ |
| Naqd amal | ✅ | ✅ | ⛔ |
| **Smena OCHISH** | ✅ | ✅ | ⛔ |
| **Smena YOPISH** | ✅ | ✅ | **✅ ATAYLAB RUXSAT** |
| Mijoz/qarz, ta'minotchi, mahsulot, filial, partiya yozuvlari | ✅ | ✅ | ⛔ |
| Operatsion sozlamalar | ✅ | ✅ | ⛔ |
| **Login, o'qish, hisobot, eksport** | ✅ | ✅ | **✅** |
| Parol o'zgartirish, logout | ✅ | ✅ | ✅ |

⚠️ **Smena yopish hech qachon to'silmaydi.** Yarim tunda obuna tugagani sabab kassada ochiq smena
qolsa — pul qoldig'i hisoblanmay qoladi. Bu ataylab qilingan istisno va testda qulflanadi.

### 5.3 Texnik majburlash

- Yangi dependency `require_subscription_write` — biznes routerlarga **router darajasida** qo'shiladi.
- **Qo'riqchi test:** har bir `POST/PUT/PATCH/DELETE` marshrut yo himoyalangan to'plamda, yo aniq
  oq-ro'yxatda (`auth`, `admin`, `billing`, smena yopish) bo'lishi shart. Yangi yozuv endpointi
  qo'shilib, matritsaga kiritilmasa — **test qizaradi**. Majburlashning haqiqiy kafolati shu
  (84 ta marshrutni qo'lda belgilashga tayanilmaydi).
- Xato: HTTP **403** + `X-Error-Code: SUBSCRIPTION_RESTRICTED` (`core/error_codes.py` ga
  qo'shiladi; sarlavha CORS `expose_headers` da allaqachon ochilgan). Xom matnga tayanilmaydi.

  ⚠️ **402 Payment Required RAD ETILDI.** Semantik jihatdan u aniqroq, lekin repo'da 402
  **hech qayerda ishlatilmagan** va tarqatilgan mijozlar uni maxsus ishlamaydi. 403 esa
  allaqachon ikki joyda shu ma'noda ishlatiladi — «do'kon to'xtatilgan» (`deps.py:44`) va
  ruxsat rad etish — va mobil klient uni `ApiErrorKind.permission` ga xaritalaydi
  (`apps/mobile/lib/api.dart:1009`). Ya'ni 403 bilan eski mijoz ham tushunarli xato
  ko'rsatadi, 402 bilan esa noma'lum holatga tushardi.

  ⚠️ Farq: «to'xtatilgan do'kon» tekshiruvi `get_current_employee` ICHIDA va **hamma narsani**
  to'sadi (o'qishni ham). Obuna cheklovi bunday QILMAYDI — u alohida dependency bo'lib faqat
  yozuv marshrutlariga qo'yiladi, o'qish/hisobot/eksport ochiq qoladi.
- Mijozga ogohlantirish uchun `/health` **tegilmaydi** (kalitlari muzlatilgan); obuna holati
  `GET /me` yoki yangi `GET /billing/state` orqali beriladi: `{status, period_end, grace_until, days_left}`.

### 5.4 Yangilash (renewal) semantikasi

`client_uuid` bo'yicha idempotent (noyob indeks + `ON CONFLICT`). Ikki marta bosish = bir marta uzaytirish.

| Holat | Yangi `current_period_start` | Yangi `current_period_end` |
|---|---|---|
| ACTIVE (muddatdan oldin) | o'zgarmaydi | **eski `current_period_end`** + N kun |
| GRACE | `now` | `now` + N kun |
| RESTRICTED | `now` | `now` + N kun |

Ya'ni muddatdan oldin to'lagan mijoz kun yo'qotmaydi; kechikkan mijozga davr to'lov kunidan
boshlanadi. Oylik davr — **yillik sana** bo'yicha (17-oktabr → 17-noyabr), kalendar oy emas;
oy oxiri qisqartiriladi (31-yanvar → 28/29-fevral) va **qisqartirish yopishib qolmaydi**
(keyingi oy asl kunga qaytadi). `PILOT` esa **aniq 30 kun** — kalendar bilan ishi yo'q.

⚠️  **`CANCELLED` — terminal.** Yangilash uni jimgina tiriltirmaydi (`RenewalRefused`);
qayta ishga tushirish alohida, aniq amal. `cancel_at_period_end` semantikasi **qo'shilmaydi**.

⚠️  **Yangilash qo'lda cheklovni YECHMAYDI.** Davr uzayadi, lekin `MANUAL_RESTRICTION` kuchda
qoladi — to'lov intizomiy qarorni yashirincha bekor qilmasin. Yechish uchun aniq `restore` kerak.

---

## 6. Implementatsiya tartibi (taklif)

1. Sxema + modellar + `initdb` indekslari + grandfathering testi
2. Holat hisoblash (sof funksiya) + chegara testlari (Fev 28/29, oy oxiri, DST, zona)
3. `platform_admins` + rol qatlami + RBAC/IDOR testlari
4. Admin API: companies, plans, subscriptions, renewal (idempotent), payments, audit
5. Majburlash dependency + **84-marshrut qo'riqchi testi**
6. `apps/admin` frontend
7. Staging: A=ACTIVE, B=GRACE, C=RESTRICTED sintetik ijarachilar, muzlatilgan soat
8. Adversarial ko'rik (A–H)

### 6.1 Majburlash yoqilishidan OLDINGI shart — tayyorlik darvozasi

⚠️  Hozir 5 yangi jadval `/health/ready` tomonidan **tekshirilmaydi** (repoda `REQUIRED_TABLES`
tushunchasi yo'q; jadval mavjudligi faqat `REQUIRED_COLUMNS`/`REQUIRED_INDEXES` orqali bilvosita
ko'riladi). Ya'ni `create_all` jadval yaratmay qolsa tayyorlik YASHIL qolardi.

Bu **qarz emas, majburlashning kirish sharti**: obuna majburlash kodi yoqilgan AYNI relizda
`plans`, `subscriptions`, `subscription_payments`, `platform_admins`, `admin_audit_log` va
ularning noyob indekslari **majburiy darvozaga** ko'tariladi. Server obuna kodi bilan ishlab
turib, obuna sxemasisiz READY bo'la OLMAYDI. Ikkalasi bitta commitda keladi — oraliqda
«majburlash bor, sxema yo'q» holati tug'ilmasin.

### 6.2 PG18 mashqi (majburlashdan oldin)

`SCHEMA PATH ACCEPTED PENDING PG18 REHEARSAL` — quyidagilar isbotlanadi: bo'sh PG18 · mavjud
production-o'xshash PG18 · birinchi boot · ikkinchi boot · restart · eski kod + yangi sxema ·
backup → toza PG18 restore · sxema barmoq izi · tayyorlik.

**Mijoz tomonidagi obuna UX — DEFER** (§21/§23): `p6b-pwa-iphone-rebrand` main'ga qo'shilmaguncha
`packages/shared` dagi klient ekranlariga tegilmaydi. Hozir faqat **shartnoma** belgilanadi:
402 + `SUBSCRIPTION_RESTRICTED` + `GET /billing/state`.
