# BinOS — Reliz xavfsizligi runbook'i (Phase 8)

Bu hujjat **operator uchun**. Har bandda: nima qilinadi · nima kutiladi · qachon TO'XTAYDI.
Raqamlar taxmin emas — 2026-09-28 da o'lchangan; har biri yonida qanday o'lchangani yozilgan.

Qamrov: reliz darvozasi (§2), staging avtomatik nusxasi (§3), tiklash mashqi (§4),
qaytarish — ilova va baza (§5), ochiq repo ta'siri (§6), sir almashtirish (§7).

> **Bu hujjatdagi HECH NARSA o'z-o'zidan yoqilmaydi.** Jonli Railway/GitHub sozlamalari
> **tegilmagan**. §2 va §3 dagi har bir aktivatsiya qadami — **ega qo'li bilan**.

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

### 2.1 Bugungi holat (o'lchangan)

| Fakt | Qiymat | Qanday o'lchangan |
|---|---|---|
| Railway trigger'lari | butun loyihada **1 ta** | GraphQL `project.deploymentTriggers` |
| U qayerda | staging / savdoos / `main` / github | o'sha so'rov |
| `checkSuites` | **`false`** | o'sha so'rov |
| Production trigger'lari | **0 ta** | o'sha so'rov |
| `main` ga tushgan QIZIL CI run | **40 ta** (2026-08-26…09-13), eng uzun ketma-ketlik **20 ta** (`75d48cd`→`68f73ae`) | `gh api --paginate .../actions/runs?branch=main` |
| CI davomiyligi | min 9.0 · median 23.4 · max 30.1 daqiqa | oxirgi 16 muvaffaqiyatli run |
| GitHub branch himoyasi | **yo'q** (`404 Branch not protected`) | `gh api .../branches/main/protection` |
| Ruleset | **yo'q** (`[]`) | `gh api .../rulesets` |

**Ya'ni bugun `main` ga push — CI kutilmasdan darhol staging deploy'ini boshlaydi**, va bu
nazariy emas: 40 marta sodir bo'lgan.

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

1. **Darhol, 1 daqiqa — vaqtinchalik chora.** Railway → savdoos → Settings → staging →
   *Wait for CI* = ON. Bugungi eng katta teshikni yopadi.
   GraphQL varianti: `deploymentTriggerUpdate(id:"b46dc634-d2e1-4c6d-a8cd-774c51d75995", input:{checkSuites:true})`.
   ⚠️ `DeploymentTriggerUpdateInput` ning to'rt maydoni ham **ixtiyoriy skalyar** — tushirib
   qoldirilgani `null` qilinadimi yoki tegilmaydimi **noma'lum**. Shuning uchun **UI
   toggle'ini afzal ko'ring**, GraphQL ishlatsangiz `branch` va `repository` ni ham
   hozirgi qiymatlari bilan bering.
2. **Kuzating (1 hafta).** Deploy qancha marta Uptime/backup tufayli to'xtadi? Nol bo'lsa —
   (a) yetarli, (d) shart emas.
3. **(d) ga o'tish** (ixtiyoriy, agar 2-bandda shovqin bo'lsa):
   a. Secret `RAILWAY_TOKEN` qo'shing.
   b. Variable `STAGING_DEPLOY_ENABLED=true`.
   c. **Va o'sha payt** Railway trigger'ini o'chiring (`deploymentTriggerDelete`) — aks holda
      ikki yo'l bir vaqtda deploy qiladi.
   d. Bitta test push bilan tekshiring: Actions'da `Staging Deploy` yashil, `/health` da yangi commit.
4. **Begona GitHub App'larni olib tashlang** (netlify, zeet-co, vercel, render, railway-app) —
   ular doimiy `queued` suite qoldiradi va check-suite maydonini ifloslaydi.
5. **Ruleset — alohida qaror.** PR talab qilish loyihaning `CLAUDE.md` dagi "push qil"
   oqimini buzadi. Bu jarayon qarori, xavfsizlik shoshilinchligi emas.

### 2.5 `staging-deploy.yml` — aktivatsiya ro'yxati

