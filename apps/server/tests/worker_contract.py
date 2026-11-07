# -*- coding: utf-8 -*-
"""SINTETIK WORKER ↔ BACKEND KONTRAKTI — YAGONA MANBA.

Bu fayl `binos-synthetic-lab` worker'i (`demo/live/supermarket.py`)
backendga AYNAN nima yuborishini va javobdan NIMA O'QISHINI e'lon qiladi.
`tests/test_worker_contract.py` uni har CI yurishida JONLI ilovaga qarshi
tekshiradi.

NEGA KERAK (o'lchangan nuqson, 2026-11-07)
──────────────────────────────────────────
Worker `6ef666bb` relizida mavjud BO'LMAGAN maydonga tayangan edi:
`POST /shifts/{id}/close` ga `count_source="SIMULATED"` yuborib, javobda
uni TEKSHIRARDI. Lekin `count_source` `6ef666bb` ning BUTUN repo'sida
0 fayl (`main` da ham yo'q — faqat `7ac/simulated-cash-count` shoxida),
`CloseShift` sxemasida esa faqat `counted_cash` bor. Pydantic standarti
`extra="ignore"` maydonni JIM tashlab 200 qaytaradi — ya'ni worker har
kun oxirida smenani YOPA OLMASDI va bu FAQAT deploydan keyin, kun
oxirida ma'lum bo'lardi.

⚠️  BU DARVOZA O'SHA SINFNI RELIZDAN OLDIN USHLAYDI.

QOIDALAR
────────
* `required` — server MAJBURIY deb e'lon qilgan maydon workerning
  payloadida BO'LISHI shart (aks holda worker 422 oladi).
* `sends` — worker YUBORADIGAN maydonlar. Har biri server sxemasida
  E'LON QILINGAN bo'lishi shart; aks holda Pydantic uni JIM tashlaydi.
  Ataylab e'tiborsiz qoldiriladigan maydon `ignored_ok` ga yoziladi va
  SABABI izohlanadi.
* `reads` — worker javobdan O'QIYDIGAN maydonlar. Ular javob sxemasida
  bo'lishi shart.
* `roundtrip` — worker javobda AYNI qiymatni kutadigan maydonlar
  (fail-closed tekshiruvi). Bu eng qattiq talab.

⚠️  YANGILASH TARTIBI: worker payloadi o'zgarsa SHU FAYL yangilanadi va
    CI yangi kontraktni tekshiradi. Lab repo'sidagi
    `ops/contract_probe.py` shu faylni O'QIYDI (backend yo'li berilsa),
    ya'ni ikki nusxa ORASIDA DRIFT BO'LMAYDI.
"""

