# -*- coding: utf-8 -*-
"""`POST /historical/events` — DARVOZALAR: allowlist, strict DTO, muhit, doira.

Bu fayl sirtning «nima QILA OLMAYDI» tomonini qoplaydi. Semantik tomon
(`test_historical_http.py`) va jurnal/halokat (`test_historical_http_journal.py`)
alohida.
"""
import uuid
from datetime import timedelta

import pytest

from tests._hist_scene import D0, NOW, env, post, sahna, yozuv_yoq


# ══ 1. «IXTIYORIY FUNKSIYA CHAQIRUVCHISI» EMAS ═══════════════════════════
#  Allowlist = union'ning `Literal` teglar to'plami; uni PARSER majburlaydi,
#  ya'ni rad etish yozuvchiga YETIB BORMASDAN, biznes kodidan OLDIN bo'ladi.

def test_NOMALUM_hodisa_turi_PARSERDA_rad(client):
    s = sahna()
    r = post(client, env(s, event_type="delete_everything", payload={}))
    assert r.status_code == 422, r.text
    assert any(e.get("type") == "union_tag_invalid"
               for e in r.json()["detail"]), r.text
    #  Kutilgan teglar xato matnida ko'rinsin (operator uchun).
    assert "shift_open" in r.text and "supplier_payment" in r.text


def test_TEG_umuman_yoq_rad(client):
    s = sahna()
    e = env(s, event_type="sale", payload={})
    del e["event"]["event_type"]
    r = post(client, e)
    assert r.status_code == 422
    assert any(x.get("type") == "union_tag_not_found"
               for x in r.json()["detail"]), r.text


def test_BOSHQA_hodisaning_maydoni_rad(client):
    """Discriminator variantni maydon validatsiyasidan OLDIN qadaydi."""
    s = sahna()
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 100, "qty": 5}))
    assert r.status_code == 422
    e = r.json()["detail"][0]
    assert e["type"] == "extra_forbidden" and "qty" in e["loc"], e


def test_KASSA_YIGISH_allowlistda_YOQ(client):
    """`cash_payin` orqali `type='collection'` o'tib ketmasin.

    ⚠️  `CashOpIn.type` asli `Literal["payin","expense","collection"]`. Yig'ish
        ATAYLAB allowlist'dan tashqarida: uning tiklanish guvohi FAQAT
        Postgres'dagi cash sxemasida yashaydi va «aniqlay olmadim» javobini
        beradi, ya'ni halokatdan keyin tiklanishi isbotlanmagan bo'lardi.
        Variant `type` ni QAYTA e'lon qilib uchinchi qiymatni yo'q qiladi.
    """
    s = sahna()
    r = post(client, env(s, event_type="cash_payin",
                         payload={"type": "collection", "amount": 500}))
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "literal_error", r.text


def test_TEGLAR_TOPLAMI_aynan_12_va_HAR_BIRIDA_ZOND_bor():
    """Allowlist muzlatilgan va har bir hodisaning tiklanish zondi BOR.

    ⚠️  IKKINCHI shart birinchisidan muhimroq: zondsiz hodisa turi
        halokatdan keyin `started` holatida ABADIY osilib qolardi — bu esa
        ega ataylab taqiqlagan holat.
    """
    from app.api.v1 import historical_exec as hx
    from app.services import historical_recovery as hr
    kutilgan = {"shift_open", "shift_close", "sale", "purchase", "receiving",
                "return", "inventory_count", "writeoff", "cash_payin",
                "cash_expense", "customer_debt_payment", "supplier_payment"}
    teglar = set()
    for v in hx.Event.__origin__.__args__:
        teglar |= set(v.model_fields["event_type"].annotation.__args__)
    assert teglar == kutilgan, teglar ^ kutilgan
    assert set(hr.PROBES) == kutilgan, set(hr.PROBES) ^ kutilgan
    assert set(hx.EVENT_TYPES) == kutilgan


