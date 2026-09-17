# -*- coding: utf-8 -*-
"""BARQAROR XATO KODLARI — partiya yo'lidagi ichki nomuvofiqliklar.

NEGA KOD MATNGA QO'SHILMAYDI
============================
`detail` — operatorga ko'rsatiladigan MATN va ayni paytda tarjima lug'atining
KALITI (`packages/shared/src/lib/serverErrorsLots.ts`). «LOT_...: matn» prefiksi
o'rnatilgan eski POS/Manager'da kod tokenini ekranga chiqarardi va lug'at
qidiruvini buzardi. Shu bois kod QO'SHIMCHA va MATNDAN TASHQARIDA yuradi:

  · javob sarlavhasi `X-Error-Code` (`main.py` CORS `expose_headers` da ochilgan —
    aks holda Electron renderer uni o'qiy olmasdi);
  · `/sync/push` natijasidagi `code` maydoni;
  · server jurnali — har doim.

⚠️  KOD QIYMATI O'ZGARMAYDI: mijoz va qo'llab-quvvatlash unga tayanadi. Yangi
    holat — yangi konstanta; eskisini qayta nomlash EMAS.

⚠️  HTTP HOLATI KODDAN KELIB CHIQMAYDI. Bu yerdagi hamma holat 409 bo'lib
    qoladi: `/sync/push` 409 ni TRANZIENT deb biladi (pul olingan offline chek
    outbox'da qoladi), POS esa sotuvdagi 409 da katalogni yangilaydi.
"""

HEADER = "X-Error-Code"

# Partiya/qoldiq YAKUNIY DARVOZASI buzildi: sotuv, hisobdan chiqarish, sanoq,
# kuzatuvni yoqish, kirim, qaytarish.
LOT_INVARIANT_BROKEN = "LOT_INVARIANT_BROKEN"
# Qaytarish yozgan qatorlar partiya/qarz chegarasidan oshardi (`lot_return.assert_caps`).
LOT_RETURN_CAPS_VIOLATED = "LOT_RETURN_CAPS_VIOLATED"
# Qaytarish rejasida taxminiy partiya ulushi aniq summadan katta — DASTURIY invariant.
LOT_COST_BASIS_INCONSISTENT = "LOT_COST_BASIS_INCONSISTENT"
# Chek partiya kuzatuvi YOQILISHIDAN OLDIN sotilgan — omborga qaytarish (restock) rad
# etildi (`lot_return.pre_activation_line`). Restock'siz qaytarish RUXSAT etiladi.
LOT_RETURN_PRE_ACTIVATION = "LOT_RETURN_PRE_ACTIVATION"
# Qarzni yopishning yakuniy darvozasi buzildi.
LOT_RESOLVE_INVARIANT_BROKEN = "LOT_RESOLVE_INVARIANT_BROKEN"
# Kuzatuvni yoqish darvozasi: BAZA sxemasi tayyor emas (yaxlitlik, idempotentlik
# indekslari yoki uuid ustun tipi). Ma'lumot BUZILMAGAN — yangi partiya tarixi
# shunchaki tug'ilmaydi; operator `/health/ready` ni yashil qilgach qayta uradi.
LOT_SCHEMA_NOT_READY = "LOT_SCHEMA_NOT_READY"


def headers(code: str) -> dict:
    """`HTTPException(409, "<matn>", headers=headers(KOD))` uchun."""
    return {HEADER: code}
