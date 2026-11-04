# BinOS — Reliz xavfsizligi runbook'i (Phase 8)

Bu hujjat **operator uchun**. Har bandda: nima qilinadi · nima kutiladi · qachon TO'XTAYDI.
Raqamlar taxmin emas — 2026-09-28 da o'lchangan; har biri yonida qanday o'lchangani yozilgan.

Qamrov: reliz darvozasi (§2), staging avtomatik nusxasi (§3), tiklash mashqi (§4),
qaytarish — ilova va baza (§5), ochiq repo ta'siri (§6), sir almashtirish (§7).

> **Bu hujjatdagi HECH NARSA o'z-o'zidan yoqilmaydi.** §2 va §3 dagi har bir aktivatsiya
> qadami — **ega qo'li bilan**.
>
> ⚠️  **2026-09-29 dan boshlab ikki narsa O'ZGARDI** (ega qo'li bilan, bu hujjat emas):
> `p8-release-safety` **`main` ga merge qilindi** (`e60c213a`) va Railway trigger'ida
> **`checkSuites` `true` ga o'tkazildi**. Shu sanadan oldingi «o'lchangan holat»
> jadvallari (§2.1) TARIXIY. Joriy qiymatlar — **§2.6**, o'lchangan joriy holat — **§2.7**, tarixiy uzilish — **§2.8**.

---

## 1. Deploydan OLDINGI ro'yxat

| # | Tekshiruv | Buyruq | STOP sharti |
|---|---|---|---|
| 1 | `origin/main` kutilgan SHA'da | `git fetch origin && git rev-parse origin/main` | boshqa SHA → nima qo'shilganini aniqlang |
| 2 | CI shu SHA'da yashil | `gh run list --workflow ci.yml --branch main --limit 1` | `failure` → **deploy yo'q** |
| 3 | 8/8 job yashil | `gh run view <id> --json jobs` | biror job qizil → STOP |
| 4 | Oxirgi nusxa yashil va 24 soatdan yangi | `gh run list --workflow db-backup.yml --limit 1` | qizil yoki eski → avval §3 |
| 5 | Staging hozir sog'lom | `curl -s https://savdoos-staging.up.railway.app/api/v1/health/ready` | `200` + `ready` bo'lmasa → avval shuni tuzating |
| 6 | Hozirgi deployment id yozib olindi | Railway → staging → savdoos → Deployments | yozilmasa → qaytarish nishoni yo'q |
| 7 | Sxema o'zgarishi **qo'shimchami**? | diff'dagi `ALTER TABLE` / `DROP` larni ko'ring | ustun/jadval **o'chirilsa** → §5B rejasi SHART |

**7-band eng muhimi.** Qo'shimcha DDL (yangi jadval, `NULL` ustun, yangi indeks) kodni
qaytarish bilan **mos** qoladi. Ustun tipi o'zgarishi, `NOT NULL` qo'shish yoki `DROP` —
qaytarib bo'lmaydi va §5B talab qiladi.

---

## 2. CI darvozasi — staging faqat tekshirilgan koddan

### 2.0 JORIY MODEL (2026-11-04 da JONLI o'lchangan) — AVVAL SHUNI O'QING

⚠️  Bu bo'lim §2.1–2.8 ni BEKOR QILMAYDI. U faqat bitta savolga javob beradi:
    «bugun staging qaysi yo'l bilan deploy bo'ladi». Variantlar (§2.3),
    aktivatsiya rejasi (§2.4–2.5) va manifest (§2.6) o'z kuchida qoladi —
    ular HALI BAJARILMAGAN kelajak rejasi.

**FAOL YO'L — Railway'ning O'Z GitHub autodeploy'i (to'g'ridan-to'g'ri trigger).**
`staging-deploy.yml` repoda bor, lekin **O'CHIQ** (`vars.STAGING_DEPLOY_ENABLED`
o'rnatilmagan; `RAILWAY_TOKEN` repoda umuman yo'q). Ya'ni staging'ni deploy
qiladigan narsa — GitHub Actions **EMAS**, Railway'ning GitHub integratsiyasi.
Bu holat **ataylab** shunday va §2.4 ning 1-bandi bilan mos.

| Fakt | Jonli qiymat | Qanday o'lchangan |
|---|---|---|
| Trigger soni (butun loyiha) | **1 ta** | `project.deploymentTriggers` |
| Joyi | staging / `savdoos` / `main` / `github` | UCH mustaqil so'rov MOS KELDI: `project.deploymentTriggers` · `environment.deploymentTriggers` · `service.repoTriggers` |
| `checkSuites` («Wait for CI») | **`true`** | o'sha so'rovlar |
| `validCheckSuites` | `25` | o'sha so'rovlar |
| **Production trigger** | **0 ta** | `environment(1d0edbf9-652e-44ae-b4ca-ca58d6c8106f).deploymentTriggers` |
| Tarixiy dalil | `main` ga oxirgi **14 push → 14 staging deploy**, AYNAN o'sha SHA bilan (100% moslik) | `gh run list --branch main --event push` × Railway deployment tarixi |
| Staging backend hozir | `2457b98a28598614c781ab96d6fd1467a1d9e3fc` | `GET /api/v1/health/ready` → `build.commit` |

> ⚠️ **`Wait for CI` DEPLOY'NI O'CHIRMAYDI.** `checkSuites=true` faqat
> **KUTADI**: SHA'ga biriktirilgan check suite'lar yashil bo'lgach Railway
> deploy'ni **DAVOM ETTIRADI**. U «deploy qilmaslik» bayrog'i EMAS va
> deploy'ni to'smaydi — kechiktiradi. Deploy'ni haqiqatan to'xtatadigan
> yagona narsa — **trigger'ning o'zi** (§2.6A) yoki branch mosligini uzish.

#### PLAN A va PLAN B — ARALASHTIRMANG

| | **PLAN A** (standart) | **PLAN B** (ixtiyoriy) |
|---|---|---|
| Nima qiladi | `main` ga merge'dan keyin staging autodeploy'ga **ATAYLAB ruxsat** beradi | Trigger'ni **VAQTINCHA uzadi**, deploysiz merge qiladi, keyin **ALOHIDA ruxsat** bilan qaytaradi |
| Railway mutatsiyasi | **0 ta** | **2 ta** (uzish + qaytarish) |
| Qachon to'g'ri | Staging bo'sh va deploy maqbul bo'lsa | Staging boshqa ish uchun **BAND** bo'lsa (masalan jonli demo faol yurayotgan bo'lsa) |
| Mexanizm | — | §2.6A bilan ID ni hal qilib, `deploymentTriggerUpdate` da `branch` ni **mavjud bo'lmagan shoxga** (`no-autodeploy`) burish. **`deploymentTriggerDelete` EMAS** |
| Qaytarish | — | ⚠️ **NOMA'LUM XAVF**: trigger qaytarilganda joriy `main` HEAD **DARHOL deploy bo'ladimi** — o'lchanmagan va mutatsiyasiz o'lchab bo'lmaydi. Shu bois qaytarish **deploy maqbul bo'lgan paytda**, rollback nishoni yozilgan holda qilinadi |

`deploymentTriggerDelete` dan voz kechish sababi §2.6 da yozilgan: u
**qaytarib bo'lmaydigan** va aynan tiklash uchun kerak ma'lumotni yo'q qiladi.
`branch` ni burish esa trigger **ID sini saqlaydi**.

#### Qaytarish (rollback) nishonlari — 2026-11-04 da yozilgan

| Nishon | Qiymat |
|---|---|
| `savdoos` / staging AKTIV deployment | `3190bebc-0ace-418a-94b6-8f35f95981ff` (`canRollback=true`, `canRedeploy=true`) |
| Uning SHA si | `2457b98a28598614c781ab96d6fd1467a1d9e3fc` |
| Bir qadam orqada (zaxira) | `17316374-b43f-47ad-833a-e828eae5e74a` (SHA `9c463f58`, `canRedeploy=true`) |
| Tasdiq probasi | `GET /api/v1/health/ready` → `build.commit` AYNAN deploy qilingan SHA bo'lsin |
| Production (tegilmaydi) | `ee78639a-8f02-4d9e-910f-26a60e7d5d05`, `build.commit` = **`null`** (CLI deploy) |

#### Jonli demo SHA koordinatsiyasi

Staging muhitida ikki servis staging backendga bog'langan va `LIVE_EXPECTED_SHA`
pin'ini olib yuradi: **`savdoos-live-demo`** (worker) va
**`savdoos-live-watchdog`** (monitor). Staging SHA o'zgarganda worker
`guard.verify_environment` da **fail-closed** to'xtaydi va watchdog
**CRITICAL** beradi. To'liq oyna tartibi — **§2.9**.

#### TO'XTATISH (abort) shartlari — HAR QANDAY reliz oynasida

- `environment(1d0edbf9-…).deploymentTriggers` **0 dan farq qilsa** → DARHOL
  TO'XTA (production'da trigger paydo bo'lgan)
