# -*- coding: utf-8 -*-
"""Universal 1C Discovery Collector — YADRO (konfiguratsiyadan MUSTAQIL).

Bu modul 1C'ga ULANMAYDI va 1C runtime'ini TALAB QILMAYDI. U faqat discovery to'plamini
(`binos-1c-discovery-v1`) o'qiydi, tekshiradi, tozalaydi va deterministik yozadi. To'plamni
1C ichida ishlaydigan yig'uvchi (`.epf`) chiqaradi — u ALOHIDA, keyingi task.

NEGA AYNAN SHUNDAY BO'LINGAN: ekstraktorning chiqish qatlami konfiguratsiyaga bog'liq emas,
o'qish so'rovlari esa bog'liq. Shu bois chiqish qatlami (sxema, validator, xesh, redaksiya)
hozir yoziladi va 1C'siz to'liq sinaladi; so'rovlar esa konfiguratsiya TASDIQLANGANDAN keyin.

YADRODA BIRORTA KONFIGURATSIYAGA YOKI IJARACHIGA OID NARSA YO'Q. Amaliy metadata nomlari
(katalog, registr, rekvizit nomlari) bu yerda QATTIQ YOZILMAYDI — ular to'plam ICHIDAN kelgan
MA'LUMOT. Yadro faqat 1C PLATFORMASINING umumiy tushunchalarini biladi.
Konfiguratsiyaga xos bilim faqat ixtiyoriy adapterga tushadi (`adapters/`, hozircha bo'sh).

Oqim:

    schema.py    lug'atlar: nishonlar, manba turlari, dalil turlari, ishonch darajalari
    bundle.py    to'plamni yuklash / tekshirish / deterministik yozish / mazmun xeshi
    redact.py    sirlarni topish va olib tashlash (fail-closed: shubha bo'lsa RAD)

FAIL-CLOSED QOIDALAR (`binos-1c-v1` bilan bir xil qat'iylik):
  · JSON SONI TAQIQLANGAN. Har qanday sanoq — MATN ("7137"). Sabab: `0000123` soni `123`
    bo'lib qoladi; PLU va Код aynan shunday yo'qoladi.
  · Takror kalit — RAD. Noma'lum kalit — RAD (whitelist). Yangi maydon faqat sxema versiyasi
    oshganda qo'shiladi.
  · `VERIFIED` ni NOM MOSLIGI bera olmaydi. Ishonch darajasi dalil TURI bilan chegaralangan
    (`schema.py`): nom/sinonim/tip shakli — faqat `CANDIDATE`. `VERIFIED` uchun odam tasdig'i,
    arifmetik isbot, kontrakt mosligi yoki mustaqil manbalar kelishuvi SHART.
  · Yiqilgan bo'lim JIMGINA TUSHIRIB QOLDIRILMAYDI — u xatosi bilan birga to'plamda qoladi
    va umumiy holat `PARTIAL` yoki `BLOCKED` bo'ladi.
  · Sir topilsa — to'plam RAD (ulanish satri, parol, token, AnyDesk/RDP identifikatori).
"""

SCHEMA_VERSION = "binos-1c-discovery-v1"
CONTENT_HASH_LABEL = b"binos-1c-discovery-content-v1"

#: To'plam ichidagi majburiy fayllar (yo'qligi — RAD).
REQUIRED_MEMBERS = ("discovery.json", "metadata_sweep.json", "counts.json", "status.json", "summary.md")

#: Bitta a'zo fayl uchun yuqori chegara. Samplelar shu chegaradan kichik bo'lishi kerak.
MAX_MEMBER_BYTES = 64 * 1024 * 1024

#: Umumiy holatlar.
STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUSES = (STATUS_COMPLETE, STATUS_PARTIAL, STATUS_BLOCKED)
