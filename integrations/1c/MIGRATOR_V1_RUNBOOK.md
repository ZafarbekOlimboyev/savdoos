# Fayzan 1C Migrator V1 — operator runbook

Yo'nalish: **1C → BinOS**, bir martalik. 1C faqat o'qiladi. Barcha buyruqlar `apps/server` ichida.

```
python -m app.tools.migrate_1c <buyruq> …
```

## Bosqichlar

| # | Qadam | Buyruq | Yozadimi |
|---|---|---|---|
| 1 | 1C'dan eksport (`.json` + `.json.sha256`) — FAQAT sandboxga tiklangan nusxadan | 1C: «BinOS uchun eksport» (discovery'dan keyin yoziladi) | 1C'ga YO'Q |
| 2 | Fayl imzosi va tuzilmasi | `verify-bundle --bundle X` | yo'q |
| 3 | Quruq yurish (DB read-only, REPEATABLE READ, ijobiy + negativ isbot) | `dry-run --bundle X --company-code fayzan1 --out report.json --summary-out summary.txt [--unit-map units.json]` | yo'q |
| 4 | Qaror shabloni | `mapping-template --report report.json --out mapping.json` | yo'q |
| 5 | Conflict review: CANDIDATE/AMBIGUOUS/DELETED_MATCH qarorlari, har siyosat, ombor→filial, (ixtiyoriy) `prepared_by/at` | qo'lda | — |
| 6 | Reja tekshiruvi (yoziladigan HAMMA narsa rejada) | `plan --report report.json --mapping mapping.json --out plan.json` | yo'q |
| 7 | Rehearsal (staging/nusxa) — DOIM ROLLBACK | `apply … --expect-system-identifier <sysid> --rehearse` | yo'q (rollback) |
| 8 | **Final fresh snapshot**: savdoni to'xtatish va freeze'ni HUJJAT bilan tasdiqlash → YANGI nusxa → sandboxga tiklash (`SANDBOX_RESTORE_RUNBOOK.md`) → yangi eksport → 2–6 qayta; oldingi qarorlar yangi hisobotga ko'chiriladi, farqlar qayta ko'riladi | — | — |
| 9 | APPLY (alohida yozma ruxsat bilan) | `apply … --expect-system-identifier <sysid> --commit` | HA |
| 10 | Post-verify (read-only) — apply'dan DARHOL keyin | `verify-applied --company-code fayzan1 --job-id <id>` | yo'q |
| 11 | BinOS POS savdoni ochish; katalogni LIVE qilish. **Production'da Phase 5A darvozasi `/catalog/v2/cutover-complete` ni 403 bilan yopadi** — bu qadam uchun alohida tasdiqlangan o'zgarish (darvozani ongli ochish yoki maxsus CLI qadami) kerak; hozircha faqat staging'da | — | HA |

`dry-run` chiqish kodi: 0 — rekonsiliatsiya MOS, 3 — MOS EMAS. `plan`: 0 — reja tayyor, 2 — muammolar ro'yxati.
`verify-applied`: 0 — reja bazada isbotlandi va job `committed`, 4 — farq bor.

## Himoyalar

- **Kesim YANGILIGI (`freshness.py`).** `apply` kesimni HOZIRGI vaqt bilan solishtiradi — imkon
  bo'lsa yozilayotgan **bazaning `clock_timestamp()`** i bilan (`now()` EMAS: u tranzaksiya
  boshlanish vaqti va uzoq apply'da yoshni kam ko'rsatardi). SQLite'da jarayon soati, dalilda
  `clock_source: "process"` deb belgilanadi. Chegara **24 soat**; kelajakka **NOL tolerantlik** —
  kesim hozirgi vaqtdan keyin bo'lolmaydi, soat to'g'rilanib bundle qayta chiqariladi.
  ⚠️ **24 soat — faqat TEXNIK chegara; u savdo bo'lmaganini isbotlamaydi.** Buni faqat
  hujjatlashtirilgan operatsion tasdiq ko'rsatadi (yopilgan smenalar, bo'sh «Активные пользователи»,
  uchta nazorat hisoboti). Eskirganlik halqasi faqat OLDIN qo'llangan job'lar bilan
  solishtiradi va birinchi apply'da — ya'ni **cutover'da** — bo'sh bo'ladi; bu darvoza aynan
  shuni yopadi. ⚠️ **VOZ KECHISH YO'Q — darvoza MUTLAQ.** Mapping'dagi `freshness_override` bloki
  rad etiladi: CLI'da identity umuman yo'q (`apply` `actor_id`siz chaqiriladi, `job.created_by`
  NULL), ya'ni `approved_by` faylni yozgan odamning o'zi tergan matn va hech narsani isbotlamaydi.
  **Yagona yo'l — yangi muzlatish va yangi nusxa.** Dalil har yurishda
  `import_jobs.column_mapping.freshness` ga yoziladi (`age_seconds`, `clock_source`, `verdict`).
  ⚠️ Bu darvoza E'LON QILINGAN yoshni o'lchaydi — rostlikni emas.