- §2.6A trigger'ni **nol** yoki **birdan ortiq** topsa
- `environmentStagedChanges.patch` **bo'sh bo'lmasa** (kimdir o'zgarish tayyorlagan)
- `environmentPendingWork` **bo'sh bo'lmasa**
- Merge'dan oldin staging `/api/v1/health/ready` **`ready` bo'lmasa**
- PR base `main` dan **siljigan** yoki `refs/pull/N/merge` daraxti tasdiqlangan
  daraxtdan **farq qilsa**
- Shu oynada **boshqa sessiya** deploy qilgan bo'lsa

### 2.1 Bugungi holat (o'lchangan)

| Fakt | Qiymat | Qanday o'lchangan |
|---|---|---|
| Railway trigger'lari | butun loyihada **1 ta** | GraphQL `project.deploymentTriggers` |
| U qayerda | staging / savdoos / `main` / github | o'sha so'rov |
| `checkSuites` | **`false`** *(2026-09-28 holati; 09-29 da `true` ga o'zgartirilgan; **2026-11-04 da JONLI qiymat `true`** — §2.0)* | o'sha so'rov |
| Trigger `id` BARQARORMI | **YO'Q** — 2026-09-29 da `b46dc634…`, 2026-11-04 da `a134211e…` (trigger qayta yaratilgan). Har amaldan oldin **§2.6A** bilan hal qiling | `project.deploymentTriggers` ikki o'lchov |
| Production trigger'lari | **0 ta** | o'sha so'rov |
| `main` ga tushgan QIZIL CI run | **40 ta** (2026-08-26…09-13), eng uzun ketma-ketlik **20 ta** (`75d48cd`→`68f73ae`) | `gh api --paginate .../actions/runs?branch=main` |
| CI davomiyligi | min 9.0 · median 23.4 · max 30.1 daqiqa | oxirgi 16 muvaffaqiyatli run |
| GitHub branch himoyasi | **yo'q** (`404 Branch not protected`) | `gh api .../branches/main/protection` |
| Ruleset | **yo'q** (`[]`) | `gh api .../rulesets` |

**O'sha paytda `main` ga push — CI kutilmasdan darhol staging deploy'ini boshlardi**, va bu
nazariy emas: 40 marta sodir bo'lgan.

⚠️  **Bu jadval 2026-09-28 holati.** 09-29 da `checkSuites` `true` qilingach xulq o'zgardi —
va bir muddat staging umuman deploy bo'lmay qoldi (TARIXIY — §2.8). Joriy, uchidan-uchiga
isbotlangan holat — §2.7.

### 2.2 Nega Railway'ning "Wait for CI" bayrog'i YOLG'IZ yetarli emas

`checkSuites=true` commit SHA'siga biriktirilgan **har bir GitHub Actions check suite**'ini
kutadi. Bu repoda esa bitta SHA'ga ko'p suite tushadi (`gh api .../commits/<sha>/check-suites`):

| SHA | Jami suite | `github-actions` | Begona ilova (`queued`, 0 run) |
|---|---|---|---|
| `d916b9b` | 8 | 3 | 5 — netlify, zeet-co, vercel, render, railway-app |
| `25a55fb` | 12 | 7 | o'sha 5 ta |

Begona ilovalarni Railway hujjati bo'yicha **e'tiborsiz** qoldiradi. Lekin `github-actions`
suite'lari orasida CI'dan tashqari **`Uptime`** (har 15 daqiqa), **`DB Backup`** (har tun) va
**`Restore Rehearsal`** (har hafta) ham bor — jadvalli workflow'lar default branch HEAD'iga,
ya'ni aynan deploy qilinayotgan SHA'ga bog'lanadi.

**Oqibat:** production'ning health blip'i yoki tungi backup'ning yiqilishi **staging
deploy'ini to'xtatadi**. Yo'nalish xavfsiz (deploy bo'lmaydi, yomon kod ketmaydi), lekin
bog'lanish noto'g'ri va sababi operatorga ko'rinmaydi.

> Railway'ning kutish semantikasi hujjatda tasdiqlangan (docs.railway.com/deployments/github-autodeploys):
> har bir workflow **run xulosasi** baholanadi, boshqa ilovalar e'tiborsiz, `skipped`/`neutral`
> to'smaydi, 2 soatdan keyin deploy **o'tkazib yuboriladi**. Bu bandlar hujjatdan olindi,
> jonli sinovdan EMAS — yoqishdan oldin shuni bilib turing.

### 2.3 Variantlar

| Variant | Qizil CI staging'ga yetadimi | `main` ga to'g'ridan-to'g'ri push | Kamchiligi |
|---|---|---|---|
| (a) `checkSuites=true` | **Yo'q** | ruxsat | Uptime/backup yiqilsa deploy ham to'xtaydi |
| (b) GitHub ruleset (PR + status check) | PR yo'li bilan yo'q | **Bloklanadi** | loyihaning "push qil" oqimini buzadi; merge yangi SHA yaratadi va u **hech qachon build qilinmagan** bo'ladi |
| (c) (a) + (b) | Yo'q | bloklanadi | ikkalasining kamchiligi |
| (d) **CI'dan keyin Actions deploy qiladi** | **Yo'q** | ruxsat | `RAILWAY_TOKEN` siri kerak |

**Tavsiya: (d), (a) — vaqtinchalik chora sifatida.**

Sabab: (d) faqat `CI` ning xulosasiga qaraydi, ya'ni Uptime/backup shovqiniga bog'liq emas,
va **aynan CI sinagan SHA**ni deploy qiladi. (b) ni yolg'iz ishlatib bo'lmaydi: merge/squash
`main` ga **yangi SHA** tushiradi va Railway aynan o'shani deploy qiladi — holbuki status
check'lar PR HEAD'ida baholangan.

Repoda tayyor: **`.github/workflows/staging-deploy.yml`** — `on: workflow_run` (`CI`,
`main`), `if: vars.STAGING_DEPLOY_ENABLED == 'true' && conclusion == 'success'`, ishni
Railway'ning **o'z** `serviceInstanceDeployV2` mutatsiyasi bajaradi. Qo'lda chaqiruv yo'li
ham CI yashilligini **aniq** tekshiradi (darvozada teshik qolmasin).

### 2.4 Aktivatsiya rejasi (EGA qo'li bilan, shu tartibda)

1. ~~**Darhol, 1 daqiqa — vaqtinchalik chora.**~~ **BAJARILGAN (2026-09-29).**
   Railway → savdoos → Settings → staging → *Wait for CI* = ON.
   ⚠️  Bu chora eng katta teshikni yopdi. Bir muddat undan keyin staging umuman deploy
   bo'lmadi (TARIXIY — §2.8), lekin 2026-09-30 probe'i zanjir uchidan-uchiga ishlashini
   isbotladi (§2.7). Ya'ni `checkSuites=true` ning O'ZI sabab emas edi.
   GraphQL varianti — ⚠️ **ID ni QATTIQ KODLAMANG**: u trigger qayta
   yaratilganda O'ZGARADI (o'lchangan: 2026-09-29 `b46dc634…` → 2026-11-04
   `a134211e…`). Avval **§2.6A** bilan `$TRIG` ni DINAMIK hal qiling, so'ng:
   `deploymentTriggerUpdate(id:"$TRIG", input:{branch:"main", repository:"ZafarbekOlimboyev/savdoos", checkSuites:true, rootDirectory:"/apps/server"})`.
   ⚠️  **TO'RT maydon ham ATAYLAB beriladi** (sxemada aynan shu to'rtta bor):
   tushirib qoldirilgani `null` qilinadimi yoki tegilmaydimi — hujjatlanmagan.
   ⚠️ `DeploymentTriggerUpdateInput` ning to'rt maydoni ham **ixtiyoriy skalyar** — tushirib
   qoldirilgani `null` qilinadimi yoki tegilmaydimi **noma'lum**. Shuning uchun **UI
   toggle'ini afzal ko'ring**, GraphQL ishlatsangiz `branch` va `repository` ni ham
   hozirgi qiymatlari bilan bering.
2. **Kuzating (1 hafta).** Deploy qancha marta Uptime/backup tufayli to'xtadi? Nol bo'lsa —
   (a) yetarli, (d) shart emas.
3. **(d) ga o'tish** (ixtiyoriy, agar 2-bandda shovqin bo'lsa):
   **Tartib bu yerda TAKRORLANMAYDI.** Yagona normativ ketma-ketlik — **§2.5 jadvali**.
   O'sha jadvaldan chetga chiqmang.

   ⚠️  Ilgari bu yerda boshqa tartib yozilgan edi: avval `STAGING_DEPLOY_ENABLED=true`,
   keyin «**va o'sha payt**» Railway trigger'ini o'chirish. Bu XATO edi ikki sababga ko'ra.
   Birinchidan, u §2.5 bilan ZID. Ikkinchidan, «o'sha payt» — ikkita alohida boshqaruv
   paneli (GitHub va Railway) uchun bajarib bo'lmaydigan kafolat: orada qancha vaqt
   o'tsa, shuncha vaqt IKKI deployer bir vaqtda faol bo'ladi.
4. **Begona GitHub App'larni olib tashlang** (netlify, zeet-co, vercel, render, railway-app) —
   ular doimiy `queued` suite qoldiradi va check-suite maydonini ifloslaydi.
5. **Ruleset — alohida qaror.** PR talab qilish loyihaning `CLAUDE.md` dagi "push qil"
   oqimini buzadi. Bu jarayon qarori, xavfsizlik shoshilinchligi emas.

### 2.5 `staging-deploy.yml` — aktivatsiya ro'yxati

Workflow repoda bor, lekin **o'chiq**: `vars.STAGING_DEPLOY_ENABLED != 'true'` bo'lsa job
umuman bajarilmaydi.

