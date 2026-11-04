# -*- coding: utf-8 -*-
"""NORMAL POS/mobil DTO'lari TARIXIY VAQT MAYDONI OLMASIN — muzlatilgan shartnoma.

NEGA BU FAYL BOR
================
Tarixiy bajarish (H1–H3b) ataylab shunday qurilgan: 12 kanonik yozuvchi
`at=` ni FAQAT kalit-so'zli SERVIS parametri sifatida oladi, marshrut
sxemasida esa vaqt maydoni YO'Q. Buni uch joyda yozib qo'yilgan
(`api/v1/cashops.py`, `api/v1/inventory.py`, `api/v1/shifts.py`): marshrut
funksiyasiga kwarg qo'shilsa FastAPI uni QUERY parametriga aylantiradi, ya'ni
oddiy kassir `?at=...` bilan tarixga yozardi.

Shartnoma manba bo'yicha o'z-o'zini himoya qilmaydi: kimdir «qulay bo'lsin»
deb `WriteoffIn`ga `at: datetime | None = None` qo'shsa, hech bir gard qizil
bo'lmaydi va teshik JIMGINA ochiladi. Shu fayl aynan shu regressiyani tutadi.

QAMROV — ICHMA-ICH MODELLARNI HAM
=================================
Faqat yuqori qatlamni muzlatish YETARLI EMAS: `SaleCreate.items` ichidagi
`SaleItemIn`ga `at` qo'shilsa ham tarixiy vaqt payloadga kirardi. Shu bois
11 ildiz DTO'dan rekursiv yurib, 20 modelning HAMMASI muzlatilgan.

⚠️  BU TEST YANGI ENDPOINTGA TEGISHLI EMAS. Yangi privileged tarixiy sirt
    (`POST /historical/events`) O'Z xususiy strict bazasiga ega va `occurred_at`
    ni O'Z envelopida oladi. Shu fayl aks tomonni — oddiy POS yo'li
    TEGILMAGANINI — isbotlaydi.
"""
import typing

import pytest
from pydantic import BaseModel

from app.api.v1.cashops import CashOpIn
from app.api.v1.inventory import CountIn, WriteoffIn
from app.api.v1.purchases import SupplierPaymentIn
from app.api.v1.receiving import CommitIn
from app.api.v1.shifts import CloseShift, OpenShift
from app.schemas.customer import CreditPayment
from app.schemas.purchase import PurchaseCreate
from app.schemas.sales import ReturnCreate, SaleCreate

#  12 hodisa turini 11 DTO qoplaydi (`cash_payin` va `cash_expense` bitta
#  `CashOpIn` ustida ishlaydi).
ILDIZLAR = [OpenShift, CloseShift, SaleCreate, ReturnCreate, PurchaseCreate,
            SupplierPaymentIn, CommitIn, CountIn, WriteoffIn, CashOpIn,
            CreditPayment]

#  ⚠️  O'LCHANGAN (pydantic 2.13.4, main=78e5fd07). Qiymatni «tuzatish» uchun
#      emas, O'ZGARISHNI ko'rish uchun muzlatilgan. Agar bu ro'yxat o'zgarsa —
#      normal POS kontrakti o'zgargan, demak qarorni EGA qabul qilishi kerak.
MUZLATILGAN: dict[str, list[str]] = {
    "CashOpIn": ["amount", "client_uuid", "destination_safe_id", "reason", "type"],
    "CloseShift": ["counted_cash"],
    "CommitIn": ["ai_raw", "cash_account_id", "client_uuid", "image_b64", "items",
                 "payment", "source", "supplier_id"],
    "CommitItem": ["ai_name", "lots", "new_barcode", "new_category_id",
                   "new_is_weighted", "new_min_qty", "new_name", "new_plu",
                   "new_sell_price", "product_id", "qty", "unit", "unit_cost"],
    "CountIn": ["branch_id", "client_uuid", "items"],
    "CountItem": ["counted", "lots", "new_lots", "product_id"],
    "CountLot": ["counted", "stock_batch_id"],
    "CountNewLot": ["batch_no", "expiry_date", "qty", "reason", "unit_cost"],
    "CreditPayment": ["amount", "cash_account_id", "client_uuid", "method"],
    "OpenShift": ["opening_cash", "terminal_id", "till_id"],
    "PaymentSplit": ["amount", "method"],
    "PurchaseCreate": ["cash_account_id", "client_uuid", "items", "status",
                       "supplier_id"],
    "PurchaseItemIn": ["product_id", "qty", "unit_cost"],
    "ReturnCreate": ["client_uuid", "items", "original_sale_id", "reason",
                     "refund_method", "restock"],
    "ReturnItemIn": ["product_id", "qty", "unit_price"],
    "SaleCreate": ["client_uuid", "customer_id", "discount_total", "expected_total",
                   "given_amount", "items", "payment_method", "payments",
                   "qr_txn_id", "sold_at", "terminal_id", "till_id"],
    "SaleItemIn": ["discount", "product_id", "qty", "unit_price"],
    "SupplierPaymentIn": ["amount", "cash_account_id", "client_uuid", "method"],
    #  ⚠️  `confirm_duplicate` — R6.8 P0-1 da QO'SHILDI (ega qarori bilan).
    #      VAQT MAYDONI EMAS va tarixiy yo'lga ta'sir qilmaydi: u FAQAT
    #      `_assert_no_recent_twin` darvozasini ochadi (so'nggi o'xshash
    #      chiqarish uchun operator tasdig'i). `_writeoff_once` uni `at=`
    #      bilan umuman bog'lamaydi, `/historical/events` esa o'z strict
    #      bazasiga ega. Darvozaning maqsadi SAQLANADI: ro'yxat hamon
    #      MUZLATILGAN, ya'ni keyingi har qanday o'zgarish yana QIZIL bo'ladi.
    "WriteoffIn": ["branch_id", "client_uuid", "confirm_duplicate", "lots",
                   "product_id", "qty", "reason"],
    "WriteoffLot": ["qty", "stock_batch_id"],
}

