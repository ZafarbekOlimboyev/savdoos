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

---

## 7. OBUNA HAYOT SIKLI — EGA QARORI (2026-09-27, YAKUNIY)

### 7.1 Qaror
**KOMPANIYAGA BITTA `subscriptions` QATORI — umrbod.** Bekor qilingan mijoz qayta obuna
bo'lsa YANGI QATOR YOZILMAYDI. Mavjud qator authoritative bo'lib qoladi, qayta faollashtirish
esa qulf ostidagi ANIQ hayot-sikli o'tishi orqali bajariladi.

### 7.2 Sxema natijasi
| Obyekt | Qaror |
|---|---|
| `ux_subscriptions_company` | **O'ZGARMAYDI** — nomi, ta'rifi, `__table_args__` dagi yozuvi bayt-bayt o'sha |
| `ck_sub_deleted_never` | `CHECK (deleted_at IS NULL)` — yuqoridagi qisman indeksni **TO'LIQ** qiladi |
| `ck_sub_restricted_iff` | `CHECK ((status = 'RESTRICTED') = (restricted_at IS NOT NULL))` |
| `ck_sub_cancelled_iff` | `CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL))` |
| `ck_sub_status_persistable` | `CHECK (status IN ('ACTIVE','RESTRICTED','CANCELLED'))` — `GRACE` saqlanmaydi |
| `ux_subscriptions_company_current` | **YARATILMAYDI** — yuqoridagi CHECK ostida to'liq qamrab olingan |
| `ux_subpay_client_uuid` | `(company_id, client_uuid)` — **O'SHA NOM ostida**, model + `initdb.py:651-653` bitta commitda |
| Triggerlar | **YO'Q** |

⚠️  **Indeks nomlari MUZLATILGAN.** `_index()` faqat nomga qaraydi (`initdb.py:346`), `_unique_index_states`
esa kalit ustunlarni ham, predikatni ham o'qimaydi (`required_schema.py:1044-1070`). Nom bo'shatilsa,
rollback ESKI ta'rifni **hech nima yozmasdan** qayta tiklaydi. Joyida qayta ta'riflash — drop-and-rename emas.

⚠️  **Nega trigger yo'q.** `tenant_purge.py:726` allaqachon `ALTER TABLE ... DISABLE TRIGGER USER`
ishlatadi va DELETE triggerlarini `pg_trigger (tgtype & 8)` bilan **avtomatik topadi** (`:128`) — yangi
trigger ko'rib chiqiladigan diff'siz o'sha bypass'ga qo'shilardi. Bundan tashqari `cash.fn_block_mutation`
da rol tekshiruvi yo'q: bazadagi o'zgarmaslik — **egalik chegarasi**, imtiyoz chegarasi emas, ilova esa
egasi (staging'da o'lchandi: `DATABASE_URL` roli `postgres`). CHECK'lar yomon yozuvni rad etadi va
`DELETE` ni to'smaydi — `tenant_purge` ga o'zgarish kerak emas.

⚠️  4 ta CHECK 2.5 da `REQUIRED_PG_CONSTRAINTS` ga **kirmaydi** (`required_schema.py:540-545` qoidasi).
Demak **xizmat qatlami CHECK'siz bazada ham to'g'ri ishlashi SHART** — CHECK'lar to'r, majburlovchi emas.

### 7.3 Ruxsat etilgan o'tishlar — boshqasi YO'Q
```
enrol                        -> ACTIVE
ACTIVE            <-> RESTRICTED     (restrict / restore)
ACTIVE|RESTRICTED  -> CANCELLED      (cancel)
CANCELLED          -> ACTIVE         FAQAT reactivate()
```
**`restore()` sharti (majburiy, aks holda bu CANCELLED→ACTIVE ga ikkinchi yo'l bo'lardi):** qulf ol,
so'ng **saqlangan** `status == 'RESTRICTED'` VA `restricted_at IS NOT NULL` bo'lishini talab qil;
`CANCELLED` qatorni `reactivate()` dagi bilan AYNI xato kodi bilan rad et. CHECK oldingi qatorni
ko'ra olmaydi, shuning uchun buni faqat kod yopadi. `state.py:74-76` CANCELLED ni operatorga
`RESTRICTED` ko'rinishida ko'rsatadi — `restore()` **ko'rinishga emas, saqlangan qiymatga** qarasin.