> ### ⚠️ Yagona xavfsiz tartib
> **1) Avval ESKI yo'l o'chiriladi → 2) o'chgani TEKSHIRILADI → 3) keyin YANGI yo'l yoqiladi.**
>
> Ya'ni Railway trigger'ini o'chirish (4-qadam) `STAGING_DEPLOY_ENABLED` dan (6-qadam)
> **OLDIN** bo'ladi. Teskarisi — **6-qadamni 4-dan oldin qilish** — ikki deploy yo'lini bir
> vaqtda ochiq qoldiradi: Railway push bo'yicha, workflow esa CI'dan keyin deploy qiladi va
> ular poyga qiladi.
>
> Oraliq holat (ikkalasi ham o'chiq) **XAVFSIZ**: staging vaqtincha yangilanmaydi, xolos.
> Teskari oraliq holat (ikkalasi ham yoqiq) **XAVFLI**. Shubha bo'lsa — hech qachon
> ikkalasini bir vaqtda yoqiq qoldirmang.

⚠️  Ilgari shu yerda yo'nalish TESKARI yozilgan edi («3-qadamni 4-dan oldin qilish ikki
deploy yo'lini ochiq qoldiradi»), holbuki jadvalda 3-qadam aynan trigger'ni o'chirish edi —
ya'ni matnga ishongan operator qadamlarni almashtirib, aynan oldini olmoqchi bo'lgan
holatni yaratardi.

| # | Qadam | Tekshiruv (o'tmasa TO'XTA) | Qaytarish |
|---|---|---|---|
| 0 | Bu branch merge qilingan bo'lsin | `git log origin/main --oneline -1` yangi SHA'ni ko'rsatsin | merge'ni revert |
| 1 | **Offline salbiy sinov:** `pytest apps/server/tests/test_staging_deploy_gate.py` | Hammasi yashil. Bu darvoza mantig'ini HAQIQATAN bajaradi (qizil/bekor/tugamagan/yo'q CI, `ci-proof` SHA, eskirgan SHA) — hech narsa yoqilmasdan | — |
| 2 | **Sirni MUHITGA bog'lang.** Settings → Environments → `staging` yarating → *Deployment branches*: **Selected branches → `main`**. Railway tokenini yarating (iloji bo'lsa **project-scoped**, account-scoped EMAS) va uni **`staging` muhitining** sirlariga `RAILWAY_TOKEN` nomi bilan qo'ying. Repo darajasidagi `RAILWAY_TOKEN` bo'lmasin | **Uchalasi ham:** ① `gh api repos/ZafarbekOlimboyev/savdoos/environments/staging --jq '.deployment_branch_policy'` → `custom_branch_policies: true` · ② `gh api repos/ZafarbekOlimboyev/savdoos/environments/staging/deployment-branch-policies --jq '[.branch_policies[].name]'` → **aynan `["main"]`** · ③ `gh secret list` da `RAILWAY_TOKEN` **KO'RINMASIN** (repo darajasida qolsa muhit chegarasi hech narsa bermaydi). Biror biri o'tmasa — **TO'XTANG** | secret'ni va muhitni o'chiring |
| 3 | **Quruq yurish:** `gh workflow run staging-deploy.yml -f commit_sha=<main SHA>` — hali `STAGING_DEPLOY_ENABLED` yo'q | Run **o'tkazib yuborilgan** (skipped) bo'lsin. Bajarilsa — darvoza sharti buzilgan, TO'XTANG | — |
| 4 | **ESKI YO'LNI O'CHIRISH.** Avval manifestni §2.6 bo'yicha SAQLANG **va `$TRIG` ni §2.6A bilan DINAMIK hal qiling**, so'ng: `deploymentTriggerDelete(id:"$TRIG")`. ⚠️ **QATTIQ KODLANGAN UUID ISHLATMANG** — eskirgan ID bilan amal jonli trigger'ni **O'CHIRMAYDI** va «eski yo'l o'chdi» degan YOLG'ON xulosaga olib keladi (5-qadam buni ushlaydi, lekin ID har safar qayta hal qilinishi SHART). ⚠️ **BUZMAYDIGAN MUQOBIL (afzal, §2.0 PLAN B):** `delete` o'rniga `branch` ni `no-autodeploy` ga burish — trigger ID saqlanadi va qaytarish `branch:"main"` bilan bo'ladi | `project.deploymentTriggers` **bo'sh** (yoki `branch != main`) qaytsin | §2.6 dagi tiklash tartibi |
| 5 | **O'chgani TASDIQLANSIN — ikki dalil bilan.** (a) 4-qadamdagi `deploymentTriggers` **bo'sh** qaytsin (ASOSIY dalil); (b) qo'shimcha: `main` ga bo'sh commit push qiling va CI tugagach yana 10 daqiqa kuting | (a) bo'sh ro'yxat. (b) yangi deployment paydo bo'lmasin. ⚠️ (b) YOLG'IZ yetarli EMAS: yetkazib berish uzilganda «deployment yo'q» trigger o'chganini ISBOTLAMAYDI — 2026-09-29 da aynan shunday YOLG'ON xulosa chiqardi (§2.8). Shu bois (a) ASOSIY dalil | — |
| 6 | **YANGI YO'LNI YOQISH.** Variable qo'ying: `STAGING_DEPLOY_ENABLED=true` | `gh variable list` da ko'rinsin | variable'ni `false` qiling — darvoza darhol yopiladi |
| 7 | **Jonli sinov:** `main` ga kichik o'zgarish push qiling | ① CI yashil → ② `Staging Deploy` ishga tushsin → ③ `curl .../api/v1/health` da `build.commit` yangi SHA bo'lsin → ④ `/health/ready` 200, 8/8 `true` | 6-qadamdagi variable'ni `false`, so'ng `deploymentRollback` bilan oldingi deployment'ga qayting |
| 8 | **Jonli salbiy sinov (majburiy):** CI'ni ataylab qizil qiladigan commit push qiling | `Staging Deploy` **ishga tushmasin**; staging `build.commit` **o'zgarmasin** | commit'ni revert qiling |

> ### Nega 2-qadam shu qadar muhim
> `workflow_dispatch` workflow **ta'rifini chaqiruvchi ko'rsatgan ref'dan** oladi
> (`gh workflow run ... --ref <ref>`). Ya'ni `staging-deploy.yml` ichidagi hamma
> tekshiruv — freshness ham, CI-yashillik ham — **chaqiruvchi tanlagan nusxadan** ishlaydi.
> Repoda tuzatilmagan eski nusxali ref'lar bor va yangisini yaratish ham oson.
> **Darvozani fayl ichidan himoya qilib bo'lmaydi.**
>
> GitHub Environment esa faylning tashqarisida turadi: *deployment branch policy* `main` ga
> cheklansa, boshqa ref'dan dispatch qilingan run `RAILWAY_TOKEN` ni **umuman olmaydi** va
> workflow'dagi `[ -n "$RAILWAY_TOKEN" ]` tekshiruvida fail-closed yiqiladi.
>
> Shu bois `environment: staging` workflow'da **bor**, lekin muhitning branch siyosatini
> faqat EGA qo'ya oladi. Siyosatsiz muhit — himoya EMAS.

> ### QOLDIQ XAVF — darvoza nimani ISBOTLAMAYDI
> Bu darvoza «**CI yashil bo'lgan**» ni isbotlaydi. U «**kod ko'rib chiqilgan**» ni
> isbotlamaydi. `main` da branch himoyasi ham, ruleset ham **yo'q** (§2.1), `ci.yml` esa
> CI baholaydigan commit'ning O'ZIDA yotadi — ya'ni `ci.yml` ni bo'shashtirgan to'g'ridan-
> to'g'ri push `main` da yashil `CI` run beradi va darvozaning hamma shartini qanoatlantiradi.
>
> Demak `STAGING_DEPLOY_ENABLED=true` «push qila oladigan har kim» ni «deploy qila oladigan
> har kim» ga aylantiradi. Buni kamaytirmoqchi bo'lsangiz, `main` uchun ruleset (PR talabi +
> majburiy status check) aktivatsiyadan OLDIN qo'yilsin. §2.4 ning 5-bandi buni «alohida
> qaror» deb qoldirgan — shu qaror endi shu yerda, ongli ravishda qabul qilinsin.

> ### Qo'lda ESKI SHA ni chiqarish — endi RAD etiladi
> Ilgari `workflow_dispatch` istalgan SHA'ni qabul qilardi (va aynan shu B4 teshigi edi).
> Endi nishon AYNAN `main` tepasi bo'lishi shart. Eskiroq holatga qaytish uchun —
> **§5.2 (ILOVANI qaytarish)**, Railway'ning o'z `deploymentRollback` mexanizmi.

⚠️ **8-qadamni o'tkazib yubormang.** Butun ishning maqsadi — qizil CI staging'ga
yetmasligi. Buni **isbotlamasdan** darvoza ishlayapti deb hisoblash mumkin emas.

**Darvoza haqida bilib turish kerak bo'lgan xususiyatlar** (testlar bilan qadab qo'yilgan,
`apps/server/tests/test_staging_deploy_gate.py`):
- Qo'lda chaqiruv (`workflow_dispatch`) darvozani **chetlab o'tmaydi**: u ham shu SHA uchun
  `CI` run'larini so'rab, hammasi `success` ekanini talab qiladi.
- Shu SHA uchun **birorta** `CI` run topilmasa — deploy **rad etiladi** (jim o'tmaydi).
- SHA **butunlay** o'n oltilik va aynan 40 belgi bo'lishi tekshiriladi.
- `RAILWAY_TOKEN` buyruq satriga chiqmaydi (`-d @payload.json`), `set -x` yo'q.

---

---

### 2.6 Railway trigger MANIFESTI va uni TIKLASH

⚠️  `deploymentTriggerDelete` **qaytarib bo'lmaydigan** amal va u aynan tiklash uchun kerak
bo'ladigan ma'lumotni yo'q qiladi. Shu bois §2.5 ning 4-qadamidan **OLDIN** manifestni
o'qib, shu yerga (yoki ega yozuviga) ko'chirib qo'ying.

**O'qish (faqat-o'qish, sir chop etilmaydi — CLI o'z avtorizatsiyasini ishlatadi):**

```bash
railway api 'query($id: String!) { project(id: $id) { deploymentTriggers { edges { node {
  id branch checkSuites repository provider environmentId serviceId } } } } }' \
  --var id=32171ad7-cd7a-4eb8-8080-4806250fd1b8
```

#### 2.6A Trigger ID ni DINAMIK hal qilish — MAJBURIY, FAIL-CLOSED

⚠️  **Bu runbook'dagi birorta trigger buyrug'ida qattiq kodlangan UUID
    ishlatilmaydi.** Sabab o'lchangan: ID 2026-09-29 dan 2026-11-04 ga
    qadar `b46dc634…` dan `a134211e…` ga o'zgargan (trigger qayta
    yaratilgan). Eskirgan ID bilan `delete`/`update` **jim no-op** bo'ladi.

```bash
#  Doimiylar (bular BARQAROR — loyiha/muhit/servis identifikatorlari).
PROJ=32171ad7-cd7a-4eb8-8080-4806250fd1b8   # trustworthy-enchantment
STG=7eb2e84f-3c17-4dbb-b343-2b7a6df783fe    # staging
PRD=1d0edbf9-652e-44ae-b4ca-ca58d6c8106f    # production — HAR DOIM 0 trigger
SVC=4c0164e3-d24f-477d-a3c1-0a4c9283e218    # savdoos
REPO=ZafarbekOlimboyev/savdoos

#  ANIQ MOSLIK: loyiha + muhit + servis + repo + branch — beshtasi ham.
TRIG=$(railway api 'query($e: String!) { environment(id: $e) { deploymentTriggers {
  edges { node { id repository branch serviceId } } } } }' --var e=$STG \
 | jq -r --arg s "$SVC" --arg r "$REPO" '
    .data.environment.deploymentTriggers.edges[].node
    | select(.serviceId == $s and .branch == "main" and .repository == $r)
    | .id')

#  FAIL-CLOSED: nol yoki birdan ortiq bo'lsa — HECH NARSA qilinmaydi.
N=$(printf '%s\n' "$TRIG" | grep -c . || true)
[ "$N" = "1" ] || { echo "RAD: trigger soni=$N (1 bo'lishi SHART) — TO'XTA"; exit 1; }
echo "TRIG=$TRIG"

#  PRODUCTION HIMOYASI — bu tekshiruv TUSHIRIB QOLDIRILMAYDI.
NP=$(railway api 'query($e: String!) { environment(id: $e) { deploymentTriggers {
  edges { node { id } } } } }' --var e=$PRD \
 | jq '.data.environment.deploymentTriggers.edges | length')
[ "$NP" = "0" ] || { echo "RAD: production'da $NP trigger — DARHOL TO'XTA"; exit 1; }
```