#: Worker'ning POST marshrutlari. `{...}` — yo'l parametri (nomi
#: serverda boshqacha bo'lishi mumkin, naqsh bo'yicha mos keladi).
WORKER_POSTS: tuple[dict, ...] = (
    {
        "key": "login",
        "path": "/auth/login/password",
        "sends": ("phone", "password"),
        "reads": ("access_token",),
        "critical": True,
        "note": "har aktor o'z tokeni bilan ishlaydi (eng kam imtiyoz)",
    },
    {
        "key": "shift_open",
        "path": "/shifts/open",
        "sends": ("opening_cash", "till_id"),
        "reads": ("id",),
        "critical": True,
        "note": "`client_uuid` ATAYLAB yuborilmaydi (shifts.py — smena "
                "ochish daftariga tushmaydi)",
    },
    {
        "key": "sale",
        "path": "/sales",
        "sends": ("items", "payment_method", "discount_total", "expected_total",
                  "till_id", "given_amount", "customer_id", "client_uuid"),
        "reads": ("id",),
        "critical": True,
        "note": "`client_uuid` — idempotentlik kaliti, `ux_sales_company_"
                "client_uuid` unique indeksi bilan majburlanadi",
    },
    {
        "key": "shift_cash",
        "path": "/shifts/{shift}/cash",
        "sends": ("type", "amount", "reason", "client_uuid"),
        "reads": ("id",),
        "critical": True,
        "note": "payin / expense; inkassa shu marshrut orqali",
    },
    {
        "key": "shift_close",
        "path": "/shifts/{shift}/close",
        "sends": ("counted_cash",),
        "reads": ("expected_cash", "counted_cash", "difference"),
        "critical": True,
        #  ⚠️  `count_source`/`attestation_ref` ATAYLAB YO'Q — ular
        #      `6ef666bb` da mavjud EMAS. Agar backend 7AC shartnomasini
        #      qabul qilsa, SHU YERGA qo'shiladi va `roundtrip` ga
        #      kiritiladi; shundan KEYINGINA worker ularni yuborishi
        #      mumkin. Tartib teskari bo'lsa (avval worker) — aynan
        #      2026-11-07 da topilgan nuqson takrorlanadi.
        "note": "AVVAL SERVER, KEYIN KLIENT: `count_source` qo'shilsa "
                "birinchi shu faylga yoziladi",
    },
    {
        "key": "return",
        "path": "/returns",
        "sends": ("original_sale_id", "reason", "client_uuid", "items"),
        "reads": ("id",),
        "critical": True,
    },
    {
        "key": "customer_payment",
        "path": "/customers/{customer}/payments",
        "sends": ("amount", "method", "client_uuid"),
        "reads": (),
        "critical": False,
        "note": "worker javobdagi `id` ni MAJBURIY deb bilmaydi "
                "(`(javob or {}).get('id') or None`)",
    },
    {
        "key": "supplier_payment",
        "path": "/suppliers/{supplier}/payments",
        "sends": ("amount", "method", "client_uuid"),
        "reads": (),
        "critical": False,
    },
    {
        "key": "inventory_writeoff",
        "path": "/inventory/writeoff",
        "sends": ("product_id", "qty", "reason", "client_uuid"),
        "reads": (),
        "critical": False,
    },
    {
        "key": "inventory_count",
        "path": "/inventory/count",
        "sends": ("items", "client_uuid"),
        "reads": (),
        "critical": False,
    },
    {
        "key": "purchase",
        "path": "/purchases",
        "sends": ("supplier_id", "status", "items", "client_uuid"),
        "reads": (),
        "critical": False,
    },
)

#: Worker TAYANADIGAN GET marshrutlari (darvozalar va surat).
WORKER_GETS: tuple[dict, ...] = (
    {"key": "health", "path": "/health",
     "reads": ("build", "api"), "critical": True},
    {"key": "auth_context", "path": "/auth/context",
     "reads": ("company", "actor_branch", "employee", "permissions"),
     "critical": True},
    {"key": "cash_setup", "path": "/cash-setup",
     "reads": ("ledger_native", "branches"), "critical": True},
    {"key": "tills", "path": "/tills", "reads": (), "critical": True},
    {"key": "offline_policy", "path": "/shifts/offline-sale-policy",
     "reads": ("mode", "reason"), "critical": True},
    {"key": "shift_current", "path": "/shifts/current",
     "reads": (), "critical": True},
    {"key": "shift_summary", "path": "/shifts/{shift}/summary",
     "reads": ("expected",), "critical": True},
    {"key": "products", "path": "/products", "reads": (), "critical": True},
    {"key": "customers", "path": "/customers", "reads": (), "critical": True},
    {"key": "suppliers", "path": "/suppliers", "reads": (), "critical": True},
    {"key": "shifts_overview", "path": "/shifts/overview",
     "reads": ("shifts",), "critical": False},
)

#: ⚠️  SO'ROV SXEMASI XOSSASIZ marshrutlar (erkin tana). Hozir BO'SH.
#:     Jim skip EMAS: `test_yuborilgan_maydon_SXEMADA_ELON_QILINGAN`
#:     xossasiz sxemani shu ro'yxatda TALAB qiladi, aks holda QIZIL.
#:     Erkin tanali marshrutga worker yuborgan HAR maydon jimgina
#:     qabul qilinadi va `count_source` sinfidagi nuqson TEKSHIRILMAY
#:     qoladi — shu bois u ANIQ qayd etilishi kerak.
REQUEST_SCHEMA_FREEFORM: dict[str, str] = {}

#: Worker yuboradigan, lekin server ATAYLAB e'tiborsiz qoldiradigan
#: maydonlar. HAR BIRI SABAB bilan. Bo'sh ro'yxat — eng xavfsiz holat.
IGNORED_OK: dict[str, str] = {}