### 7.4 Qulf va qayta o'qish idiomasi — MAJBURIY
```python
db.flush()                                   # autoflush=False: qulfdan OLDIN, oralarda emas
row = (db.query(Subscription)
         .filter(Subscription.company_id == cid)
         .with_for_update(key_share=True)    # FOR NO KEY UPDATE
         .populate_existing().one())         # <- usiz bu QAYTA O'QISH EMAS
```
- `populate_existing()` **SHART**: `SessionLocal(autoflush=False, expire_on_commit=False)`
  (`db/session.py:72`) identity map'dagi eski nusxani qaytaradi va qulf ostidagi qaror eskirgan
  qiymatda qabul qilinardi. Uy qoidasi: `catalog_import_v2.py:69-75`, `lot_resolution.py:332`,
  `lot_return.py:343`, `receipt/jobs.py:190`.
- `key_share=True` (**`FOR UPDATE` EMAS**): `subscription_payments.subscription_id` FK'li INSERT ota
  qatorga KEY SHARE oladi, `FOR UPDATE` esa u bilan to'qnashib **deadlock** berardi.
- ⚠️  `cashops.py:108` da `populate_existing` yo'q va bu **to'g'ri**: u qulfdan keyin faqat `shift.id`
  va yangi SQL agregatlarini o'qiydi. Bizda qatordan `status` o'qiladi — shuning uchun bizda SHART.
- **Bitta UPDATE qoidasi:** CHECK'lar deferrable emas. `before_summary` ni qur → hamma hayot-sikli
  ustunini birga tayinla → audit qatorini qo'sh → commit. Tayinlashlar **orasida flush qilma**.

### 7.5 `cancelled_at` / `restricted_at` / `started_at` semantikasi
- **`cancelled_at` — FAQAT JORIY HOLAT.** `NOT NULL` ⟺ `status = 'CANCELLED'`. Qayta faollashtirishda
  `NULL` ga tushadi. Qayta bekor qilinsa **OXIRGI** bekor qilishni ko'rsatadi. **Tarix ustuni EMAS.**
- **`restricted_at`** — xuddi shunday.
- **`started_at` — O'ZGARMAS.** Kompaniya obuna boshqaruviga BIRINCHI marta kirgan lahza.
  Qayta faollashtirish uni **o'zgartirmaydi**.
  ⚠️  Tuzatish: qoralamada «`started_at = now`» degan band bor edi, asosi — `add_months` yillik sanani
  `started_at` dan hisoblaydi degan taxmin. Bu **noto'g'ri**: `add_months` (`periods.py:37-50`) o'ziga
  BERILGAN qiymatni qisqartiradi, chaqiruvchi esa `renewal_base` natijasini beradi
  (`current_period_end` yoki `now`) — `started_at` ni **hech qachon**. `started_at` ning repoda
  o'quvchisi yo'q, ya'ni uni yozish billingni o'zgartirmaydi, faqat «mijoz qachondan» javobini yo'qotadi.
- Bekor qilish/qayta faollashtirish **tarixi** — `admin_audit_log`.

### 7.6 Audit semantikasi
- Har o'tish uchun **AYNI TRANZAKSIYADA** bitta `admin_audit_log` qatori.
- `action`: `SUBSCRIPTION_CREATE|CANCEL|REACTIVATE|RESTRICT|RESTORE`.
- **Majburiy maydonlar** (CHECK bilan, `CREATE TABLE` bilan keladi):
  `action` obuna hodisasi bo'lsa — `actor_admin_id`, `before_summary`, `after_summary`, `reason`
  hammasi `NOT NULL` bo'lishi shart.
- **Yangi ustunlar:** `actor_login String(64)`, `actor_role String(24)`, `actor_kind String(16) NOT NULL`
  + `CHECK ((actor_kind='ADMIN') = (actor_admin_id IS NOT NULL))`. Sabab: `ux_platform_admins_login`
  qisman (`deleted_at IS NULL`), ya'ni soft-delete'dan keyin login qayta ishlatilishi mumkin —
  `actor_admin_id` yolg'iz «kim» savoliga javob bermaydi.
- `before_summary` **aniq kalitlar ro'yxatidan** quriladi (umumiy filtrdan emas, u jimgina kalit
  tushirib qoldirardi): `status, cancelled_at, restricted_at, plan_id, started_at,
  current_period_start, current_period_end, grace_until, row_version`.