**UCH MUSTAQIL KESISHTIRISH** (hammasi bir xil natija berishi SHART —
2026-11-04 da shunday bo'lgan):

1. `project(id:$PROJ).deploymentTriggers`
2. `environment(id:$STG).deploymentTriggers`
3. `service(id:$SVC).repoTriggers`

**2026-11-04 da o'qilgan JONLI holat (manifest nusxasi):**

| Maydon | Qiymat |
|---|---|
| `id` | `a134211e-4b3b-4320-9145-39f2898681ab` — ⚠️ **BARQAROR EMAS**, §2.6A bilan hal qiling |
| `validCheckSuites` | `25` |
| `provider` | `github` |
| `repository` | `ZafarbekOlimboyev/savdoos` |
| `branch` | `main` |
| `checkSuites` | `true` |
| `environmentId` | `7eb2e84f-3c17-4dbb-b343-2b7a6df783fe` (**staging**) |
| `serviceId` | `4c0164e3-d24f-477d-a3c1-0a4c9283e218` (`savdoos`) |
| `rootDirectory` | **`/apps/server`** — ⚠️ `DeploymentTrigger` dan **o'qilmaydi** (faqat `...CreateInput` da bor); qiymat `ServiceInstance.rootDirectory` dan olingan |

Loyiha: `trustworthy-enchantment` = `32171ad7-cd7a-4eb8-8080-4806250fd1b8`.
Production environment `1d0edbf9-652e-44ae-b4ca-ca58d6c8106f` — **bu yerda ishtirok etmaydi**
va hech qachon trigger nishoni bo'lmasligi kerak.

**Tiklash** (eski yo'lni qaytarish kerak bo'lsa — masalan yangi darvoza ishlamay qolsa):

```bash
railway api 'mutation($in: DeploymentTriggerCreateInput!) { deploymentTriggerCreate(input: $in) { id } }' \
  --variables '{"in":{"provider":"github","repository":"ZafarbekOlimboyev/savdoos",
                "branch":"main","checkSuites":true,
                "rootDirectory":"/apps/server",
                "environmentId":"7eb2e84f-3c17-4dbb-b343-2b7a6df783fe",
                "serviceId":"4c0164e3-d24f-477d-a3c1-0a4c9283e218",
                "projectId":"32171ad7-cd7a-4eb8-8080-4806250fd1b8"}}'
```

⚠️  **`rootDirectory` ni TUSHIRIB QOLDIRMANG.** U ixtiyoriy maydon, lekin usiz qayta
yaratilgan trigger repo ILDIZIDAN qurishga urinadi: `apps/server/railway.json` va
`apps/server/Dockerfile` topilmaydi. Ya'ni «tiklandi» ko'rinib, birinchi deploy'da
buziladi. Qiymatni trigger'dan o'qib bo'lmaydi — u faqat `ServiceInstance` da:

```bash
railway api 'query($s: String!, $e: String!) { serviceInstance(serviceId: $s, environmentId: $e) { rootDirectory watchPatterns } }' \
  --var s=4c0164e3-d24f-477d-a3c1-0a4c9283e218 --var e=7eb2e84f-3c17-4dbb-b343-2b7a6df783fe
```

**Sxema TASDIQLANGAN (2026-09-29, `railway api describe DeploymentTriggerCreateInput`):**
majburiy maydonlar — `branch`, `environmentId`, `projectId`, `provider`, `repository`,
`serviceId`; ixtiyoriylar — `checkSuites`, `rootDirectory`. Yuqoridagi mutatsiya shu
ro'yxatga to'liq mos.

⚠️  **`rootDirectory` ni o'qib bo'lmaydi:** u `DeploymentTriggerCreateInput` da bor, lekin
`DeploymentTrigger` tipida YO'Q (`Cannot query field "rootDirectory"`), ya'ni hozirgi
qiymatini manifestga olish imkoni yo'q. Servis instansiyasining `rootDirectory` si
`/apps/server` (o'qilgan). O'chirishdan oldin Railway UI'da trigger sozlamasini ham
suratga oling — API bermaydigan yagona maydon shu.

Yangi trigger **boshqa `id`** oladi. ⚠️ Uni runbook'ga yozib qo'yish bilan
cheklanmang: §2.5 va §2.4 dagi buyruqlar `$TRIG` ni **§2.6A bilan har safar
qaytadan hal qiladi**, ya'ni ID ning eskirishi endi xavf tug'dirmaydi.
Manifestdagi qiymat — faqat **audit nusxasi**, buyruq manbasi EMAS.

#### Qaytarish tartibi (§2.5 ning TESKARISI, shu ketma-ketlikda)

⚠️  Bu yerda ham qoida bir xil: **avval faol yo'l o'chiriladi, tasdiqlanadi, keyin
ikkinchisi yoqiladi.** Faqat yo'nalish teskari. Ilgari bu bo'lim «tiklashdan KEYIN
variable'ni `false` qiling» deb yozilgan edi — ya'ni tiklash bilan o'chirish orasida
IKKI deployer bir vaqtda faol bo'lardi.

| # | Qadam | Tekshiruv (o'tmasa TO'XTA) |
|---|---|---|
| 1 | **Yangi yo'lni O'CHIRING:** `gh variable set STAGING_DEPLOY_ENABLED --body false` | `gh variable list` da `false` ko'rinsin |
| 2 | **O'chgani TASDIQLANSIN:** Actions'da `Staging Deploy` ning yurayotgan run'i qolmasin | Oxirgi run **skipped** yoki tugagan bo'lsin |
| 3 | **Eski yo'lni TIKLANG:** yuqoridagi `deploymentTriggerCreate` (`rootDirectory` bilan) | Mutatsiya `id` qaytarsin |
| 4 | **Tiklangani ISHLASHINI tasdiqlang:** `main` ga kichik o'zgarish push qiling | Railway'da yangi deployment paydo bo'lsin **va** `SUCCESS` ga yetsin **va** `/api/v1/health` dagi `build.commit` yangi SHA'ga o'tsin |

⚠️  **4-qadam majburiy.** `rootDirectory` ni trigger'dan o'qib bo'lmaydi, ya'ni uni
noto'g'ri tiklash faqat BIRINCHI deploy'da bilinadi: Railway Dockerfile'ni repo
ildizidan qidiradi va build yiqiladi. «Mutatsiya `id` qaytardi» — tiklandi degani EMAS.

### 2.7 Staging yetkazib berish — O'LCHANGAN holat

> **Joriy holat (2026-09-30): staging yetkazib berish ISHLAYDI va uchidan-uchiga
> isbotlangan.** Quyida shu o'lchov. Undan oldingi uzilish — TARIXIY, §2.8 da.

**Probe:** `main` ga bo'sh commit (ega ruxsati bilan, faqat shu maqsadda):
`09a2eacb45f9936f96f3e4527d40579d4b78a635` — parent `e60c213a`, tree AYNAN bir xil,
GitHub API bo'yicha **0 fayl, +0/−0**.

| Vaqt (UTC) | Hodisa |
|---|---|
| `17:20:23` | `main` ga push |
| **`17:20:57`** | Railway deployment yaratdi — **`WAITING`** |
| `17:20:58 → 17:46:20` | CI run **`36750736390`** — **8/8 success** |
| `17:46:59` | `WAITING` → **`DEPLOYING`** |
| **`17:47:47`** | **`SUCCESS`** |

Tasdiq: `savdoos-staging.up.railway.app/api/v1/health` → `build.commit = 09a2eacb…`.

**Bu nimani isbotlaydi:**
- GitHub webhook yetkazib berish **ishlaydi**;
- Railway'ning **o'z (native) trigger'i ishlaydi**;
- **`checkSuites=true` uchidan-uchiga ishlaydi** — deploy CI yashil bo'lgunicha
  `WAITING` da turdi va faqat shundan keyin boshlandi (~26 daqiqa);
- deploy'ni **Railway'ning o'z trigger'i** qildi, GitHub'dagi `Staging Deploy (CI-gated)`
  workflow'i **emas** — u o'sha SHA uchun ham **`skipped`** bo'ldi, chunki
  `STAGING_DEPLOY_ENABLED` hamon yo'q.

⚠️  **Bu yerdagi trigger sozlamasi HOZIR ISHLAYAPTI** (`main`, `checkSuites=true`,
`rootDirectory=/apps/server`). §2.5 aktivatsiyasi boshlangunicha unga TEGILMAYDI.

### 2.8 Oldingi uzilish (2026-09-29 … 09-30) — TARIXIY

2026-09-29 da `p8-release-safety` `main` ga merge qilindi (`e60c213a`), CI main'da 8/8
yashil tugadi, lekin **staging deploy bo'lmadi**. O'shanda o'lchangani:

- `e60c213a` uchun deployment yozuvi — 13 statusning HAMMASI bo'yicha **0 ta**
  (`WAITING` ham yo'q, ya'ni «kutmoqda» emas edi);
- trigger esa MAVJUD va to'g'ri sozlangan edi;
- Railway'ning GitHub'ga murojaat qiladigan **har bir** GraphQL so'rovi
  («Not Authorized») rad etilardi, ayni paytda GitHub'ga aloqasi yo'q `me { }` so'rovi
  ishlardi va hisobda GitHub bog'langan ko'rinardi.

**Rad etilgan (takrorlamang):** begona ilovalarning abadiy `queued` check suite'lari
(Railway hujjati: e'tiborsiz qoldiriladi) · ataylab `skipped` bo'ladigan
`Staging Deploy` workflow'i (hujjat: `skipped`/`neutral` **hech qachon bloklamaydi**) ·
`watchPatterns` (bo'sh) · servis uxlashi · `isUpdatable=false` (production'da ham
`false` — ajratuvchi emas).

**⚠️ ILDIZ SABAB — NOMA'LUM.** 09-30 kuni 11:54Z va 17:20Z oralig'ida holat o'zgardi
(16:06Z da `d916b9b1` uchun yangi SUCCESS deploy paydo bo'ldi, uni biz qilmadik).
Oradagi ega amallari qayd etilmagan. **Nima tuzatganini bilamiz deb da'vo qilmaymiz.**

**Amaliy saboq:** «deployment yozuvi yo'q» ≠ «Wait for CI kutmoqda». Hujjatga ko'ra
`checkSuites=true` da `WAITING` yozuvi YARATILADI (probe buni tasdiqladi). Yozuv umuman
bo'lmasa — push qayta ishlanmagan, ya'ni muammo yetkazib berishda.

**Shuning uchun §2.5 ning 5-qadami ikki dalilga tayanadi:** trigger ro'yxatining bo'shligi
(asosiy) va deployment paydo bo'lmasligi (qo'shimcha). Ikkinchisi yolg'iz ishonchsiz —
2026-09-29 da u «trigger o'chgan» degan YOLG'ON xulosa berardi.

### 2.9 Jonli demo worker — RELIZ OYNASI tartibi

> **Holati: TAYYORGARLIK.** Nazorat ostidagi to'xtatish **tasdiqlangan**
> (ega, 2026-11-04), lekin u **faqat** alohida ruxsat etilgan merge/deploy
> ketma-ketligining ichida, quyidagi shartlar bajarilgandan keyin bajariladi.
> Hujjat/CI fazasida worker **TO'XTATILMAYDI**.

#### 2.9.1 Nega kerak (o'lchangan)

Staging muhitidagi ikki servis staging backendga bog'langan:

| Servis | Roli | `LIVE_EXPECTED_SHA` | Holati (2026-11-04 12:40Z) |
|---|---|---|---|
| `savdoos-live-demo` | worker | `2457b98a…` | **TIRIK**, `standby`, raund 1738, `armed=False` |
| `savdoos-live-watchdog` | monitor | `2457b98a…` | **TIRIK**, `worst=INFO`, `deadman=yetdi` |

⚠️  **`LIVE_RUN_UNTIL` tugagani «to'xtagan» DEGANI EMAS.** Muddat
    2026-10-29T08:00:00Z da o'tgan (`seconds_left=-535011`), lekin jarayon
    chiqmagan — u **STANDBY** halqasida har ~5 daqiqada gardni qayta
    bajaradi va staging backendga so'rov yuboradi.

Staging `dedd16e6` ga deploy bo'lsa, ~5 daqiqa ichida:

1. **Worker:** `guard.verify_environment` → `SHA_CHANGED` → `SafetyViolation`
   (standby halqasi uni ushlamaydi) → jarayon chiqadi →
   `restartPolicyType=ON_FAILURE (max 10)` → 10 marta ayni xato → CRASHED.
2. **Watchdog:** `SERVER_SHA_CHANGED` **CRITICAL** → **Telegram xabari**.
3. `enforce_stop` — **dry-run standart** va masofaviy PID da signalni
   **RAD etadi** → watchdog worker'ni o'zi o'ldirmaydi.
4. **Dead-man** (`hc-ping.com`) — watchdog tirik qolgani uchun ping
   **uzilmaydi**.
5. **Ma'lumot xavfi YO'Q** — `armed=False` va gard fail-closed: worker
   yoza olmaydi.

Ya'ni SHA pin — **himoya**, mo'rt bog'liqlik emas. Nazorat ostida to'xtatish
faqat **shovqinni** (10 crash + bitta soxta CRITICAL) oldini oladi.

#### 2.9.2 To'xtatishdan OLDIN bajarilishi SHART (darvozalar)

| # | Darvoza | Qanday tekshiriladi | O'tmasa |
|---|---|---|---|
| G1 | Hisob-kitob **AYNI** (in-flight yozuv yo'q) | watchdog logidagi `FAKTLAR.sale_recon`: `server_ids == ledger_ids`, `reread_ok=true`, **`in_flight=false`** | **TO'XTA** — avval reconciliation tugasin |
| G2 | Ledger va server mos | `FAKTLAR.sale_ledger_vs_server`: `ledger == server_shift_receipts` | TO'XTA |
| G3 | Worker **qurollanmagan** | worker logida `armed=False` va `[standby] live.standby` | TO'XTA — qurollangan worker to'xtatilmaydi |
| G4 | Heartbeat **yangi** (osilib qolmagan) | `FAKTLAR.heartbeat_age_seconds` kichik (o'lchangan: 84 s), `last_error=null` | Osilgan jarayonni to'xtatish boshqa tartib |
| G5 | Qulf holati ANIQ | `FAKTLAR.lock.state = LOCK_HELD_ACTIVE`, `read="read"` | `unreadable` bo'lsa TO'XTA |
| G6 | Checkpoint faktlari YOZILGAN | `FAKTLAR.checkpoint`: `epoch_id`, `last_tick_id`, `business_date`, `current_shift_id` ega yozuviga ko'chirilgan | TO'XTA — tiklash nishoni yo'q |
| G7 | Manfiy qoldiq yo'q | `FAKTLAR.negative_stock = 0` | TO'XTA |

**2026-11-04 12:36:54Z da o'lchangan qiymatlar (nusxa):**

```
checkpoint   epoch_id=77714cb4-1990-4bcf-94a0-2d9285cb3580  last_tick_id=176
             business_date=2026-10-29  current_shift_id=6539215d-81ab-4a4f-8e7e-2d9d3fa948ba
deadline     run_until=2026-10-29T08:00:00+00:00  passed=true  worker_status=standby
heartbeat    status=standby  stop_reason=null  last_error=null   (age 84 s)
lock         present=true  state=LOCK_HELD_ACTIVE  worker_id=w-50c10e71e483  pid=1
runtime_sha  2457b98a28598614c781ab96d6fd1467a1d9e3fc
sale_recon   server_ids=54  ledger_ids=54  reread_ok=true  in_flight=false
shift        receipts=54  expected=16675.0  status=open
negative_stock 0
```

⚠️  **Staging demo ijarachisida OCHIQ SMENA bor** (`6539215d…`,
    `business_date=2026-10-29`). To'xtatish uni YOPMAYDI va yopmasligi
    kerak: checkpoint aynan shu smenaga bog'langan va qayta ishga
    tushganda worker `current_shift_id` bo'yicha rekonsiliatsiya qiladi.

#### 2.9.3 Checkpoint tiklanishi — DALIL va BO'SHLIQ

| Fakt | Holat |
|---|---|
| Checkpoint qayerda | `LIVE_STATE_DIR=/data/live`, Railway volume `savdoos-live-demo-volume` (instans `3d9b9d46-fc1f-41d7-8a63-63dda09ab0d9`, mount `/data`, 165.26 MB) |
| Volume to'xtatishda saqlanadimi | **HA** — volume servisga bog'langan, to'xtatish/qayta deploy uni o'chirmaydi |
| Yozuv atomikmi | **HA** — `state.write_atomic`: `tmp` + `fsync` + `os.replace`; uzilish yoki ASL, yoki TO'LIQ YANGI faylni qoldiradi |
| ⚠️ Railway volume **backup**'i | **YO'Q** — `volumeInstanceBackupList` = **0**, `volumeInstanceBackupScheduleList` = **0** |

⚠️  **BO'SHLIQ:** checkpoint'ning platforma darajasidagi nuqtaviy zaxirasi
    YO'Q. Shu bois **G6 majburiy**: to'xtatishdan oldin `FAKTLAR.checkpoint`
    qiymatlari (hech bo'lmasa `epoch_id`, `last_tick_id`, `business_date`,
    `current_shift_id`) ega yozuviga **ko'chiriladi**. Tiklanish atomik
    yozuv + volume saqlanishiga tayanadi, backupga EMAS.

#### 2.9.4 BUZMAYDIGAN to'xtatish mexanizmi

`worker.py` `install_signal_handlers()` **SIGTERM/SIGINT ni TUTIB OLADI** →
`LiveShutdown` → nazoratli to'xtash → **qulf bo'shatiladi**
(`release_lock_quietly`). Docstring'da aniq: ilgari SIGTERM jarayonni
darhol tugatardi va `try/finally` ham bajarilmasdi; endi to'xtash nazoratli.

| Usul | Baho |
|---|---|
| Railway UI → `savdoos-live-demo` → **Stop / Remove deployment** | **AFZAL** — SIGTERM yuboradi → graceful → qulf bo'shaydi → volume saqlanadi |
| `railway down --service savdoos-live-demo` | Shu ta'sir, CLI orqali |
| `SIGKILL` / volume o'chirish | **TAQIQ** — qulf osilib qoladi, checkpoint xavf ostida |

⚠️  **`savdoos-live-watchdog` TO'XTATILMAYDI.** U to'xsa dead-man pingi
    uziladi va `hc-ping.com` tashqi ogohlantirish yuboradi. Watchdog tirik
    qolib, worker yo'qligi uchun bitta CRITICAL berishi **KUTILADI va
    NORMAL** — oldindan ogohlantiring.

#### 2.9.5 Reliz oynasi — ANIQ ketma-ketlik

| Faza | Amal | Kim | Tasdiq |
|---|---|---|---|
| 0 | G1–G7 darvozalari (§2.9.2) | operator | hammasi o'tdi |
| 1 | `savdoos-live-demo` ni **Stop** (watchdog TIRIK) | **EGA** | worker logida `live.graceful_stop` yoki `signal:` sababi; qulf bo'shagan |
| 2 | **Merge** (alohida ruxsat) → staging autodeploy | **EGA** | Railway'da yangi deployment, `meta.commitHash` = yangi SHA |
| 3 | `GET /api/v1/health/ready` | kuzatuv | `ready`, 9/9, **`build.commit` = yangi SHA** |
| 4 | `LIVE_EXPECTED_SHA` = yangi SHA — **IKKI servisda** | **EGA** | Railway variables |
| 5 | `live checkpoint-migrate --apply` + `ack` = yangi SHA | **EGA** | chiqishda `expected_binos_sha: <eski> -> <yangi>`; `migrations` ro'yxatiga yozuv qo'shildi |
| 6 | `savdoos-live-demo` ni qayta ishga tushirish | **EGA** | logda `live.env_verified sha=<yangi>` → `live.scope_verified` → `live.guard_passed` → `[standby] live.standby` |
| 7 | Watchdog normallashdi | kuzatuv | `worst=INFO`, `RUN_DEADLINE_COMPLETED`, `deadman=yetdi`, `ENFORCE: action=none` |

#### 2.9.6 SHA migratsiyasining OLDINGI SHARTLARI

`live checkpoint-migrate` (`synthetic_lab/demo/live/migrate.py`) kafolatlari:

1. **Idempotent** — maqsad SHA allaqachon bo'lsa `NO_CHANGE`
2. **Crash-safe** — `tmp` + `fsync` + `os.replace`
3. **Audit izi** — `migrations` ro'yxatiga QO'SHILADI, hech narsa o'chmaydi
4. **Hamma maydon saqlanadi** — `epoch_id`, `last_tick_id`, `emitted`
   (`result_id` lar bilan), `returnable`, `run_until` bayt-bayt ko'chiriladi
5. ⚠️ **SERVER AVTORITETI** — maqsad SHA jonli `GET /health` dagi
   `build.commit` ga **TENG BO'LISHI SHART**; tasdiqlanmagan qiymatga
   bog'lab bo'lmaydi
6. **Operator tasdig'i** — `ack` **AYNAN** maqsad SHA bo'lishi kerak

> ⚠️ (5) **tartibni majburlaydi:** migratsiyani deploy'dan **OLDIN**
> bajarib bo'lmaydi, chunki server hali eski SHA ni beradi. Ya'ni
> §2.9.5 dagi 3→4→5 tartibi **majburiy**, almashtirib bo'lmaydi.

#### 2.9.7 Rollback va abort

| Vaziyat | Amal |
|---|---|
| Staging yaroqsiz | `3190bebc-0ace-418a-94b6-8f35f95981ff` ni **Redeploy** → `build.commit` yana `2457b98a…` |
| Worker qaytmasa | `LIVE_EXPECTED_SHA` ni `2457b98a…` ga qaytarish + `checkpoint-migrate` ni `ack=2457b98a…` bilan — **FAQAT staging rollback qilingandan KEYIN** (server avtoriteti) |
| G1 (`in_flight=true`) | To'xtatish **BOSHLANMAYDI** — reconciliation tugashini kuting |
| G5 (`lock.read=unreadable`) | **TO'XTA** — qulf holati noaniq, jarayon to'xtatilmaydi |
| Watchdog to'xsa | **TO'XTA** — dead-man uziladi; avval watchdog qaytarilsin |
| Checkpoint yozuvi olinmagan (G6) | **TO'XTA** — tiklash nishoni yo'q |

## 3. Staging avtomatik nusxasi

### 3.1 Nega kerak edi

Staging'da **avtomatik nusxa umuman yo'q edi**: Railway volume backup ro'yxati bo'sh,
jadval bo'sh, PITR `null`; `db-backup.yml` esa faqat `PROD_DATABASE_URL` ni oladi. Phase 6A
deploy'idan oldin nusxa **qo'lda** olingan. Qo'lda qadam ertami-kechmi tushib qoladi.

### 3.2 Tuzilma — nusxa emas, CHAQIRUV

```
_db-backup-core.yml   (workflow_call)  ← YAGONA mantiq
   ├── db-backup.yml       production  · prefiks savdoos-db          · 14/56/180
   └── staging-backup.yml  staging     · prefiks savdoos-staging-db  ·  7/30/90
```

`scripts/backup_postgres.sh`, `restore_rehearsal.sh`, `db_fingerprint` va `pg-client`
action'i **allaqachon muhitdan mustaqil** edi — ularga tegilmadi.

> Nega nusxa emas: bu repo nusxa driftidan bir marta jabr ko'rgan — `pg_client.sh` da versiya
> parseri tuzatilgan, `action.yml` dagi nusxasi esa yo'q, va birinchi haqiqiy production
> backup'i shundan yiqilgan (`major=2, expected=18`).

**`db-backup.yml` nomi va `savdoos-db` prefiksi ataylab o'zgarmadi** — `restore-rehearsal.yml`
eng yangi run'ni `actions/workflows/db-backup.yml/runs` orqali topadi va `savdoos-db-*`
naqshini qidiradi. Staging boshqa prefiks oladi, chunki mashq bitta run'da bir nechta
`savdoos-db-*` artefakt topsa ataylab yiqiladi.

### 3.3 Saqlash muddati va uning asosi

| Bosqich | Production | Staging | Staging uchun sabab |
|---|---|---|---|
| kunlik | 14 kun | **7 kun** | oxirgi bir necha relizni qoplaydi |
| haftalik | 56 kun | **30 kun** | bitta reliz siklini qoplaydi |
| oylik | 180 kun | **90 kun** | GitHub'ning **ochiq repo** uchun maksimumi |

Staging'da mijoz ma'lumoti yo'q va tenantlar qayta yaratiladi — RPO talabi yo'q. Qiymati
faqat "oxirgi relizdan oldingi holat".

> ⚠️ **Production'ning 180 kunlik bosqichi amalda ishlamaydi.** Ochiq repoda GitHub artefaktni
> 90 kundan uzoq saqlamaydi. Core workflow endi run oxirida haqiqiy `expires_at` ni o'qib
> farqni `::warning::` bilan chiqaradi. Haqiqatan 180 kun kerak bo'lsa — repo yopiq qilinsin (§6).
> O'lchangan: kunlik so'rov 14 → `expires_at` 14 kun; haftalik 56 → 56 kun (qo'llanadi).

### 3.4 Butunlik tekshiruvlari (hammasi allaqachon bor, staging'ga o'zgarishsiz tegishli)

1. Sir yo'q → **yiqiladi** (jim `exit 0` yo'q).
2. `pg_client_require_ge` — mijoz serverdan eski bo'lsa dump **boshlanmaydi**.
3. Dump bo'sh yoki `SAVDOOS_BACKUP_MIN_BYTES` dan kichik → yiqiladi.
4. `pg_restore -l` — fayl **o'qib ko'riladi** (hajm emas, tuzilma).
5. `sha256` — ochiq dump uchun; `sha256_encrypted` — shifrlangan fayl uchun (parolsiz tekshirish).
6. Barmoq izi **dumpdan oldin va keyin** → `capture_quiescent`.
7. `if-no-files-found: error` — bo'sh artefakt jimgina o'tmaydi.
8. **Yangi:** artefakt yozilgach haqiqiy `expires_at` tekshiriladi.
9. **Yangi:** shifrlash `scripts/encrypt_evidence.sh` da — YAGONA nusxa (nusxa core'i va
   mashqning ikkala job'i shuni chaqiradi). U: `gpg` yo'q bo'lsa yoki parol bo'sh bo'lsa
   **boshlamaydi**; shifrlaydi; **ochib qaytarib sha256 bilan solishtiradi**; va faqat
   shundan keyin ochiq nusxani o'chiradi. Yiqilsa ochiq nusxa **saqlanadi** (ma'lumot
   yo'qolmasin) va artefaktga baribir chiqmaydi, chunki yuklash yo'llari faqat `*.gpg`.
10. **Yangi:** parol buyruq satriga qo'yilmaydi (`--passphrase-fd 0`) — runner'ning
   jarayonlar ro'yxatida ko'rinmaydi.

> Nega tekshiruv shart: `gpg` chiqish kodi 0 bo'lsa ham fayl buzuq bo'lishi mumkin (disk
> to'lgan, oqim uzilgan). Bunda ochiq nusxa o'chib, shifrlangani OCHILMASDI — falokat
> kunidagi eng yomon holat: nusxa **bor ko'rinadi**, lekin **yo'q**.

### 3.5 Yiqilish ko'rinadimi

Bugun **faqat GitHub emaili** (jadvalli workflow yiqilsa repo egasiga ketadi). Bu zaif:
email filtrga tushishi mumkin va hech kim javobgar emas. Eng arzon yaxshilanish — mavjud
`uptime.yml` naqshidan foydalanib, backup yiqilganda ham xabar yuborish. **Bu hali
bajarilmagan** — §9 dagi ochiq bandlar ro'yxatida.

### 3.6 Yoqish uchun kerak (EGA)

| Nima | Qiymat shakli |
|---|---|
| Secret `STAGING_DATABASE_URL` | Railway → staging → Postgres-d29B → TCP proxy ulanish satri (`postgresql://...@<host>.proxy.rlwy.net:<port>/railway`) |
| `BACKUP_PASSPHRASE` | **allaqachon bor** — production bilan bir xil ishlatiladi (ikkinchi parol = ikkinchi yo'qotish xavfi) |

⚠️  **Workflow o'chiq holda keladi.** `staging-backup.yml` JADVALLI (har kecha 21:30 UTC).
Agar u sirsiz merge qilinsa, har kecha qizil bo'lardi — va bir necha kundan keyin qizil
jadval "odatiy" ko'rinib, HAQIQIY nosozlik ham e'tibordan qolardi. Shu bois job
`vars.STAGING_BACKUP_ENABLED == 'true'` bilan darvozalangan.

**Yoqish tartibi (shu ketma-ketlikda):**
1. Secret `STAGING_DATABASE_URL` qo'shiladi.
2. `gh workflow run staging-backup.yml --repo ZafarbekOlimboyev/savdoos` — qo'lda bir marta.
   Yashil bo'lsin va artefakt (`savdoos-staging-db-*`) paydo bo'lsin.
3. Variable `STAGING_BACKUP_ENABLED=true` — shundan keyin JADVAL ham ishlaydi.

⚠️  **B3 — 2-qadam ilgari BAJARIB BO'LMAYDIGAN edi.** Job sharti faqat
`vars.STAGING_BACKUP_ENABLED == 'true'` edi, ya'ni variable qo'yilmagan holda qo'lda
chaqiruv JIMGINA `skipped` bo'lardi: na artefakt, na xato. Operator «yiqilmadi» ni
«ishladi» deb o'qishi va shu asossiz tasdiq bilan 3-qadamga o'tishi mumkin edi.
Endi shart quyidagicha:

```yaml
if: >-
  vars.STAGING_BACKUP_ENABLED == 'true' ||
  github.event_name == 'workflow_dispatch'
```

ya'ni **qo'lda chaqiruv bajariladi**, **jadval esa variable qo'yilmaguncha o'chiq qoladi**.
Ikkala kafolat ham `apps/server/tests/test_backup_schedule_and_runbook.py` da tekshiriladi.

**Nima o'zgarmadi (ataylab):**
- Sir yo'q bo'lsa — **FAIL-CLOSED**: `_db-backup-core.yml` «ulanish satri secret'i
  o'rnatilmagan — BACKUP OLINMADI» deb `exit 1` qiladi. Jimgina `success` YO'Q.
- `database_url` — chaqiriladigan workflow'ning **majburiy** siri, **default yo'q**.
  Staging chaqiruvi unga AYNAN `secrets.STAGING_DATABASE_URL` ni beradi; `PROD_DATABASE_URL`
  ga **hech qanday zaxira yo'l yo'q** va bo'lishi ham mumkin emas.
- Production `db-backup.yml` darvozalanmagan va tegilmagan.

**Qaytarish:** variable'ni `false` qiling — **JADVAL** darhol to'xtaydi, sir joyida qoladi.

⚠️  Diqqat: `false` **qo'lda chaqiruvni to'xtatmaydi** (B3 dagi istisno ataylab). Ya'ni bu «kill switch» jadval uchun; repo'ga yozish huquqi bor kishi baribir qo'lda bir marta nusxa oldirishi mumkin. Butunlay to'xtatish kerak bo'lsa — `STAGING_DATABASE_URL` sirini o'chiring (u holda core fail-closed yiqiladi).

`db-backup.yml` (production) ATAYLAB darvozalanmagan: u allaqachon ishlayapti va siri bor;
unga darvoza qo'yish tungi nusxani jimgina to'xtatib qo'yish xavfini tug'dirardi.

---

## 4. Tiklash mashqi — BAJARILDI

Arxiv ro'yxati emas, **haqiqiy tiklash**. 2026-09-28 da bajarildi.

**Muhit:** bir martalik PostgreSQL **18.6** klasteri (`postgresql-binaries==18.6.0` PyPI
paketi, `C:\pg18r` ga chiqarilgan, port 55432, faqat `127.0.0.1`). Staging serveri bilan
**aynan bir xil major va minor**. Boshqa hech qanday bazaga tegilmadi.

**Nusxa:** `staging-pre-6a.dump` — Phase 6A deploy'idan oldin olingan staging nusxasi
(377 178 bayt, `-Fc`, sha256 `8c6841cd…`).

**Bajarilgan skript:** `scripts/restore_rehearsal.sh` — loyihaning **o'z** mashq skripti.

| Bosqich | Natija |
|---|---|
| checksum | `OK` |
| yetishmayotgan rollar | dump'da grant yo'q — yaratish shart emas |
| versiya gardi | `server_major=18 · pg_dump_major=18` |
| `pg_restore --exit-on-error` | **muvaffaqiyat** |
| `cash` sxemasi | mavjud |
| FOREIGN KEY | **198** |
| jadval soni | **68 / 68** |
| qator sanog'i | **44 ta nolmas jadval, hammasi mos; jami 1554 = 1554** |
| indekslar | **157 / 157**, ta'riflari aynan |
| ustunlar | **739 / 739** |
| cheklovlar | **745 / 745** — 1 tasi boshqacha **render** bo'lgan |
| boot DDL (`python -m app.initdb`) | muvaffaqiyat; `[migrate] companies.status qo'shildi` |
| `/health/ready` | **200 `ready`, 8/8 tekshiruv `true`** |

**Yagona farq va uning tahlili:** `ck_lsr_kind` cheklovi tiklangan bazada boshqacha
yoziladi (`ANY (ARRAY[('real')::text, ...])` vs `ANY ((ARRAY['real'])::text[])`). Bu —
dump/restore aylanishining katalog **render** artefakti, ma'no bir xil. Loyihaning **o'z**
struktura solishtiruvchisi bilan tasdiqlandi:
`app.core.check_canon.same_check(staging, tiklangan) → True`.

**Xulosa: nusxa tiklanadi va tiklangan baza ustida ilova ko'tariladi.** Bu Phase 6A
yangilanish yo'lini ham qamradi: tiklangan baza 6A'dan OLDINGI holatda edi va boot DDL uni
muammosiz yangiladi.

**Takrorlash (buyruq)** — `PG_BIN` ni PG18 bin katalogiga qarating:
```bash
PG_BIN=<pg18>/bin \
REHEARSAL_DATABASE_URL="postgresql://postgres@127.0.0.1:55432/rehearsal" \
AFTER_FINGERPRINT=after.json PYTHON=<venv>/python.exe \
  bash scripts/restore_rehearsal.sh <nusxa>.dump
```

---

## 5. Qaytarish — IKKI XIL, ARALASHTIRMANG

> **Ilovani qaytarish sxema o'zgarishini QAYTARMAYDI.** Bu ikki alohida amal. Sxema
> o'zgarishi qo'shimcha bo'lsa — qaytarish **kerak emas va zararli**.

### 5.1 Qaysi biri kerakligini aniqlash

| Alomat | Sabab | Amal |
|---|---|---|
| `/health` 502, tugamaydi | konteyner ko'tarilmayapti (boot yiqilgan) | **A** |
| `/health` 200, lekin `build.commit` eski | deploy o'tmagan | tekshiruv, A emas |
| `/health/ready` 503, `/health` 200 | sxema/config tayyor emas | avval sababni o'qing, keyin **A** |
| Noto'g'ri biznes mantiqi, ma'lumot buzilmagan | kod nuqsoni | **A** |
| Ma'lumot o'chgan / noto'g'ri yozilgan | ma'lumot falokati | **B** |
| Sxema buzilgan (ustun/jadval yo'qolgan) | noto'g'ri migratsiya | **B** |

**Uchta savol — har qanday qaytarishdan OLDIN:**
1. Dalada qaysi klient versiyalari bor? (5F dan keyin chek serverdan olinadi — eski
   serverga qaytish chekni buzadi.)
2. Oxirgi nusxa yashilmi va 24 soatdan yangimi?
3. Qaytarib bo'lmaydigan hodisa yozilganmi (sotuv, to'lov, obuna to'lovi)?

### 5.2 A — ILOVANI qaytarish

**Qachon:** kod nuqsoni, boot yiqilishi, noto'g'ri xatti-harakat — **ma'lumot butun**.

**Buyruq** (Railway; bazaga TEGMAYDI):
```
deploymentRollback(id: "<oldingi deployment id>")
```
`railway redeploy` — **noto'g'ri asbob**, u OXIRGI deploy'ni qayta yuklaydi. Eski deployment
`REMOVED` ko'rinsa ham `canRollback=true` bo'lib qolaveradi. ~20–35 soniya, qayta build yo'q.

**Nima qilmaydi:** bazani qaytarmaydi. Qo'shilgan jadval/ustun joyida qoladi — va bu
**xavfsiz**: `required_schema` faqat *yetishmayotganni* tekshiradi, ortiqchaga yiqilmaydi;
SQLAlchemy ustunlarni aniq nomlab tanlaydi.

**Tekshirish (hammasi majburiy):**
```bash
curl -s .../api/v1/health        # build.commit == nishon SHA
curl -s .../api/v1/health/ready  # 200 + 8/8 true
```
va buzilgan oqimni qo'lda bir marta sinang.

**⚠️ Phase 6A dan keyin qaytarishning MA'LUM oqibati:** `app/tools/tenant_purge.py`
`SEMANTIC_REGISTRY` ga `plans`, `platform_admins`, `admin_audit_log` ni qo'shgan. Kod 6A
dan oldingi SHA'ga qaytarilsa jadvallar bazada **qoladi**, eski reyestr esa ularni bilmaydi
→ purge asbobi ularni `unclassified` deb topib **fail-closed** bo'ladi. Ya'ni qaytarishdan
keyin tenant purge **ishlamaydi** (ataylab, jim buzilishdan yaxshi). Yechim: purge kerak
bo'lsa oldinga qaytib 6A kodini tiklang.

### 5.3 B — BAZANI tiklash

**Qachon:** faqat ma'lumot yo'qolgan yoki buzilgan bo'lsa.

> **Tiklash — qaytarish asbobi EMAS.** U oxirgi nusxadan keyingi hamma narsani yo'qotadi
> (production'da 24 soatgacha sotuv). Ilova nuqsoni uchun **hech qachon** ishlatilmaydi.

Bosqichlar:
1. **To'xtating.** Yozuvni to'xtatmasdan tiklash — ikki haqiqat manbai.
2. **Hozirgi holatni saqlang** (buzuq bo'lsa ham): §3 dagi dump. Tergov uchun yagona nusxa.
3. **Mashq qiling, keyin qiling.** §4 dagi yo'l bilan bir martalik bazaga tiklab ko'ring.
4. **Rollarni oldindan yarating** — `restore_rehearsal.sh` buni o'zi qiladi; qo'lda
   qilsangiz unutmang, aks holda `--exit-on-error` yarim yo'lda to'xtaydi.
5. **Tiklang**, so'ng `db_fingerprint --compare` bilan capture barmoq izi bilan solishtiring.
6. **Ilovani ko'taring:** `python -m app.initdb` → `/health/ready` 200.
7. **Nima yo'qolganini yozib qo'ying** — nusxa vaqtidan keyingi hamma narsa.

---

## 6. Ochiq repo — ta'sir doirasi va remediatsiya

### 6.1 O'lchangan holat (metadata, hech narsa yuklab olinmagan)

| Fakt | Qiymat |
|---|---|
| `private` / `visibility` | **`false` / `public`** |
| fork · yulduz · kuzatuvchi | **0 · 0 · 0** |
| `allow_forking` | `true` |
| yaratilgan | 2026-08-17 · repo hajmi 30 MB |
| jami artefakt | **220** |

GitHub hujjatiga ko'ra **anonim** foydalanuvchi artefaktni yuklay olmaydi, lekin **ochiq
repoda tizimga kirgan har qanday hisob** o'qish huquqiga ega va artefaktlarni yuklaydi.
Fork/yulduz/kuzatuvchi nolligi — repo diqqatni tortmaganini ko'rsatadi, **himoya emas**.

### 6.2 Ochiq production barmoq izi tashiydigan JONLI artefaktlar: **61**

| Guruh | Soni | Hajm | Ichida nima ochiq | Tugash |
|---|---|---|---|---|
| `savdoos-db-*` (nusxa) | **22** | 47.8 MB | `fingerprint.json`, `fingerprint-before.json`, `*.meta.json`, `*.sha256` — dump shifrlangan | 2026-09-29 … 11-22 |
| `artifact-restore-*` (mashq) | **36** | 71 KB | `after.json`, `artifact/fingerprint.json`, `uuid-preflight.json` | … 2026-12-26 |
| `restore-rehearsal-*` (mashq) | **3** | 9 KB | `before.json`, `capture-after.json`, `after.json`, `uuid-preflight.json` | … 2026-12-26 |

Barmoq izi ichida: **25 biznes jadvalining aniq qator sanog'i** (`customers`, `sales`,
`sale_items`…), `cash_counts`, `max_timestamps` va **`ledger_sums` — naqd ledgerning
yo'nalishlar bo'yicha PUL SUMMALARI**, hamda `target_db`. **Mijoz ismi, telefoni yoki PIN
kodi YO'Q** — `db_fingerprint` ularni umuman o'qimaydi. Ya'ni bu **PII emas, biznes
ko'rsatkichlari**: aylanma, hajm, o'sish sur'ati.

⚠️ Dump'ning maxfiyligi butunlay **bitta simmetrik parolga** tayanadi, hujumchi esa
shifrmatnni cheksiz saqlab, cheklovsiz urinib ko'rishi va 22 ta suratdan eng zaifini
tanlashi mumkin. **Ta'sir retroaktiv:** nusxa olingan bo'lsa, artefaktni o'chirish
yordam bermaydi.

### 6.3 Nima TUZATILDI (kod — 2026-09-29 da `main` ga MERGE QILINGAN, `e60c213a`)

| # | Tuzatish | Fayl |
|---|---|---|
| 1 | Nusxa barmoq izlari **shifrlanadi** | `_db-backup-core.yml` |
| 2 | **Mashq dalillari** ham shifrlanadi (36+3 artefakt manbai) | `restore-rehearsal.yml` |
| 3 | Eski (ochiq barmoq izli) artefaktlar hamon tiklanadi — zaxira yo'l | `restore_from_artifact.sh` |
| 4 | `*.dump.gpg`, `*.sql.gz`, `after-fingerprint.json` ignore'ga qo'shildi | `.gitignore` |
| 5 | Hujjatdagi "repo yopiq" yolg'on da'vosi to'g'rilandi | `CLAUDE.md`, core sarlavhasi |
| 6 | Production raqamlari **jurnaldan** olib tashlandi (jurnal loginsiz o'qiladi) | `_db-backup-core.yml`, `restore-rehearsal.yml` |
| 7 | HAQIQIY production endpoint (host+port+db) testlardan olindi | `tests/cash/test_artifact_restore.py` |
| 8 | `qa_auth_results.json` (bitta telefon raqami) untrack qilindi | — |
| 9 | Shifrlash **tekshiriladi**, `gpg`/parol yo'q bo'lsa **fail closed** | `scripts/encrypt_evidence.sh` (yangi) |
| 10 | SHA butunlay tekshiriladi (JSON in'ektsiyasi yopildi) | `staging-deploy.yml` |
| 11 | Konkurent deploy: navbat + "nishon hali main tepasimi" tekshiruvi | `staging-deploy.yml` |

### 6.4 Ustuvorlik bo'yicha remediatsiya (hech biri BAJARILMADI — ega qaroriga bog'liq)

**P0 — bugun, 1 daqiqa**
1. **Reponi yopiq qiling.** Auditoriya "har qanday hisob" dan hamkorlarga qisqaradi;
   180 kunlik saqlash ishlay boshlaydi; hujjatdagi taxminlar rost bo'ladi.
   *Tuzatmaydi:* retroaktiv emas; `BACKUPS.md:49` hamon GitHub artefaktini taqiqlaydi;
   kim yuklaganini ko'rsatmaydi. **O'zi yetarli emas, lekin eng arzon birinchi qadam.**

**P1 — shu hafta**
2. **Bu branch'ni merge qiling** (§6.3 dagi 5 tuzatish) — kelajakdagi artefaktlar toza bo'ladi.
3. **`BACKUP_PASSPHRASE` ni almashtiring** — §7 dagi tartib bilan. Eski parol ochiq
   auditoriyaga tushgan nusxalarni himoya qilgan; yangi nusxalar yangi parol ostida bo'lsin.
   ⚠️ Almashtirishdan **oldin** eski parol bilan oxirgi artefaktni tiklab ko'ring va eski
   parolni "eski nusxalar uchun" deb saqlang.

**P2 — qaror talab qiladi**
4. **Production nusxasining manzili.** GitHub artefakti ochiq repoda "himoyalangan manzil"
   emas va loyihaning o'z qoidasi (`BACKUPS.md:49`) uni taqiqlaydi. Variantlar:
   Railway managed backup (tarifda bor-yo'qligi **noma'lum** — siz tasdiqlaysiz) yoki
   obyekt-saqlash (siz bucket + **faqat-yozish** kalit berasiz; men hech qanday hisob yaratmayman).
5. **22 ta jonli nusxa bilan nima qilish.** O'chirish kelajakdagi yuklashni to'xtatadi,
   allaqachon olingan nusxaga ta'sir qilmaydi. **Men hech narsa o'chirmadim.**
   ⚠️ O'chirishdan oldin: kamida bitta **tekshirilgan** nusxa saqlanib qolsin — ya'ni
   Restore Rehearsal (artefakt rejimi) unda **yashil** bo'lgan bo'lsin. Tavsiya: eng yangi
   `weekly` (id `10919119685`, 2026-11-22 gacha) **saqlansin**, qolganlari muddati bilan o'chsin.
6. **5 ta begona GitHub App** (netlify, zeet-co, vercel, render, railway-app) olib tashlansin.

**Standart qoida (repo ochiq ekan):** `ci.yml` hech qachon `secrets.*` ga murojaat qilmasin
va hech bir workflow `pull_request_target` ishlatmasin.

### 6.5 Qoladigan xavf (remediatsiyadan keyin ham)

- **Retroaktiv sizish qaytarilmaydi.** 2026-09-13 … 09-28 oralig'idagi 22 ta nusxa va 39 ta
  mashq artefakti ochiq auditoriyada turgan. Kim yuklaganini bilishning **iloji yo'q** —
  GitHub artefakt yuklab olish jurnalini bermaydi.
- Reponi yopiq qilish **kodni** ham yopadi, lekin allaqachon klonlangan nusxalarni qaytarmaydi.
- `BACKUP_PASSPHRASE` almashtirilsa eski shifrlangan nusxalar **faqat eski parol bilan**
  ochiladi — parolni yo'qotmang.
- Mashq artefaktlaridagi `*.meta.json` ochiq qoladi (ulanish satri yo'q, lekin baza nomi,
  hajm va checksum bor). Bu ataylab: tiklash uchun parolsiz butunlik tekshiruvi kerak.

## 7. Sir almashtirish — ro'yxat (faqat hujjat)

> Men hech qanday sirni **o'qimadim, chop etmadim, nusxalamadim va almashtirmadim**.
> Almashtirish — **operator amali**. Quyida faqat tartib.

### 7.0 Almashtirish SHART bo'lgan holatlar (2026-09-29 holati)

**Git tarixi bo'yicha — almashtirish SHART EMAS.** 153 ref, 500 commit, 941 ta tarixda
qo'shilgan yo'l skanerlandi: **birorta ham haqiqiy sir commit qilinmagan**. `.env` hech
qachon kuzatilmagan (faqat `.env.example` shablonlari), `.gitignore` uni **birinchi
commitdan** (`720c7e6`, 2026-08-17) beri bloklaydi, ya'ni "qoidadan oldingi oyna" ham yo'q.
Topilgan har bir "sirga o'xshash" hit — shablon, hujjat namunasi yoki ataylab yozilgan
rad-etish test ma'lumoti bo'lib chiqdi (masalan `test_sir_topilsa_toplam_rad`).

| Sir | Almashtirish sababi bormi | Ustuvorlik |
|---|---|---|
| `BACKUP_PASSPHRASE` | **HA** — 61 ta artefakt ochiq auditoriyada turgan; dump'larning yagona himoyasi shu parol | **P1** |
| `PROD_DATABASE_URL` | Tarixda oshkor bo'lmagan. **Lekin** endpoint (host/port/db) ochiq repoda turgan edi — parolning o'zi emas. Ehtiyot chorasi sifatida tavsiya etiladi | P2 |
| `VENDOR_ADMIN_KEY`, `VENDOR_TOTP_SECRET`, `SECRET_KEY` | Oshkor bo'lganiga dalil **yo'q** | kerak emas |
| Railway hisob tokeni | Bu sessiyada yaroqsiz bo'lib qoldi (CLI ishlaydi, xom token yo'q) — sababi noma'lum | egada tekshirish |

⚠️ **Tartib muhim:** `BACKUP_PASSPHRASE` ni almashtirish 61 ta mavjud artefaktni
**ochib bo'lmaydigan** qilmaydi (ular eski parol bilan shifrlangan va eski parol hamon
ishlaydi) — lekin **yangi** nusxalarni eski paroldan ajratadi. Shu bois §6.4 dagi tartib:
avval bu branch merge qilinsin, keyin parol almashtirilsin.


**Umumiy qoidalar**
- `gh secret set NAME --body "<qiymat>"` **ishlatmang** — u shell tarixiga tushadi.
  `gh secret set NAME --repo ...` deb yozing va qiymatni **so'rovda** joylang.
- `railway variables --kv` / `--json` umumiy terminalda **ishlatmang** — qiymatlarni chop etadi.
- GitHub sirlari **faqat yoziladi**: noto'g'ri qiymatni almashtirish mumkin, o'qish mumkin emas.
  Har qiymatni **parol menejerida** oldindan saqlang.

**⚠️ `BACKUP_PASSPHRASE` — eng xavfli band.** Uni almashtirish **barcha mavjud shifrlangan
nusxalarni ochib bo'lmaydigan qiladi**. Almashtirishdan oldin:
1. Eski parol bilan eng oxirgi artefaktni **tiklab ko'ring** (Restore Rehearsal, artefakt rejimi).
2. Eski parolni parol menejerida **"eski nusxalar uchun"** deb saqlang — o'chirmang.
3. Faqat shundan keyin yangisini qo'ying, va **darhol** yangi backup run qiling hamda uni tiklab ko'ring.

**PostgreSQL parolini almashtirish tartibi**
1. Oldindan: oxirgi nusxa yashil va tiklanishi tasdiqlangan bo'lsin.
2. Railway → Postgres-d29B → parolni almashtiring.
3. `savdoos` servisi bazaga **qanday murojaat qilishini** aniqlang: Railway o'zgaruvchi
   **havolasi** (`${{Postgres-d29B.DATABASE_URL}}`) bo'lsa — o'zi yangilanadi, qo'lda ish yo'q;
   **nusxa qiymat** bo'lsa — uni ham qo'lda yangilang. *(Bu fakt hali aniqlanmagan: uni
   aniqlashning yagona yo'li qiymatlarni materializatsiya qiladigan so'rov, men undan
   ataylab voz kechdim. Ega Railway UI'da bir qarashda ko'radi.)*
4. GitHub sirlarini yangilang: `PROD_DATABASE_URL` (va §3 yoqilgan bo'lsa `STAGING_DATABASE_URL`).
5. Tekshiring — **sirsiz buyruqlar bilan**:
   `curl -s .../api/v1/health/ready` → 200 · `gh workflow run db-backup.yml` → yashil.
6. Biror qadam yiqilsa — to'xtang, oldingi qiymatni qaytaring (parol menejeridan), keyin tergov.

**Ochilgan `PROD_DATABASE_URL` ning ta'siri:** u to'g'ridan-to'g'ri, to'liq huquq bilan
production bazasiga ulanish imkonini beradi (barcha do'konlar, mijozlar, qarzlar, naqd
ledger). Blast radius — butun baza. Parol almashtirilgach eski satr foydasiz bo'ladi, lekin
**almashtirilgunga qadar olingan nusxalar qolaveradi**.

---

## 8. Ushbu ishda TEGILMAGAN narsalar

- Production va staging bazalari — **yozilmadi**. Staging'ga faqat o'qish so'rovlari.
- Deploy **qilinmadi**.
- GitHub sozlamalari — **tegilmadi** (sirlar, o'zgaruvchilar, ruleset, branch himoyasi,
  repo ko'rinishi). `STAGING_DEPLOY_ENABLED` va `STAGING_BACKUP_ENABLED` hamon YO'Q.

⚠️  **Bu ro'yxat 2026-09-29 da ikki band bo'yicha ESKIRDI** (ikkalasi ham ega qo'li bilan,
bu hujjat orqali emas):
- Railway trigger'ida `checkSuites` **`false` → `true`** qilindi (§2.6, §2.7).
- `main` ga bitta BO'SH probe commit'i push qilindi (`09a2eacb…`, 0 fayl) — staging
  yetkazib berishni o'lchash uchun, ega ruxsati bilan (§2.7).
- `p8-release-safety` **`main` ga merge qilindi** (`e60c213a`).
- Sirlar **o'qilmadi va chop etilmadi**.

## 9. Ochiq bandlar

1. Backup yiqilganda emaildan kuchliroq xabar (§3.5) — **bajarilmagan**.
2. Production nusxasining manzili bo'yicha qaror (§6) — **egada**.
3. 22 ta jonli production artefakti bilan nima qilish — **egada**.
4. `savdoos` DB'ga havola bilan murojaat qiladimi yoki nusxa qiymat bilan (§7.3) — **aniqlanmagan**.
5. Begona GitHub App'lar (5 ta) olib tashlanmagan.
6. `BACKUPS.md:49` GitHub artefaktini taqiqlaydi — hozirgi amaliyot bu qoidani buzadi;
   qoida yangilanishi yoki amaliyot o'zgarishi kerak.