def test_historical_enter_FAQAT_shu_moduldan_chaqiriladi():
    """`historical.enter(...)` ning yagona production chaqiruvchisi.

    ⚠️  NEGA. Agar boshqa marshrut ham kontekst ocha boshlasa, tarixiy
        qobiliyat normal POS yo'liga JIMGINA kirib kelardi — ega qat'iy
        taqiqlagan narsa. Registr emas, MANBA bo'yicha tekshiriladi.
    """
    import pathlib
    import re
    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    naqsh = re.compile(r"(?<![\w.])(?:_H|historical)\.enter\s*\(")
    topilgan = set()
    for f in app_dir.rglob("*.py"):
        if naqsh.search(f.read_text(encoding="utf-8")):
            topilgan.add(f.relative_to(app_dir).as_posix())
    #  `services/historical.py` — ta'rifning o'zi (docstringda misollar bor).
    topilgan.discard("services/historical.py")
    assert topilgan == {"api/v1/historical_exec.py"}, topilgan


# ══ 2. STRICT DTO — ORTIQCHA VA SERVER-EGALIK MAYDONLARI ════════════════

def test_ENVELOPE_ortiqcha_kalit_rad(client):
    s = sahna()
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, qandaydir_kalit="x"))
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "extra_forbidden", r.text


def test_PAYLOAD_ortiqcha_kalit_rad(client):
    s = sahna()
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0, "at": D0.isoformat()}))
    assert r.status_code == 422
    e = r.json()["detail"][0]
    assert e["type"] == "extra_forbidden" and "at" in e["loc"], e


@pytest.mark.parametrize("maydon,turi,payload", [
    ("client_uuid", "sale",
     {"items": [], "payments": [],
      "client_uuid": "11111111-1111-1111-1111-111111111111"}),
    ("sold_at", "sale",
     {"items": [], "payments": [], "sold_at": "2025-01-01T00:00:00Z"}),
    ("image_b64", "receiving", {"items": [], "image_b64": "AAA"}),
    ("ai_raw", "receiving", {"items": [], "ai_raw": []}),
])
def test_SERVER_EGALIK_maydoni_rad(client, maydon, turi, payload):
    """⚠️  `extra="forbid"` BULARNI TUTMAYDI — ular E'LON QILINGAN maydonlar.

    O'lchangan: strict voris `sold_at` ni SAQLAB qoladi. Shu bois alohida
    validator kerak. `client_uuid` ni FAQAT server qo'yadi (u `event_key`),
    vaqtni esa FAQAT `occurred_at` beradi — aks holda mijoz idempotentlik
    kalitini yoki vaqt muhrini boshqarardi.
    """
    s = sahna()
    r = post(client, env(s, event_type=turi, payload=payload))
    assert r.status_code == 422, r.text
    assert maydon in r.text, r.text
    #  Barqaror `type` — matn o'zgarsa ham test ma'nosini saqlaydi.
    assert any(e.get("type") == "server_owned_field"
               for e in r.json()["detail"]), r.json()["detail"]


def test_OCCURRED_AT_kelajakda_rad(client):
    """Tarixiy bajarish ATAYLAB o'tmishga yozadi (5 daqiqa tolerantlik)."""
    s = sahna()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0},
                         at=NOW + timedelta(hours=2)))
    assert r.status_code == 400 and "KELAJAK" in r.text.upper(), r.text


def test_PLAN_ID_bosh_rad(client):
    s = sahna()
    e = env(s, event_type="shift_open", payload={"opening_cash": 0})
    e["plan_id"] = ""
    r = post(client, e)
    assert r.status_code == 422, r.text          # envelope `min_length=1`


def test_EVENT_SEQ_bosh_rad(client):
    s = sahna()
    e = env(s, event_type="shift_open", payload={"opening_cash": 0})
    e["event_seq"] = []
    assert post(client, e).status_code == 422


# ══ 3. MUHIT — «PRODUCTION'GA TEGILMAYDI» AYNAN SHU DARVOZA ═════════════

def test_APP_ENV_yoq_bolsa_RAD(client, monkeypatch):
    """⚠️  O'zgaruvchi YO'QLIGI ruxsat BERMAYDI.

    `environment_name()` `"unknown"` qaytaradi va u allowlist'da yo'q. Bu
    muhim, chunki «productionga tegmaslik»ni `require_vendor` BERMAYDI —
    vendor sessiyasi production'da ham amal qiladi. Darvoza `is_production`
    ga ham bog'liq emas.
    """
    monkeypatch.delenv("APP_ENV", raising=False)
    s = sahna()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 403 and "unknown" in r.text, r.text
    yozuv_yoq(s["cid"])