#: ⚠️  JAVOB SXEMASI E'LON QILINMAGAN marshrutlar — O'LCHANGAN KAMCHILIK,
#:     jim skip EMAS. Bu yo'llarda FastAPI javob modelini e'lon qilmaydi,
#:     ya'ni worker O'QIYDIGAN maydonlarni STATIK tekshirib bo'lmaydi.
#:
#: ⚠️  TO'RTTASI HAM KRITIK va hammasi smena/naqd yo'lida — ya'ni eng
#:     qimmat joyda eng kuchsiz shartnoma. Ular `None` javob modeli bilan
#:     ketgani uchun `count_source` sinfidagi nuqson JAVOB tomonida
#:     USHLANMAYDI (so'rov tomonida ushlanadi).
#:
#: ⚠️  RO'YXAT QULFLANGAN: `test_javob_sxemasi_ELON_QILINMAGANLAR_ANIQ`
#:     ro'yxat AYNAN haqiqatga mos ekanini tekshiradi. Yangi marshrut
#:     sxemasiz qo'shilsa test QIZIL bo'ladi; mavjud marshrutga sxema
#:     qo'shilsa ham QIZIL (ro'yxatdan olib tashlash kerak). Shu bois
#:     ro'yxat «abadiy istisno» bo'lib qolmaydi.
#:
#: KEYINGI ISH (Phase 9 rejasi): bu to'rt marshrutga `response_model`
#: e'lon qilish. Alohida o'zgarish — ko'p endpointga tegadi va reliz
#: xavfi alohida baholanishi kerak.
RESPONSE_SCHEMA_UNDECLARED: dict[str, str] = {
    #  ── worker JAVOBDAN O'QIYDIGAN marshrutlar (XAVF YUQORI) ───────────
    "shift_open": "POST /shifts/open — `response_model` yo'q; worker `id` "
                  "O'QIYDI (smena id'si shundan olinadi)",
    "shift_cash": "POST /shifts/{id}/cash — `response_model` yo'q; worker "
                  "`id` o'qiydi (inkassa natijasi)",
    "shift_close": "POST /shifts/{id}/close — `response_model` yo'q; worker "
                   "`expected_cash`/`counted_cash`/`difference` O'QIYDI. "
                   "ENG KRITIK: javob tomonidagi shartnoma statik "
                   "tekshirilmaydi",
    "return": "POST /returns — `response_model` yo'q; worker `id` o'qiydi",
    #  ── worker javobni MAJBURIY deb BILMAYDIGAN marshrutlar (xavf past) ─
    #  ⚠️  Bular ilgari UMUMAN tekshirilmagan edi: eski test faqat
    #      `reads` bo'sh BO'LMAGAN marshrutlar uchun ishlardi, ya'ni
    #      `reads: ()` bo'lgan to'rtta marshrut jim o'tib ketardi.
    #      Qulflangan ro'yxat shuni ochdi.
    "customer_payment": "POST /customers/{id}/payments — `response_model` yo'q; "
                        "worker `id` ni MAJBURIY deb bilmaydi",
    "supplier_payment": "POST /suppliers/{id}/payments — `response_model` yo'q; "
                        "worker `id` ni majburiy deb bilmaydi",
    "inventory_writeoff": "POST /inventory/writeoff — `response_model` yo'q",
    "inventory_count": "POST /inventory/count — `response_model` yo'q",
}

#: O'LCHANGAN HOLAT (2026-11-07): 11 worker POST marshrutidan 8 tasida
#: javob modeli E'LON QILINMAGAN. Bu son faqat KAMAYISHI kerak —
#: `test_javob_modeli_qamrovi_YOMONLASHMAYDI` shuni qulflaydi.
RESPONSE_SCHEMA_UNDECLARED_MAX = 8

#: Worker TAYANADIGAN qobiliyat nomlari (`/health.api.features`).
#: `release.DEFAULT_REQUIRED_FEATURES` bilan AYNI bo'lishi shart.
REQUIRED_FEATURES: tuple[str, ...] = ("auth_context", "offline_sale_policy")
REQUIRED_API_LEVEL: int = 2
