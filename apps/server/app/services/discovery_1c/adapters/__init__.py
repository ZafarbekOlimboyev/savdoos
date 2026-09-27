# -*- coding: utf-8 -*-
"""Konfiguratsiyaga xos adapterlar — YADRODAN TASHQARIDA, hozircha BO'SH.

Yadro (`../`) hech qanday konfiguratsiyani bilmaydi va bilishi ham shart emas. Lekin bir kun
konfiguratsiya TASDIQLANGANDA, «bu oilada nomenklatura odatda falon katalogda bo'ladi» degan
bilim kerak bo'ladi. O'sha bilim FAQAT shu papkada yashaydi.

ADAPTER NIMA QILA OLADI: nishon uchun NOMZOD taklif qilish va taklifiga KUCHSIZ dalil
(`name_match`, `synonym_match`, `type_shape`) biriktirish.

ADAPTER NIMA QILA OLMAYDI: `VERIFIED` berish. Bu texnik jihatdan ham imkonsiz —
`schema.confidence_error` darajani dalil TURI bilan chegaralaydi, va adapter kuchli dalil
(odam tasdig'i, arifmetik isbot) ishlab chiqara olmaydi. Ya'ni «adapter shunday deb o'ylaydi»
hech qachon «tekshirildi» ga aylanmaydi.

Adapter yozilganda `test_discovery_1c_universal.py` uni tekshirmaydi (u `adapters` ni chetlab
o'tadi) — chunki bu papkaning butun MAQSADI konfiguratsiyaga xos bo'lish.
"""