@pytest.mark.parametrize("nom,qiymat,kutilgan", [
    #  Muhit allowlist'i — MENING darvozam.
    ("APP_ENV", "production", 403),
    #  ⚠️  O'LCHANGAN: platforma production deb signal bersa, so'rov MENING
    #      darvozamga YETIB ham bormaydi — `require_vendor` xom master kalitni
    #      rad etadi (`admin.py:278-282`: xom kalit faqat `not is_production`
    #      va 2FA o'chiq bo'lganda qabul qilinadi). Ya'ni production'da IKKI
    #      MUSTAQIL qatlam to'sadi. Bu kutilmani ataylab 403 deb yozib
    #      qo'ymaymiz: 401 haqiqiy xulq va u KUCHLIROQ.
    ("RAILWAY_ENVIRONMENT_NAME", "production", 401),
])
def test_PRODUCTION_signali_RAD(client, monkeypatch, nom, qiymat, kutilgan):
    monkeypatch.setenv(nom, qiymat)
    if nom == "RAILWAY_ENVIRONMENT_NAME":
        monkeypatch.setenv("APP_ENV", "staging")      # muhitning o'zi ruxsatli
    s = sahna()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == kutilgan, r.text
    yozuv_yoq(s["cid"])


# ══ 4. DO'KON DOIRASI ═══════════════════════════════════════════════════

def test_JONLI_dokon_RAD(client):
    s = sahna(code_prefix="fayzan")
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 400 and "demo" in r.text, r.text
    yozuv_yoq(s["cid"])


def test_BOSHIDAGI_BOSHLIQ_kodi_RAD(client):
    """`" test1"` — bo'shliq bilan. ⚠️  `is_demo_code` da `strip()` ATAYLAB YO'Q.

    Predikat `api/v1/admin.py` dagi mavjud darvoza bilan BAYT-AYNAN bo'lishi
    shart; bo'shliqni «tozalash» niyatida kesish uni BO'SHATARDI.
    """
    from app.models.org import Company
    from tests._hist_scene import db_
    s = sahna()
    with db_() as db:
        db.get(Company, uuid.UUID(s["cid"])).code = " test1-" + uuid.uuid4().hex[:6]
        db.commit()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 400, r.text


def test_MAVJUD_BOLMAGAN_dokon_404(client):
    s = sahna()
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 0})).status_code == 200   # nazorat
    s2 = dict(s, cid=str(uuid.uuid4()))
    r = post(client, env(s2, event_type="shift_open",
                         payload={"opening_cash": 0}, seq=["x"]))
    assert r.status_code == 404, r.text


def test_PLAN_START_savdosi_BOR_dokonda_409(client):
    s = sahna()
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 0}, seq=["o"])).status_code == 200
    assert post(client, env(
        s, event_type="sale", at=D0 + timedelta(hours=1), seq=["s1"],
        payload={"items": [{"product_id": s["pid"], "qty": 1, "price": 100}],
                 "payments": [{"method": "cash", "amount": 100}]})).status_code == 200
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0},
                         seq=["o2"], plan_start=True))
    assert r.status_code == 409 and "savdo" in r.text, r.text


def test_KASSA_T0_belgilangan_dokon_409(client, monkeypatch):
    """⚠️  T0 qo'yilgan tenantda tarixiy yozuv RAD — darvoza CHETLAB O'TILMAYDI.

    Sabab arxitekturaviy: T0 belgilangan tenantda yopilgan tarixiy smenaga
    naqd yozish ATAYLAB taqiqlangan (anti-abuse). Biz uni bo'shatmaymiz,
    balki T0 qo'yilMAGAN tenantni TALAB qilamiz.

    SQLite'da cash sxemasi yo'q, shu bois bu yerda darvozaning SIMLANGANI
    o'lchanadi; real T0 bilan Postgres testi alohida.
    """
    from app.services.cash import cutover as _cut
    monkeypatch.setattr(_cut, "cutover_at", lambda db, cid: D0)
    s = sahna()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 409 and "T0" in r.text, r.text
    yozuv_yoq(s["cid"])


# ══ 5. FILIAL / AKTOR — FAIL-CLOSED, MUTATSIYADAN OLDIN ═════════════════

