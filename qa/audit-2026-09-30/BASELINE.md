# BinOS mustaqil adversarial QA — baza qaydi (2026-09-30)

## Audit qilingan branch/SHA'lar (fetch'dan keyin tekshirilgan)

| Area | Branch | SHA | Izoh |
|---|---|---|---|
| Stabil baza / QA | origin/main | `e60c213a446caf0c8e845bd9caa50113aad0e194` | P8 release safety merge qilingan main tepasi |
| POS OFFLINE (P9) | p9-pos-offline-shift-safety (lokal) | `482b3f38bd3b14ac315b71115352052bfa89818a` | baza d916b9b + P7 UI (4 commit) + 1 ta P9 commit; Phase 3A hali commit qilinmagan bo'lishi mumkin — topilmalar 3A'dan keyin qayta baholanadi |
| SAFE (index_guard) | integration/p6c-phase1 (lokal) | `85be3991bf7f087759949ff1e2545a98accbaea7` | index_guard FAQAT shu branchda (main'da yo'q) |
| RELEASE SAFETY | p8.1-release-gate-fixes (lokal) | `38f1d750d1ea9d65a397d13b5c1648054a1d5312` | e60c213a + 1 commit (staging-deploy/backup) |
| 1C | p5-1c-discovery-collector (lokal) | `40150b54660f9a9adea3ef68442dcbcf35ee3c67` | merge-base 25a55fb7 |

Muhim: **origin'da faqat `main` mavjud** — qolgan audit branchlari faqat lokal.
Lokal `main` (d916b9b) origin/main'dan orqada (e60c213a ning ajdodi).

## QA izolyatsiyasi
- Worktree: `.claude/worktrees/qa-binos-security`, branch `qa/binos-independent-security`, baza e60c213a.
- Boshqa sessiyalarning worktree'lariga TEGILMAGAN; boshqa SHA'lar faqat `git show/grep/diff` orqali o'qiladi.

## Muhit va cheklovlar (2026-09-30 02:15 mahalliy)
- RAM: 15.4 GB jami, **~1.5 GB bo'sh** — og'ir to'plamlar XAVFLI.
- Disk C: 19.2 GB bo'sh.
- **~300 ta begona `postgres` jarayoni faol** (boshqa sessiyalarning to'plamlari, oxirgisi 02:13 da boshlangan) + 6 ta python.
- Qoida (§7) bo'yicha: PG darajasidagi isbotlar **PENDING** — statik tahlil + SQLite darajasidagi sintetik sinovlar bilan boshlanadi; RAM/PG bo'shagani kuzatiladi.

## Uslub
1-bosqich: 3 fazali adversarial workflow (Xarita → Qidiruv → Triaj), faqat o'qish.
2-bosqich: tirik qolgan P0/P1 nomzodlar uchun fokusli reproduksiya sinovlari (test-only fayllar, ketma-ket, yengil).
3-bosqich: PG talab qiladigan topilmalar — resurs bo'shasa haqiqiy PG bilan; bo'lmasa PENDING deb belgilanadi.

Hech qanday production kod o'zgartirilmaydi; tuzatishlar developer-handoff sifatida beriladi.