- ⚠️  **JSON PRIMITIVLARI.** `JSONB = _PGJSONB().with_variant(JSON(), "sqlite")` (`db/types.py:20`)
  va engine `json_serializer`siz quriladi (`db/session.py:44`) — snapshot'ga `datetime` qo'yilsa
  `json.dumps` **TypeError** beradi va har cancel/reactivate 500 bo'lardi. Sana ISO-8601 satr,
  UUID `str`, `Decimal` `str` — bitta yordamchi orqali, round-trip test bilan.
- **Zanjir:** har `(company_id, target_id)` uchun N-hodisaning `before_summary` si N−1 ning
  `after_summary` siga teng bo'lsin (ishga tushadigan so'rov + test). Tashqaridan qilingan har qanday
  o'zgartirish zanjirni ko'rinadigan qilib uzadi. `row_version` ham o'sha qulflangan UPDATE ichida oshadi.
- **Append-only — KONSTRUKSIYA bo'yicha** (UPDATE/DELETE yo'li yo'q), trigger bilan emas. Da'vo aynan
  shu kuchda yoziladi: hech bir kod yo'li UPDATE/DELETE yubormaydi; before/after zanjiri buzilishni
  ko'rsatadi; tenant purge uni butunlay o'chiradi; imtiyoz bilan majburlanmagan, chunki ilova roli
  sxema egasi.
- `admin_audit_log` da `subscriptions` ga FK **ataylab yo'q** — audit mustaqil yashaydi.

### 7.7 To'lov va yangilash
- `record_payment`: **avval** obuna qulflanadi (7.4 idiomasi), **keyin** to'lov INSERT qilinadi,
  keyin `renewal_base` qayta yuklangan obyektda chaqiriladi. Bu to'lovni qayta faollashtirishga
  nisbatan ketma-ketlashtiradi (TOCTOU yopiladi) va eskalatsiya deadlock'ini konstruksiya bilan yo'q qiladi.
- `renewal_base` `CANCELLED` da `RenewalRefused` beradi — **to'lov bekor qilingan obunani tiriltirmaydi**.
- Yangilashni harakatga keltirgan to'lov `period_from`/`period_to` ni **yangilash natijasidan** yozadi
  (storno qatorlarida ikkalasi ham bo'sh qolishi qonuniy — blanket `NOT NULL` qo'yilmaydi).
- Idempotentlik kaliti: `(company_id, client_uuid)`.

### 7.8 R10 — bu KOD chegarasi, baza chegarasi EMAS
Ochiq yoziladi. Statik qo'riqchi test: `app/services/subscription/lifecycle.py` dan tashqari birorta
modul `Subscription.status` yoki `cancelled_at` ga yozmasin.

### 7.9 Phase 2.5 implementatsiya tartibi
1. `state.py:78` `and` → `or` (fail-closed `MANUAL_RESTRICTION`) + `tests/test_subscription_state.py:84`
   dagi qadab turgan testni qayta yozish.
2. 4 ta obuna CHECK'i + `admin_audit_log` CHECK'lari + `actor_login`/`actor_role`/`actor_kind` —
   hammasi `__table_args__` da.
   **2a.** `cancelled_at`/`restricted_at`/`started_at` kontrakti `Subscription` docstring'iga +
   bazasiz bikondisional round-trip testi.
3. `ux_subpay_client_uuid` → `(company_id, client_uuid)`, o'sha nom, model + `initdb` bitta commitda.
4. Bazasiz drift testi: 9 ta `initdb` DDL satri model `Index` ta'riflariga mos (nom, kalit ustunlar, predikat).
5. `app/services/subscription/lifecycle.py` — `enrol`/`cancel`/`reactivate`/`restrict`/`restore`.
   **5a.** To'lov/yangilash yozuvchisi (7.7).
6. PG konkurentlik testlari — qatorni chaqiruvdan OLDIN sessiyaga yuklab; har amal uchun `CANCELLED`
   qatorni rad etish testi; audit zanjiri; JSONB round-trip; statik qo'riqchi.
7. PG18 mashqi — jumladan **bazaga qaragan** tekshiruvlar: `pg_constraint` da 4 ta nom,
   `pg_index.indkey` aynan `(company_id, client_uuid)`; production shaklidagi bazada **yangilash** yo'li.
8. To'liq regressiya.

### 7.10 2.5 dan TASHQARIDA qoladi
- **Yangilash yo'li** production shaklidagi `companies` ustida — 7-qadam mashqi.
- **Reactivation replay kaliti** — 6A/3 (endpoint paydo bo'lganda). Hozir faqat arzon yarmi:
  noto'g'ri holat xatosi javobida JORIY statusni qaytaradi.