- **Nusxa provenansi (`source_copy`).** Bundle qaysi nusxa artefaktidan chiqarilganini
  hujjatlaydi. Server `.dt`/`1Cv8.1CD` faylini ko'rmaydi, ya'ni `sha256` va `byte_size` — DA'VO;
  ularni odam administratorning yozma qaydi bilan solishtiradi (`dry-run` chiqishida chop etiladi).
- `dry-run` sessiyasi DB darajasida read-only: Postgres `default_transaction_read_only=on` + `REPEATABLE READ, READ ONLY`,
  SQLite fayl `mode=ro` URI + `query_only`. Isbot = ijobiy dalil (`transaction_read_only=on` / `query_only=1`;
  izolyatsiya darajasi hisobotga QAYD etiladi, lekin isbot sharti emas) VA `UPDATE … WHERE 1=0` AYNAN read-only xatosi bilan rad etilishi (PG SQLSTATE `25006`).
  Boshqa har qanday xato (qulf, jadval yo'q, huquq) isbot EMAS — quruq yurish to'xtaydi.
- `apply`: `APP_ENV` ∈ {dev, test, staging} va platforma production EMAS. Postgres'da:
  `system_identifier` production denylist'da EMAS (**Phase 5A: production apply kodda taqiqlangan**) VA
  production bo'lmagan klasterlar ALLOWLIST'ida (kodda staging `7683497876193431618`; vaqtinchalik mahalliy/CI
  klonlari — faqat `MIGRATOR_1C_ALLOWED_SYSTEM_IDENTIFIERS`), `--expect-system-identifier` MAJBURIY va ulangan
  bazaga teng, ko'rib chiqilgan hisobotdagi `database` (sysid + baza nomi) bilan AYNAN teng. Production
  qayta yaratilsa (yangi sysid) u allowlist'da bo'lmaydi — apply RAD.
- Mapping AYNAN bitta hisobotga (`report_sha256`) va eksportga (`bundle_file_sha256`) bog'langan. Noma'lum kalit,
  takror kalit, float/NaN — rad.
  ⚠️ `prepared_by` / `prepared_at` (ilgari `approved_by` / `approved_at`) — **IXTIYORIY hujjat
  metadatasi, avtorizatsiya EMAS**: hech qanday xodimga bog'lanmaydi, rol tekshirilmaydi,
  `prepared_at` vaqt sifatida parse ham qilinmaydi. Berilsa — bo'sh bo'lmagan matn bo'lishi kerak.
  Foydalanuvchi tahrirlaydigan fayl o'ziga o'zi ruxsat bera olmaydi; haqiqiy mas'uliyat yozuvi —
  cutover HUJJATIDAGI qo'l imzosi.
- Apply do'kon qatorini `FOR NO KEY UPDATE` (lock_timeout 120 s) bilan oladi, keyin do'konning BARCHA mahsulot va
  qoldiq qatorlarini (product_id, branch_id) tartibida qulflaydi, SHUNDAN KEYIN katalogni o'qib hisobotni qayta
  hisoblaydi — bir bayt farq bo'lsa `DriftError`. Vaqt belgisi qulflardan keyin olinadi.
- Takroriy apply (fayl xeshi yoki mazmun xeshi) — `AlreadyApplied`; eski/teng snapshot — `StaleSnapshotError`; yozuvsiz.
- Ikki parallel apply — faqat bittasi yozadi (qulf + `ux_import_jobs_snapshot`). Ikkinchisi birinchisi tugagach
  `AlreadyApplied` oladi; agar birinchisi do'kon qatorini 120 s dan uzoq ushlasa — `ApplyInProgress` (yozuvsiz),
  tugagach qayta urinish kerak.
- Butun apply BITTA tranzaksiya; post-tekshiruv BAZADAN o'qiydi (identitet, narx, nom, yaratilgan maydonlar,
  har (mahsulot, filial) qoldig'i, job'ning HAR harakati, barkod–mahsulot juftliklari, o'chirilganlar, partiya
  kuzatuvi) — yiqilsa hammasi qaytariladi.