#  Vaqtga o'xshash maydon nomlari. Ataylab KENG: `_at`, `_date`, `timestamp`...
def _vaqtga_oxshaydimi(nom: str) -> bool:
    n = nom.lower()
    return (n == "at" or n.endswith("_at") or n.endswith("_date")
            or "timestamp" in n or "occurred" in n or "happened" in n
            or n in {"when", "ts", "moment", "instant"})


#  ⚠️  MA'LUM IKKI ISTISNO — har biriga SABAB yozilgan. Yangi istisno qo'shish
#      = kontraktni bo'shatish, shu bois sabab MAJBURIY (test tekshiradi).
KUTILGAN_VAQT_MAYDONLARI: dict[tuple[str, str], str] = {
    ("SaleCreate", "sold_at"):
        "ATAYLAB. Offline outbox uchun: `/sync/push` uni `_clamp_sold_at` bilan "
        "(+5min/-60kun) qisib `create_sale(at=...)` ga uzatadi (api/v1/sync.py:89). "
        "`POST /sales` esa uni O'QIMAYDI — kanonik sotuv yo'li `at=` bermaydi. "
        "DIQQAT: e'lon qilingan maydon bo'lgani uchun `extra=forbid` uni TUTMAYDI; "
        "yangi tarixiy endpoint uni `_ServerOwned` validatori bilan rad etadi.",
    ("CountNewLot", "expiry_date"):
        "BIZNES MA'LUMOTI, hodisa vaqti EMAS — partiya yaroqlilik muddati "
        "(Phase 4B: `expiry_date` birinchi kirimda muzlaydi). Sanoq qachon "
        "bajarilganiga aloqasi yo'q.",
}


def _rekursiv_modellar() -> dict[str, type[BaseModel]]:
    """11 ildizdan ichma-ich pydantic modellarini yig'adi."""
    topilgan: dict[str, type[BaseModel]] = {}

    def yur(M: type[BaseModel]) -> None:
        if M.__name__ in topilgan:
            return
        topilgan[M.__name__] = M
        for f in M.model_fields.values():
            #  `list[X] | None` kabi ichma-ich generiklarni ikki qatlam ochamiz.
            for t in [f.annotation, *typing.get_args(f.annotation)]:
                for t2 in [t, *typing.get_args(t)]:
                    if isinstance(t2, type) and issubclass(t2, BaseModel):
                        yur(t2)

    for R in ILDIZLAR:
        yur(R)
    return topilgan


MODELLAR = _rekursiv_modellar()


def test_QAMROV_rekursiv_royxat_TOLIQ():
    """Muzlatilgan ro'yxat aynan yetib boriladigan modellar to'plami bo'lsin.

    ⚠️  IKKI TOMONLAMA: yangi ichma-ich model qo'shilsa ham, eskisi olib
        tashlansa ham qizil bo'ladi. Aks holda qamrov bayonoti jimgina
        eskirardi — gard esa «hammasi muzlatilgan» deb ko'rinardi.
    """
    assert sorted(MODELLAR) == sorted(MUZLATILGAN), (
        f"yetib boriladigan modellar {sorted(MODELLAR)}, "
        f"ro'yxatda {sorted(MUZLATILGAN)}")


@pytest.mark.parametrize("nom", sorted(MUZLATILGAN))
def test_DTO_maydonlari_MUZLATILGAN(nom):
    """Har bir DTO maydon to'plami aynan o'lchangan holatda qolsin."""
    M = MODELLAR[nom]
    assert sorted(M.model_fields) == MUZLATILGAN[nom], (
        f"{nom} maydonlari o'zgardi: {sorted(M.model_fields)} "
        f"!= {MUZLATILGAN[nom]} — normal POS kontrakti o'zgargan")