@pytest.mark.parametrize("nima", ["boshqa_dokon", "ochirilgan", "nofaol"])
def test_FILIAL_fail_closed(client, nima):
    from app.models.org import Branch
    from tests._hist_scene import db_
    s = sahna()
    bid = s["a"]
    if nima == "boshqa_dokon":
        bid = sahna()["a"]
    else:
        with db_() as db:
            br = db.get(Branch, uuid.UUID(bid))
            if nima == "ochirilgan":
                br.deleted_at = NOW
            else:
                br.is_active = False
            db.commit()
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, branch=bid))
    assert r.status_code == 400, r.text
    yozuv_yoq(s["cid"])


def test_BOSHQA_DOKON_filiali_MAVJUDLIGINI_oshkor_qilmaydi(client):
    """IDOR: javob boshqa ijarachining identifikatorini qaytarmasin."""
    s1, s2 = sahna(), sahna()
    r = post(client, env(s1, event_type="shift_open",
                         payload={"opening_cash": 0}, branch=s2["a"]))
    assert r.status_code == 400
    assert s2["a"] not in r.text and s2["code"] not in r.text, r.text


def test_AKTOR_biriktirilmagan_FILIAL_rad(client):
    """7-DARVOZA: `actor_branch` TENGLIGI.

    ⚠️  NEGA MAVJUDLIK YETMAYDI. O'n yozuvchi filialni `emp` dan
        `actor_branch` orqali oladi, u esa UCH bosqichli va 2-3 bosqichi
        FAIL-OPEN: biriktirilmagan xodimga do'konning birinchi faol filialini,
        oxirgi chorada hatto NOFAOL filialni beradi (`core/deps.py:65-81`).
        Ya'ni envelopdagi `branch_id` ni tekshirmasdan ishonib bo'lmaydi —
        hodisa jimgina boshqa filialga tushardi.
    """
    s = sahna()
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, branch=s["b"]))
    assert r.status_code == 400 and "biriktirilmagan" in r.text, r.text
    yozuv_yoq(s["cid"])


@pytest.mark.parametrize("turi", ["shift_open", "sale"])
def test_BOSHQA_dokon_aktori_rad(client, turi):
    """⚠️  `sale` ALOHIDA sinaladi va bu YUK KO'TARUVCHI.

    `services/sales.py` `historical` ni UMUMAN import qilmaydi (`now = at or
    _now()`), ya'ni kontekst ichida bo'lish `create_sale` da HECH NARSANI
    tekshirmaydi: u aktorning do'konini ham, lahzani ham gate qilmaydi. Shu
    hodisa uchun endpointning o'z darvozalari YAGONA himoya — «qo'shimcha
    qatlam» emas. Kim bu ikki qatorni «soddalashtirsa», 60 kundan chuqur
    orqaga sanash yo'li ochilib ketadi.
    """
    s1, s2 = sahna(), sahna()
    payload = ({"opening_cash": 0} if turi == "shift_open" else
               {"items": [{"product_id": s1["pid"], "qty": 1, "price": 100}],
                "payments": [{"method": "cash", "amount": 100}]})
    r = post(client, env(s1, event_type=turi, payload=payload, actor=s2["eid"]))
    assert r.status_code == 400 and "BOSHQA do'kon" in r.text, r.text
    yozuv_yoq(s1["cid"])
    yozuv_yoq(s2["cid"])


def test_RUXSATSIZ_aktor_rad(client):
    """Aktorda `kassa.sell` bo'lmasa — rad. Bu ATRIBUTSIYA gardi."""
    from app.models.auth import Employee, Role
    from tests._hist_scene import db_
    s = sahna()
    with db_() as db:
        e = db.get(Employee, uuid.UUID(s["eid"]))
        e.role_id = db.query(Role).filter(Role.code == "omborchi").one().id
        db.commit()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}))
    assert r.status_code == 400 and "ruxsat yetishmaydi" in r.text, r.text
    yozuv_yoq(s["cid"])


def test_XODIM_tokeni_rad_va_JURNAL_ham_BOSH(client, admin_headers):
    """Oddiy xodim token'i tarixni qayta yoza olmaydi — ega invarianti."""
    from app.models.historical import HistoricalPlanEvent as HPE
    from tests._hist_scene import db_
    s = sahna()
    r = post(client, env(s, event_type="shift_open", payload={"opening_cash": 0}),
             headers=admin_headers)
    assert r.status_code == 401, r.text
    yozuv_yoq(s["cid"])
    with db_() as db:
        assert db.query(HPE.id).filter(
            HPE.company_id == uuid.UUID(s["cid"])).first() is None