> **O'LCHANGAN NATIJA (2026-09-29/30).** `checkSuites=true` yoqilib `main` ga merge
> qilindi. Railway deployment yozuvini **umuman yaratmadi** — 2 soat 38 daqiqa, hujjatdagi
> 2 soatlik cheklovdan ham keyin. Ya'ni bu repoda o'sha bayroq "CI kutish" emas,
> **"hech qachon deploy qilmaslik"**. Hozirgi holat: staging `d916b9b` da qotgan,
> `main` esa `e60c213` da. **Eski yo'l amalda ishlamayapti.**
>
> ⚠️ Sabab HALI ISBOTLANMAGAN. Eng ko'rinadigan anomaliya — beshta begona ilova
> (`netlify`, `zeet-co`, `vercel`, `render`, `railway-app`) har commit'ga `queued`,
> 0 run check suite qoldiradi. LEKIN o'sha beshtasi `checkSuites=false` bilan
> **muvaffaqiyatli deploy bo'lgan** commitlarda ham bor edi (`d916b9b`, `25a55fb`) —
> demak ularning MAVJUDLIGI farqni tushuntirmaydi. Bu korrelyatsiya, sabab emas.
> Tergov: §2.7.

**AKTIVATSIYA TARTIBI — buzilmasin.** Eski yo'l **o'chiriladi va TASDIQLANADI**, keyin
yangisi yoqiladi. Teskari tartibda ikki deploy yo'li bir vaqtda ochiq qoladi va bitta
push ikki marta deploy qiladi (Railway trigger'i push bo'yicha, workflow CI'dan keyin).

| # | Qadam | Tekshiruv (o'tmasa TO'XTA) | Qaytarish |
|---|---|---|---|
| 0 | `main` kutilgan SHA'da, CI yashil | `gh run list --workflow ci.yml --branch main --limit 1` | — |
| 1 | Secret `RAILWAY_TOKEN` qo'shiladi | `gh secret list` da nom ko'rinsin | secret'ni o'chiring |
| 2 | **Quruq yurish:** `gh workflow run staging-deploy.yml -f commit_sha=<main tepasi>` | Run **skipped** bo'lsin (variable hali yo'q). Bajarilsa — darvoza sharti buzilgan, **TO'XTANG** | — |
| 3 | **ESKI YO'L O'CHIRILADI:** `deploymentTriggerDelete(id:"b46dc634-d2e1-4c6d-a8cd-774c51d75995")` | **§2.6 dagi tekshiruv:** `deploymentTriggers` **BO'SH** qaytishi shart | **§2.6 manifesti bilan qayta yaratish** |
| 4 | O'chirilgani **ikkinchi marta** tasdiqlanadi: `main` ga bo'sh commit push qilinadi | Railway'da **yangi deployment paydo BO'LMASIN** (eski yo'l haqiqatan o'lgan) | §2.6 |
| 5 | Variable `STAGING_DEPLOY_ENABLED=true` | `gh variable list` da ko'rinsin | variable'ni `false` — darvoza darhol yopiladi |
| 6 | **Jonli sinov:** `main` ga kichik o'zgarish push | ① CI yashil → ② `Staging Deploy` **ishga tushdi** (skipped emas) → ③ `/health` da `build.commit` yangi SHA → ④ `/health/ready` 200, 8/8 `true` | 5-qadam `false`, so'ng `deploymentRollback` |
| 7 | **Salbiy sinov (MAJBURIY):** CI'ni ataylab qizil qiladigan commit | `Staging Deploy` **ishga tushmasin**; staging `build.commit` **o'zgarmasin** | commit'ni revert |

⚠️ **4-qadamni o'tkazib yubormang.** «Trigger o'chirildi» degan API javobi — u haqiqatan
deploy qilmasligining isboti EMAS. Faqat bo'sh commit push qilib, deployment
paydo bo'lmasligini ko'rgandan keyin eski yo'l o'lgan deb hisoblash mumkin.

⚠️ **7-qadam ham majburiy.** Butun ishning maqsadi — qizil CI staging'ga yetmasligi.
Buni **isbotlamasdan** darvoza ishlayapti deb hisoblash mumkin emas.

