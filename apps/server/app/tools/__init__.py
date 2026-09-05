# -*- coding: utf-8 -*-
"""Cash Migration — operator CLI driver'lari (`python -m app.tools.cash_*`).

Bu paket faqat MAVJUD, TESTLANGAN Phase 0/1/2/3 asboblarини (phase0/phase1/backfill/
compare_engine/preflight/mode) yupqa CLI qobig'iда o'raydi. Operator ularni Railway
terminalida xavfsiz ishlatadi. Yangi biznes-mantiq YO'Q — faqat argparse + I/O + exit code.

Umumiy XAVFSIZLIK invariantlari (har CLI ularга rioya qiladi — `_common` da markazlashган):
  * Sirlar HECH QACHON chop etilmaydi — TARGET faqat `current_database()` nomini ko'rsatadi
    (host/user/password/URL emas); DATABASE_URL faqat mavjud/yo'q (true/false) sifatida.
  * LEDGER_PRIMARY HECH QACHON yoqilmaydi; mode HECH QACHON o'zgartirilmaydi (`set_mode` yo'q).
  * DELETE/TRUNCATE/DROP YO'Q. Yozuv faqat --apply bilan; default DOIM dry-run/read-only.
  * Sarlavha MODE (DRY-RUN/APPLY/READ-ONLY) + TARGET (db nomi, tenant scope, T0) ni sirlarсиз
    ko'rsatadi; --apply'дан oldin "THIS WILL WRITE ..." ogohlantirishi.
"""