@pytest.mark.parametrize("nom", sorted(MUZLATILGAN))
def test_YANGI_vaqt_maydoni_QOSHILMAGAN(nom):
    """Hech bir normal DTO'da ro'yxatdan tashqari vaqt maydoni paydo bo'lmasin.

    Bu `test_DTO_maydonlari_MUZLATILGAN` ustiga QO'SHIMCHA qatlam: u literalni
    yangilab qo'ygan odamni tutmaydi, bu esa yangilangan literalda ham vaqt
    maydonini ko'rsatadi va SABAB yozishni talab qiladi.
    """
    M = MODELLAR[nom]
    for maydon in sorted(M.model_fields):
        if not _vaqtga_oxshaydimi(maydon):
            continue
        sabab = KUTILGAN_VAQT_MAYDONLARI.get((nom, maydon))
        assert sabab, (
            f"{nom}.{maydon} — vaqtga o'xshash YANGI maydon. Normal POS/mobil "
            f"sxemasiga tarixiy vaqt QO'SHILMAYDI (H3b shartnomasi). Agar bu "
            f"haqiqatan biznes ma'lumoti bo'lsa, KUTILGAN_VAQT_MAYDONLARI ga "
            f"sabab bilan qo'shing.")
        assert sabab.strip(), f"{nom}.{maydon}: sababsiz istisno"


def test_ISTISNO_royxati_ESKIRMAGAN():
    """Istisno ro'yxatida mavjud bo'lmagan maydon qolmasin.

    Maydon olib tashlansa istisno ham ketishi SHART, aks holda ro'yxat
    kontraktni bo'shatgan holda jimgina qolardi.
    """
    for (nom, maydon) in KUTILGAN_VAQT_MAYDONLARI:
        assert nom in MODELLAR, f"istisno eskirgan: {nom} modeli yo'q"
        assert maydon in MODELLAR[nom].model_fields, (
            f"istisno eskirgan: {nom}.{maydon} maydoni yo'q")


def test_NEGATIV_NAZORAT_global_siyosat_OZGARMAGAN():
    """Normal DTO'lar hamon NOMA'LUM kalitni jimgina tashlaydi.

    ⚠️  BU — GUVOH TESTI, nuqsonni MAQTAMAYDI. Pydantic'ning standart
        `extra='ignore'` siyosati tufayli `POST /sales` ga `at=...` yuborilsa
        422 EMAS, 200 qaytadi va qiymat yo'qoladi (`model_extra is None`, ya'ni
        tiklanmaydi ham). Bu ALOHIDA follow-up auditining mavzusi.

        Shu test global siyosat SHU TASKDA o'zgarmaganini isbotlaydi: yangi
        tarixiy endpoint strictligi FAQAT o'z xususiy bazasida. Follow-up
        teshikni yopsa — shu testni O'SHA commit ataylab yangilashi kerak.

        NEGA global strictlik bu yerda QILINMAYDI: `api/v1/sync.py:48-54`
        `SaleCreate(**raw)` ni `except ValidationError -> ok:False` ichida
        bajaradi. `SaleCreate` strict bo'lsa, outbox payloadida bitta ortiqcha
        kalit bo'lgan offline klient sotuvi JIMGINA dead-letter bo'lardi —
        payload esa localStorage'da qolib abadiy qayta urinardi. Bu pul
        yo'qotish yo'li.
    """
    s = SaleCreate(
        items=[{"product_id": "00000000-0000-0000-0000-000000000001",
                "qty": 1, "price": 10}],
        payments=[{"method": "cash", "amount": 10}],
        at="2025-03-01T10:00:00Z",          # NOMA'LUM kalit
    )
    assert "at" not in s.model_dump(), "noma'lum kalit saqlanib qolgan"
    assert s.model_extra is None, (
        "model_extra paydo bo'lgan — `extra` siyosati o'zgargan")


def test_NEGATIV_NAZORAT_sold_at_ELON_QILINGAN_va_SAQLANADI():
    """`sold_at` noma'lum EMAS — parser uni SAQLAYDI.

    ⚠️  NEGA MUHIM. Bu `extra='forbid'`ning chegarasini yozib qo'yadi: forbid
        faqat NOMA'LUM kalitni to'sadi, E'LON QILINGAN maydonni emas. Shu
        sababli yangi tarixiy endpointda `extra='forbid'` YETARLI EMAS va
        server egalik qiladigan maydonlar (`client_uuid`, `sold_at`,
        `image_b64`, `ai_raw`) uchun ALOHIDA validator kerak.
    """
    s = SaleCreate(
        items=[{"product_id": "00000000-0000-0000-0000-000000000001",
                "qty": 1, "price": 10}],
        payments=[{"method": "cash", "amount": 10}],
        sold_at="2025-03-01T10:00:00Z",     # E'LON QILINGAN maydon
    )
    assert s.sold_at is not None, "e'lon qilingan maydon tashlab yuborilgan"
    assert s.model_dump()["sold_at"] is not None
