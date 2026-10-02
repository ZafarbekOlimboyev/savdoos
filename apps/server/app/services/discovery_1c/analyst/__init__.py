# -*- coding: utf-8 -*-
"""TALQIN QATLAMI — ko'p tilli leksika va deterministik analitik (yadrodan TASHQARIDA).

⚠️ BU QATLAM FAQAT TAXMIN QILADI. U hech narsani tasdiqlamaydi va tasdiqlay ham olmaydi:
   eng yuqori chiqishi — `CANDIDATE`. `VERIFIED` bu kanalda UMUMAN yo'q, `HUMAN_CONFIRMED`
   esa faqat operatorning ALOHIDA tasdiq hujjatidan keladi (`ai.validate_analysis` ni
   `allow_human_confirmed=True` bilan chaqirgan kod), modelning yoki bu qatlamning
   ishonchidan EMAS.

⚠️ BOG'LIQLIK BIR TOMONLAMA: yadro (`discovery_1c` ning o'zi — `schema`, `bundle`, `redact`,
   `metadata`, `graph`, `probe`, `ai`, `export_adapter`) bu paketni IMPORT QILMAYDI va
   qilmasligi kerak. Bu paket yadroni o'qiydi, yadro esa bu paketni bilmaydi. Shu bois
   talqin bilimini o'zgartirish yadroning shartnomasiga TEGMAYDI.

NEGA AJRATILGAN. Yadro «nima bor» ni yozadi, bu qatlam «nima ma'nosi bo'lishi mumkin» ni
taxmin qiladi. Ikkisi bitta faylda tursa taxmin dalilga o'xshab qolardi. Ajratish ataylab
KO'RINADIGAN: yadroning statik qo'riqchisi (`tests/test_discovery_1c_universal.py`) yadroda
konfiguratsiyaga oid amaliy nom bo'lmasligini tekshiradi, ko'p tilli lug'at esa aynan shunday
so'zlardan iborat. Shu bois lug'at yadroda EMAS, shu paketda yashaydi.

Tarkibi:

    lexicon.py     deterministik leksik normalizatsiya, kirill->lotin, ko'p tilli KUCHSIZ
                   ishoralar va chalg'ituvchi shakllar (qarshi dalil uchun)
    heuristics.py  `ai.DiscoveryAIAnalyzer` protokolini DETERMINISTIK bajaradigan analitik
                   (`HeuristicAnalyzer`), hamda testlar uchun `NullAnalyzer` va
                   `RecordedAnalyzer`

QAT'IY QOIDALAR (yadroning qoidalari bilan bir xil):
  · Tarmoq chaqiruvi YO'Q, sir YO'Q, jarayon ochish YO'Q, COM YO'Q. Bu qatlam ham faqat
    kirishdagi lug'atni o'qiydi.
  · Nom mosligi O'ZI BILAN hech qachon tasdiqlangan xarita bermaydi — u KUCHSIZ dalil.
  · Qaralmagan konsept TASHLANMAYDI: u `UNKNOWN` bo'lib hisobga olinadi
    (`heuristics.coverage`). «Qaralmadi» va «yo'q» bir xil narsa emas.
  · Dalil yo'q bo'lsa gipoteza CHIQARILMAYDI. Dalilsiz nomzod — shunchaki taxmin.
  · Vaqt O'YLAB CHIQARILMAYDI: bu qatlamda vaqt tamg'asi umuman yo'q.
  · Determinizm: bir xil kirish — AYNAN bir xil chiqish, tartiblangan.
"""