- `track_lots` / `track_expiry` / `lots_activated_at` ga TEGILMAYDI; kuzatuvli mahsulot bo'lsa reja RAD, apply
  mavjud `stock_gate.assert_untracked` darvozasidan o'tadi.
- `/catalog/v2/preview`, `/commit`, `/initial-create`, `/cutover-complete` production muhitida 403 (11-qadamga qarang).

## ⚠️ ISHONCH CHEGARASI — nima isbotlanadi va nima YO'Q

Bu bo'lim ataylab qisqa va qat'iy, chunki uni noto'g'ri o'qish eng qimmat xato bo'lardi.

### `--actor-employee-id` — ATRIBUTSIYA, avtorizatsiya EMAS

| Isbotlaydi | Isbotlamaydi |
|---|---|
| Nomlangan odam **haqiqiy** (`employees.id` ga tashqi kalit) | O'sha odam **hozir shu yerda** bo'lganini |
| U **shu do'konda** ishlaydi, **faol**, **o'chirilmagan** | Uning **roziligini** |
| Unda `mahsulotlar.edit` + `ombor.edit` **ruxsati bor** | Buyruqni **aynan u** yozganini |
| Egasi **kimdan so'rashini biladi** | Hech qanday **nazorat** (containment) |

**Nega:** `migrate_1c` CLI'si hech kimni **autentifikatsiya qilmaydi**. Uni ishga tushirgan odamda
`DATABASE_URL` bor — bu istalgan xodim akkauntidan **ko'proq** kuch: u qatorlarni `psql` bilan
to'g'ridan-to'g'ri ham yoza oladi. Shu bois bu CLI bajaradigan **hech qanday tekshiruv** o'sha
odamni cheklay olmaydi. Buni «avtorizatsiya» deb atash — teatr bo'lardi.

Qoladigan qiymat haqiqiy va arzimas emas: to'rtta ustun `NULL` dan **bog'lanadigan identitetga**
aylandi, cutover audit jurnalida **ko'rinadi**, va javobgarlik izi paydo bo'ldi. Lekin bu **iz**,
**to'siq emas**.

### Production cutover erkin terilgan UUID bilan TASDIQLANMAYDI

Bugun production APPLY **umuman mumkin emas** — u kodda bloklangan: `guard.py` production
`system_identifier` ni denylist'da ushlaydi va **override yo'q**, faqat kod o'zgarishi.
Ya'ni «erkin terilgan uuid production cutover'ni tasdiqlay oladi» degan holat **hozir mavjud emas**.

⚠️ **O'sha darvoza ochilgan kunga qat'iy shart:** `--actor-employee-id` production cutover uchun
**yagona nazorat bo'lib qololmaydi**. Undan oldin tekshiriladigan tasdiqlash mexanizmi bo'lishi
SHART — server imzolagan, CLI **tekshira oladigan lekin yasay olmaydigan** grant; aynan kompaniya,
hisobot, mapping va manba kesimiga bog'langan; tasdiqlovchi **ega darajasida**, o'zgarmas yozuv
bilan. Bu mexanizm **hali yozilmagan** va egasining alohida ruxsatisiz boshlanmaydi.

### Audit izi

Cutover endi jurnalda ko'rinadi, chunki aktyor haqiqiy xodim. ⚠️ Lekin `audit_log` ning O'ZI
**o'zgarmas emas**: yozuv chaqiruvchining tranzaksiyasi ichidagi oddiy `db.add()` (rollback bilan
birga yo'qoladi), va sxemada trigger ham, RLS ham yo'q — `DATABASE_URL` ni ushlagan odam qatorni
o'chira oladi. Bu **alohida ochiq masala**.

---

## Qoldiq semantikasi

Har (mahsulot, filial) uchun, reja `inventory_before` → `stock_final`:

| Harakat | ref_type | reason | qty | balance_after | vaqt |
|---|---|---|---|---|---|
| Eski qoldiqni yopish (eski ≠ 0) | `1c_cutover` | `CUTOVER_LEGACY_CLOSE · 1C export <sha12>` | −eski | 0 | T |
| 1C ochilish qoldig'i (1C ≠ 0) | `1c_cutover` | `CUTOVER_OPENING_BALANCE · 1C export <sha12>` | 1C qoldiq | 1C qoldiq | T + 1 µs |
| 1C'da bog'lanmagan, `deactivate_and_zero` | `1c_cutover` | `CUTOVER_LEGACY_CLOSE_NOT_IN_1C · …` | −eski | 0 | T |

`Inventory.qty = 1C qoldiq` faqat shu harakatlar bilan birga, qator qulfi ostida yoziladi. Apply joriy qoldiq reja
kutgan `inventory_before` ga AYNAN teng ekanini tekshiradi (aks holda `DriftError`).
Eski demo/import harakatlari o'chirilmaydi — tarix saqlanadi, lekin ochilish qoldig'i bilan aralashmaydi.
`client_uuid = uuid5(job, "kind:mahsulot:filial")` + `ux_movements_cutover_key` — BITTA job ichida takror imkonsiz;
joblar aro takrorni fayl/mazmun xeshi va snapshot vaqti to'sadi.

## Siyosatlar (mapping `policies`) — standart qiymat YO'Q

Reja siyosatni FAQAT kerak bo'lganda talab qiladi va TANLANGAN maqsad bo'yicha qo'llaydi (qator toifasidan qat'i nazar).

| Kalit | Tanlov | Qachon kerak |
|---|---|---|
| new_products | create / skip | NEW qatorda aniq qaror yo'q |
| blocked_rows | skip | BLOCKED qatorlar |
| negative_stock | block / zero | tanlangan omborda manfiy qoldiq |
| missing_price | block / skip_row / keep_binos_price | chakana narx yo'q yoki 0 (keep_binos_price: CREATE yoki BinOS narxi ham 0 bo'lsa — o'tkazib yuboriladi) |
| unknown_unit | block / skip_row | birlik BinOS'da yo'q — LINK, REACTIVATE, CREATE HAMMASIDA |
| unit_differs | block / skip_row | tanlangan maqsad birligi farq qiladi yoki tekshirib bo'lmaydi (1C narx/qoldig'i boshqa birlikka YOZILMAYDI — avval BinOS birligini tuzatib, dry-run qaytadan) |
| invalid_barcode | skip_barcode | buzuq barkod |
| barcode_owned_by_other | skip_barcode / block | barkod (yoki GTIN egizagi) TANLANGAN maqsaddan boshqa mahsulotda (CREATE'da har qanday egasi) |
| article_collision | generate_article | 1C artikuli boshqa qatorning artikuli/kodi bilan bir xil |
| plu_collision | drop_plu / block | CREATE PLU'si band yoki takror; tiklanadigan mahsulot PLU'si band; reja ichida PLU ikki mahsulotga |
| names | keep_binos / use_1c | LINK/REACTIVATE maqsad nomi farq qiladi |
| unmapped_branch_stock | keep / close | bog'langan YOKI o'chiriladigan mahsulotning xaritalanmagan filialda eski qoldig'i bor |
| binos_missing_from_source | keep / deactivate_and_zero | qarorlardan KEYIN bog'lanmagan faol yoki qoldiqli mahsulotlar (1C'da yo'q, rad etilgan nomzodlar) |
| skipped_row_products | keep / deactivate_and_zero | o'tkazib yuborilgan qatorning mahsulotlari: operator tanlagan LINK/REACTIVATE maqsadi (keyin siyosat o'tkazgan), BLOCKED/SKIP qatorning GUID egalari (boshqa manba nomi bilan saqlangani ham) yoki yagona nomzodi (MANY_TO_ONE tufayli nishoni tozalangan yoki nomzodda boshqa identitet bo'lgani uchun LINK imkonsiz qatorda ham) — hisobotda `row_targets`. CREATE qarori berilgan qatorning nomzodi bunga KIRMAYDI (rad etilgan — `binos_missing_from_source`). EXCLUDED qator (papka, o'chirish belgisi, xizmat) GUID egasi ham `binos_missing_from_source` ga tushadi: 1C'da u sotuv tovari emas |

Yangi mahsulot artikuli rejada hisoblanadi: 1C artikuli → 1C kodi → `1C-<guid>`; BinOS'da band yoki boshqa
qatorning artikuli/kodi bo'lgan qiymat hech qachon olinmaydi. LINK arxivdagi (`is_active=false`) mahsulotni
faollashtiradi va bu `expected.activate` da ko'rinadi.