**Darvoza xususiyatlari** (hammasi `apps/server/tests/test_ci_gate_script.py` da ijro
etiladigan testlar bilan qadab qo'yilgan, 4 tasi mutatsiya testi):
- Dalil FAQAT `main` ga **push** bo'lgan `CI` run'idan olinadi. `ci-proof/**` run'i —
  aynan shu SHA'da yashil bo'lsa ham — **dalil sifatida qabul qilinmaydi**.
- Shu SHA'dagi **har bir** main-push `CI` run'i `completed` + `success` bo'lishi shart
  (yiqilgan qayta yurgizish yashiringan qolmaydi).
- `in_progress`, `queued`, `cancelled`, `skipped`, `neutral`, `timed_out`,
  `action_required`, `failure` — **hammasi rad**.
- **Kerakli job ro'yxati `ci.yml` DAN o'qiladi** — qo'lda yozilmaydi. Job nomi o'zgarsa
  ro'yxat o'zi yangilanadi va darvoza jimgina bo'shashmaydi. Ro'yxat bo'sh chiqsa — **rad**.
- Har kerakli job `completed` + `success`; **yo'q job ham rad**.
- Nishon SHA `main` ning **hozirgi tepasi** bo'lishi shart. `workflow_dispatch` ham
  bundan **o'tmaydi** — eski SHA'ni qo'lda deploy qilish yo'li ataylab yopiq.
  Qaytarish `deploymentRollback` bilan qilinadi (Railway'dagi tayyor image, CI chetlab
  o'tilmaydi).
- API javobi **sahifalanadi** (`--paginate`): bitta SHA'da 100 dan ko'p run bo'lishi mumkin.
- `concurrency: staging-deploy`, `cancel-in-progress: false` — navbat, uzish yo'q.

### 2.6 Eski trigger — o'chirish, TASDIQLASH va QAYTA YARATISH manifesti

**Hozirgi holat (2026-09-30 da o'qilgan):**

| Maydon | Qiymat |
|---|---|
| trigger id | `b46dc634-d2e1-4c6d-a8cd-774c51d75995` |
| projectId | `32171ad7-cd7a-4eb8-8080-4806250fd1b8` |
| environmentId | `7eb2e84f-3c17-4dbb-b343-2b7a6df783fe` (staging) |
| serviceId | `4c0164e3-d24f-477d-a3c1-0a4c9283e218` (savdoos) |
| provider | `github` |
| repository | `ZafarbekOlimboyev/savdoos` |
| branch | `main` |
| checkSuites | `true` (2026-09-29 da `false` dan o'zgartirilgan) |
| rootDirectory | `/apps/server` — ⚠️ `DeploymentTrigger` da **o'qilmaydi** (input-only); qiymat `ServiceInstance.rootDirectory` dan olingan |

**O'chirish:**

    deploymentTriggerDelete(id: "b46dc634-d2e1-4c6d-a8cd-774c51d75995")

**O'chirilganini TASDIQLASH (majburiy, ikki qatlam):**

    query { project(id: "32171ad7-cd7a-4eb8-8080-4806250fd1b8") {
      deploymentTriggers { edges { node { id branch checkSuites environmentId serviceId } } } } }

`edges` **bo'sh** bo'lishi shart. So'ng §2.5 ning 4-qadami: `main` ga bo'sh commit push
qilib, Railway'da **yangi deployment paydo bo'lmasligini** ko'rish.

**QAYTA YARATISH (rollback) — barcha majburiy maydonlar bilan:**

    mutation { deploymentTriggerCreate(input: {
      projectId:     "32171ad7-cd7a-4eb8-8080-4806250fd1b8"
      environmentId: "7eb2e84f-3c17-4dbb-b343-2b7a6df783fe"
      serviceId:     "4c0164e3-d24f-477d-a3c1-0a4c9283e218"
      provider:      "github"
      repository:    "ZafarbekOlimboyev/savdoos"
      branch:        "main"
      rootDirectory: "/apps/server"
      checkSuites:   false
    }) { id branch checkSuites } }

⚠️ `checkSuites` **`false`** bilan qayta yaratiladi — `true` bu repoda deploy'ni butunlay
to'sadi (§2.5 dagi o'lchangan natija). Ya'ni qaytarish "ishlaydigan holat" ga qaytadi,
"to'silgan holat" ga emas.

⚠️ `DeploymentTriggerCreateInput` da `branch`, `environmentId`, `projectId`, `provider`,
`repository`, `serviceId` — **majburiy**; `checkSuites` va `rootDirectory` — ixtiyoriy.
`rootDirectory` ni **berish shart**: usiz Railway Dockerfile'ni repo ildizidan qidiradi
va build buziladi.

⚠️ **Yangi trigger id BOSHQA bo'ladi.** Qayta yaratgandan keyin uni o'qib, shu bo'limdagi
jadvalni yangilang — aks holda keyingi o'chirish noto'g'ri id bilan urinadi.

⚠️ **`deploymentTriggerUpdate` tuzog'i:** to'rtta maydonni ham hozirgi qiymati bilan
yuborish **rad etiladi** (`Problem processing request`); faqat `{ checkSuites: ... }`
yuborilganda ishlaydi va qolgan maydonlar **saqlanadi** (javobning o'zi buni ko'rsatadi).
Ya'ni bu API'da tushirib qoldirish = tegilmaydi.

### 2.7 Nega `checkSuites=true` deploy qilmadi — TERGOV

Faqat-o'qish tergovi (Railway GraphQL + GitHub API). **Ikkala nomzod to'siq ham istisno
qilindi.** Nosozlik check-suite darvozasida EMAS — u **deployment yozuvi yaratilishidan
YUQORIDA**, ya'ni Railway tomonidagi nuqsonga o'xshaydi.

**Hal qiluvchi fakt: hech qanday holatda yozuv YO'Q**

`DeploymentStatus` enum'ida **13** qiymat bor, jumladan **`WAITING`** va **`SKIPPED`**.
Railway hujjati: darvozalangan deploy **`WAITING` holatida yozuv yaratadi**, 2 soatlik
cheklov esa **`SKIPPED`** yozuv qoldiradi. Tekshirildi — eng yangi 100 qator, **holat
filtrisiz**, **`includeDeleted: true`** bilan: `e60c213` uchun **birorta qator yo'q**.
Loyiha bo'ylab eng yangi deployment hamon `082acede` / `d916b9b` / 2026-09-28T11:34:37Z.
Railway hatto yangi SHA'dan konfiguratsiyani ham **o'qimagan**:
`resolvedFileConfig.commitHash` hamon `d916b9b`.

Ya'ni: Railway push'ni deployment obyektiga **umuman aylantirmadi**. Bu "kutayotgan edi"
dan tubdan farq qiladi.

**ISTISNO QILINDI — beshta begona `queued` suite**

Uch mustaqil asos: ① hujjat: «boshqa GitHub ilovalarining tekshiruvlari **e'tiborsiz
qoldiriladi**» ② ular `head_branch = ci-proof/p8-release-safety` da, `main` da **emas** —
09:16:10Z dagi ci-proof push yaratgan ③ nazorat holati: `d916b9b` da **aynan o'sha beshtasi**
bor edi va u main push'dan **5 soniya** keyin deploy bo'lgan.

**ISTISNO QILINDI — `skipped` suite (mening oldingi yetakchi gipotezam)**

Men bu gipotezani kuchli deb hisoblagandim, chunki u deploy bo'lgan/bo'lmagan commitlar
orasidagi haqiqiy farqni ko'rsatardi. **Vaqt chizig'i uni rad etadi:**
- `skipped` suite faqat **17:57:37Z** da paydo bo'ldi — push esa 17:28:45Z da edi.
  Deployment yozuvi push'dan keyingi **8 soat 29 daqiqa** ichida **na oldin, na keyin**
  yaratilmadi. Agar u to'siq bo'lganida, u paydo bo'lishidan oldingi 29 daqiqada yozuv
  yaratilishi kerak edi.
- 18:53:50Z da uchinchi main suite'i `success` bo'lib tugadi; shundan keyin **uchala**
  main-branch github-actions suite'i ham **to'smaydigan terminal holatda** edi — va
  baribir hech narsa yaratilmadi.
- Hujjat: «`skipped` yoki `neutral` **hech qachon to'smaydi**».

**Boshqa istisno qilinganlar:** `watchPatterns` (ikkala instansiyada `[]`) ·
`rootDirectory` bo'yicha filtr (o'zgargan 16 fayldan 5 tasi `apps/server/` ostida) ·
`sleepApplication=false` · `drainingSeconds=null` · servis/muhit o'chirilmagan
(`deletedAt=null`) · loyiha muddati/temp holati · plan limitlari (hobby,
`builds.concurrent=3`, hech narsa ishlamayotgan) · SHA bo'yicha dublikat
(`d916b9b` ham ci-proof branchida turgan, keyin main'ga ff qilingan va deploy bo'lgan —
dublikat tekshiruvi check-darvozasidan YUQORIDA bo'lardi, shu bois bu nazorat haqiqiy).

**QOLGAN GIPOTEZA (SUPPORTED, isbotlanmagan)**

Railway 17:28:45Z push'ini `checkSuites=true` kod yo'lida deployment obyektiga
aylantirmadi — webhook yetib bormaganmi yoki trigger baholashi yiqilganmi. Har qanday
hujjatlangan o'qishda deploy davom etishi kerak edi, va **hech qanday o'qishda yozuv
butunlay yo'q bo'lmasligi kerak edi**.

⚠️ **Halol cheklov:** Railway'ning uchala feed'i (`events`, `environmentHistory`,
`auditLogs`) 2026-09-28T11:35:44Z da to'xtaydi — ular **bizning 17:20Z dagi `checkSuites`
o'zgartirishimizni ham qayd etmagan**. Demak ularning 2026-09-29 uchun bo'shligi webhook
haqida **zaif dalil** va Railway push'ni ko'rmaganini **isbotlamaydi**. GitHub App yetkazib
berish jurnali bu hisobdan o'qilmaydi (`app/hook/deliveries` → 401), repo darajasidagi
hook'lar `[]` (App integratsiyasi uchun normal).

**Eksperimentlar** (bajarilmagan, har biri **ega ruxsatini** talab qiladi):
1. **Eng arzon va eng ma'lumotli:** `checkSuites=false` → `main` ga bo'sh commit.
   Deploy bo'lsa: trigger sog'lom, nuqson aynan `checkSuites=true` yo'lida. Bu bir vaqtda
   staging'ni `main` bilan tenglashtiradi ham.
2. Railway qo'llab-quvvatlash: push 17:28:45Z, trigger `b46dc634-…`, `checkSuites=true`,
   deployment obyekti **umuman yaratilmagan**, `resolvedFileConfig.commitHash` hamon eski.
3. Beshta begona App'ni olib tashlash — endi **ustuvor emas**: ular istisno qilindi.

**Amaliy tavsiya.** `staging-deploy.yml` check-suite maydoniga **umuman tayanmaydi** va
Railway'ning `checkSuites` kod yo'lini **chetlab o'tadi** — u faqat `CI` workflow run
xulosasini o'qib, `serviceInstanceDeployV2` ni to'g'ridan-to'g'ri chaqiradi. §2.5 tartibi
bilan yoqilsa, bu nuqson ahamiyatsiz bo'ladi. Oraliq chora sifatida 1-eksperiment
staging'ni darhol tiklaydi.

---

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
3. Variable `STAGING_BACKUP_ENABLED=true` — shundan keyin jadval ishlaydi.

**Qaytarish:** variable'ni `false` qiling — jadval darhol to'xtaydi, sir joyida qoladi.

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

### 6.3 Nima TUZATILDI (kod, hali merge qilinmagan)

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

- Jonli Railway sozlamalari — **tegilmadi** (trigger, `checkSuites`, o'zgaruvchilar).
- GitHub sozlamalari — **tegilmadi** (sirlar, ruleset, branch himoyasi, repo ko'rinishi).
- Production va staging bazalari — **yozilmadi**. Staging'ga faqat o'qish so'rovlari.
- Deploy **qilinmadi**, `main` ga **merge qilinmadi**.
- Sirlar **o'qilmadi va chop etilmadi**.

## 9. Ochiq bandlar

1. Backup yiqilganda emaildan kuchliroq xabar (§3.5) — **bajarilmagan**.
2. Production nusxasining manzili bo'yicha qaror (§6) — **egada**.
3. 22 ta jonli production artefakti bilan nima qilish — **egada**.
4. `savdoos` DB'ga havola bilan murojaat qiladimi yoki nusxa qiymat bilan (§7.3) — **aniqlanmagan**.
5. Begona GitHub App'lar (5 ta) olib tashlanmagan.
6. `BACKUPS.md:49` GitHub artefaktini taqiqlaydi — hozirgi amaliyot bu qoidani buzadi;
   qoida yangilanishi yoki amaliyot o'zgarishi kerak.
