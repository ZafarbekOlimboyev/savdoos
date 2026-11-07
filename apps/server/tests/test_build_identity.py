# -*- coding: utf-8 -*-
"""RELIZ IDENTITETI — artefakt O'Z commitini aytishi (Phase 9).

⚠️  NEGA. Jonli insident (2026-11-06/07): `build_info()` commit SHA'ni FAQAT
    muhit o'zgaruvchisidan olardi. Nazoratli tajriba isbotladi — Railway git
    o'zgaruvchilarini `deploy`/`redeploy` da BERADI, `rollback` da BERMAYDI
    (`binos-demo-api` reason=deploy -> commit BOR; `savdoos` reason=rollback
    -> `null`). Natijada production AYNAN kutilgan relizga (`6ef666bb`)
    qaytarilgan bo'lsa ham ilova o'z commitini AYTA OLMADI, demo worker'ning
    SHA darvozasi YOLG'ON yiqildi va do'kon 22,8 soat muzladi.

BU FAYL MAHKAMLAYDIGAN INVARIANTLAR
───────────────────────────────────
 1. Digest DETERMINISTIK va QATOR OXIRIGA BOG'LIQ EMAS (CRLF tuzog'i shu
    loyihada O'LCHANGAN).
 2. Digest kodning HAR QANDAY mazmunli o'zgarishini ko'radi (bayt, nom,
    fayllar o'rni almashishi).
 3. Muhrning O'ZI digestga KIRMAYDI — aks holda «o'z digestini o'z ichiga
    yozish» aylanmasi imkonsiz bo'lardi.
 4. ROLLBACK SENARIYSI: muhit o'zgaruvchilari YO'Q bo'lsa ham commit
    E'LON QILINADI (muhr artefakt ichida).
 5. ESKIRGAN O'ZGARUVCHI E'TIBORGA OLINMAYDI: muhr undan USTUN.
 6. MUHR MOS KELMASA — `commit` AYTILMAYDI (taxmin yo'q, fail-closed).
 7. Muhrsiz artefakt uchun orqaga moslik, lekin ishonch darajasi ANIQ
    (`ENV_ONLY`), ya'ni iste'molchi farqni ko'radi.
 8. BIR XIL API BARMOQ IZI BIR XIL KODNI ISBOTLAMAYDI — o'lchangan
    dalil: 192 marshrutli sirt `6ef666bb`, otasi `3f76b62e` va
    `2457b98a` uchun AYNAN bir xil.
 9. `/health` ARZON qoladi va OCHIQ endpointda fayl yo'li oshkor
    bo'lmaydi.
"""
import json
import pathlib

import pytest

from app.core import api_capabilities, build_identity as B


# ── yordamchi: izolyatsiyalangan soxta manba daraxti ────────────────────────
def tree(tmp_path: pathlib.Path, files: dict[str, bytes]) -> pathlib.Path:
    """`apps/server` ga o'xshash minimal daraxt yasaydi."""
    root = tmp_path / "srv"
    for nisbiy, xom in files.items():
        p = root / nisbiy
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(xom)
    return root


BAZA = {
    "app/__init__.py": b"",
    "app/main.py": b"X = 1\n",
    "app/core/a.py": b"def f():\n    return 1\n",
    "app/db/cash/x.sql": b"create table t(id int);\n",
}


# ════════════════════════════════════════════════════════════════════════
#  1. DIGEST — determinizm va sezgirlik
# ════════════════════════════════════════════════════════════════════════
class TestDigest:

    def test_deterministik(self, tmp_path):
        r = tree(tmp_path, BAZA)
        assert B.compute_source_digest(r) == B.compute_source_digest(r)

    def test_qator_oxiri_AHAMIYATSIZ(self, tmp_path):
        """CRLF va LF AYNI digest berishi SHART.

        ⚠️  O'LCHANGAN TUZOQ: `core.autocrlf=true` bo'lgan Windows
            checkout'ida fayllar CRLF bilan yoziladi (shu repoda
            `release.py` diskda 323 CR, HEAD blob'ida 0 CR). Normallashtirmasa
            AYNI kod platformaga qarab BOSHQA digest berardi va muhr
            HAR SAFAR «mos emas» bo'lib commitni YASHIRARDI.
        """
        lf = tree(tmp_path / "lf", {**BAZA, "app/core/a.py": b"def f():\n    return 1\n"})
        crlf = tree(tmp_path / "crlf", {**BAZA, "app/core/a.py": b"def f():\r\n    return 1\r\n"})
        assert B.compute_source_digest(lf) == B.compute_source_digest(crlf)

    def test_mazmun_ozgarsa_digest_OZGARADI(self, tmp_path):
        a = tree(tmp_path / "a", BAZA)
        b = tree(tmp_path / "b", {**BAZA, "app/core/a.py": b"def f():\n    return 2\n"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_fayl_nomi_ozgarsa_digest_OZGARADI(self, tmp_path):
        """Yo'l hash'ga kiradi: faylni ko'chirish ko'rinmas qolmasin."""
        a = tree(tmp_path / "a", BAZA)
        kopya = {k: v for k, v in BAZA.items() if k != "app/core/a.py"}
        kopya["app/core/b.py"] = BAZA["app/core/a.py"]
        b = tree(tmp_path / "b", kopya)
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_fayllar_mazmuni_ALMASHSA_digest_OZGARADI(self, tmp_path):
        """⚠️  Yo'lsiz hash'da ikki faylning mazmunini almashtirish
            digestni O'ZGARTIRMASDAN kodni o'zgartirishga imkon berardi."""
        a = tree(tmp_path / "a", {**BAZA, "app/core/a.py": b"A\n", "app/main.py": b"B\n"})
        b = tree(tmp_path / "b", {**BAZA, "app/core/a.py": b"B\n", "app/main.py": b"A\n"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_chegara_surilishi_KORINADI(self, tmp_path):
        """Uzunlik hash'ga kiradi: ikki faylni «qo'shib yuborish» ko'rinsin."""
        a = tree(tmp_path / "a", {"app/x.py": b"AB\n", "app/y.py": b"C\n"})
        b = tree(tmp_path / "b", {"app/x.py": b"A\n", "app/y.py": b"BC\n"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_MUHR_digestga_KIRMAYDI(self, tmp_path):
        """Muhr bor-yo'qligi digestni o'zgartirmasligi SHART."""
        yoq = tree(tmp_path / "yoq", BAZA)
        bor = tree(tmp_path / "bor", {**BAZA,
                                      "app/_build_info.py": b"COMMIT = 'x' * 40\n"})
        assert B.compute_source_digest(yoq) == B.compute_source_digest(bor)

    def test_pycache_ETIBORGA_OLINMAYDI(self, tmp_path):
        """`__pycache__` ICHIDAGI `.py` ham chiqariladi.

        ⚠️  MUTATSIYA TEKSHIRUVI TOPDI (B10). Ilgari bu test
            `a.cpython-312.pyc` qo'shardi — lekin `.pyc` `*.py`
            naqshiga MOS KELMAYDI, ya'ni u `PATTERNS` tomonidan
            allaqachon chiqarilgan va `EXCLUDE_PARTS` AMALDA
            TEKSHIRILMAGAN edi. `EXCLUDE_PARTS` ni olib tashlash
            testni QIZIL QILMASDI.

            `__pycache__` ichida `.py` bo'lishi mumkin (vositalar yozadi,
            yoki tasodifan repoga tushadi) — shu holat endi qamralgan.
        """
        toza = tree(tmp_path / "t", BAZA)
        kesh = tree(tmp_path / "k", {
            **BAZA,
            "app/__pycache__/a.cpython-312.pyc": b"\x00\x01",
            #  ⚠️  AYNAN SHU qator `EXCLUDE_PARTS` ni sinaydi.
            "app/__pycache__/stray.py": b"ZARARLI = 1\n",
            "app/core/__pycache__/boshqa.py": b"ZARARLI = 2\n"})
        assert B.compute_source_digest(toza) == B.compute_source_digest(kesh)
        yollar = [p.name for p in B.iter_source_files(kesh)]
        assert "stray.py" not in yollar
        assert "boshqa.py" not in yollar

    def test_sql_QAMRALADI(self, tmp_path):
        """DDL xatti-harakatni belgilaydi — u ham relizning qismi."""
        a = tree(tmp_path / "a", BAZA)
        b = tree(tmp_path / "b", {**BAZA,
                                  "app/db/cash/x.sql": b"create table t(id bigint);\n"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_NUL_belgili_mazmun_CHALKASHTIRMAYDI(self, tmp_path):
        """Uzunlik hash'ga kirishi SHART — NUL mazmunda bo'lishi mumkin.

        ⚠️  MUTATSIYA TEKSHIRUVI TOPDI (B3). Oldingi «chegara surilishi»
            testi uzunliksiz ham QIZIL BO'LMAGAN, chunki yo'l prefiksi va
            `\0` ajratuvchilari o'zi yetarli edi. Lekin `\0` fayl
            MAZMUNIDA ham uchrashi mumkin (masalan docstring ichida), va
            o'sha holatda uzunliksiz oqim CHALKASHADI:

              A daraxt: x.py=b"A", y.py=b"B"
                oqim -> app/x.py \0 A \0 app/y.py \0 B \0
              B daraxt: x.py=b"A\0app/y.py\0B"  (BITTA fayl)
                oqim -> app/x.py \0 A \0 app/y.py \0 B \0   <- AYNI!

            Uzunlik maydoni bu sinfni BUTUNLAY yopadi.
        """
        a = tree(tmp_path / "a", {"app/x.py": b"A", "app/y.py": b"B"})
        b = tree(tmp_path / "b", {"app/x.py": b"A\0app/y.py\0B"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_DIGEST_VERSIYASI_hashga_kiradi(self, tmp_path, monkeypatch):
        """Versiya oshsa AYNI kod uchun ham digest O'ZGARISHI SHART.

        ⚠️  MUTATSIYA TEKSHIRUVI TOPDI (B9). Oldingi test faqat
            qaytarilgan SATR `sd1:` bilan boshlanishini tekshirardi —
            prefiks f-satrda alohida qo'shiladi, shu bois versiyani
            hash KIRISHIDAN olib tashlash testni QIZIL QILMASDI.

            Nega muhim: algoritm o'zgarib versiya oshganda eski va yangi
            digestlar SOLISHTIRILMASLIGI kerak. Versiya hash ichida
            bo'lmasa, `sd2:` prefiksli qiymat `sd1:` bilan AYNI hex
            berib, muhr «izchil» ko'rinishi mumkin edi.
        """
        r = tree(tmp_path, BAZA)
        d1 = B.compute_source_digest(r)
        monkeypatch.setattr(B, "DIGEST_VERSION", "sd9")
        d2 = B.compute_source_digest(r)
        assert d1.split(":", 1)[1] != d2.split(":", 1)[1], \
            "versiya hash KIRISHIDA emas — versiyalar orasida chalkashish mumkin"

    def test_DEPENDENCY_versiyalari_digestga_KIRMAYDI(self, tmp_path):
        """HALOL CHEKLOV, nuqson emas: digest FAQAT ilova manbasini qamraydi.

        ⚠️  AYNI manba + BOSHQA kutubxona versiyalari = AYNI digest.
            `requirements.txt` ataylab qamralmaydi: u build kontekstida
            bo'ladi, lekin runtime image'da mavjudligi kafolatlanmaydi,
            demak digest «har safar hisoblanadigan» xususiyatini
            yo'qotardi. Bog'liqlik identiteti ALOHIDA masala (lock fayl
            + image digest) — `PHASE9_RELEASE_ATTESTATION_PLAN.md`.
            Bu test cheklovni YOZIB QO'YADI, kelajakda kimdir digestni
            «to'liq artefakt identiteti» deb o'ylamasin.
        """
        a = tree(tmp_path / "a", {**BAZA, "requirements.txt": b"fastapi==0.141.1\n"})
        b = tree(tmp_path / "b", {**BAZA, "requirements.txt": b"fastapi==0.99.0\n"})
        assert B.compute_source_digest(a) == B.compute_source_digest(b)

    def test_versiya_prefiksi_bor(self, tmp_path):
        d = B.compute_source_digest(tree(tmp_path, BAZA))
        assert d.startswith(B.DIGEST_VERSION + ":")
        assert len(d.split(":", 1)[1]) == 64

    def test_fayl_tartibi_BARQAROR(self, tmp_path):
        """Tartib `as_posix()` bo'yicha, fayl tizimi tartibi bo'yicha EMAS."""
        r = tree(tmp_path, BAZA)
        yollar = [p.relative_to(r).as_posix() for p in B.iter_source_files(r)]
        assert yollar == sorted(yollar)
        assert "app/_build_info.py" not in yollar


# ════════════════════════════════════════════════════════════════════════
#  2. IDENTITET QARORI — rollback, eskirgan o'zgaruvchi, mos kelmaslik
# ════════════════════════════════════════════════════════════════════════
REAL = "6ef666bbf18df725ddec6da5db2c60a049a94e01"
BOSHQA = "2457b98a28598614c781ab96d6fd1467a1d9e3fc"
DIGEST = "sd1:" + "a" * 64


@pytest.fixture
def muhit_toza(monkeypatch):
    """BARCHA commit o'zgaruvchilarini olib tashlaydi (rollback holati)."""
    for k in B.ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("RAILWAY_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_REPLICA_ID", raising=False)
    return monkeypatch


def stamp(monkeypatch, *, commit=REAL, digest=DIGEST, at="2026-11-07T00:00:00+00:00"):
    monkeypatch.setattr(B, "read_stamp", lambda: {
        "COMMIT": commit, "SOURCE_DIGEST": digest, "SEALED_AT": at,
        "SEALED_BY": "operator", "BRANCH_REF": "release/x", "STAMP_VERSION": "bs1"})


class TestIdentitet:

    def test_ROLLBACK_SENARIYSI_commit_SAQLANADI(self, muhit_toza):
        """ENG MUHIM TEST: o'zgaruvchi YO'Q, muhr BOR -> commit BOR.

        Bu aynan 2026-11-06 holati: rollback kodni qaytardi, git
        o'zgaruvchilarini esa bermadi. Muhr bo'lsa identitet YO'QOLMAYDI.
        """
        stamp(muhit_toza)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        out = B.build_identity()
        assert out["commit"] == REAL
        assert out["commit_source"] == "stamp"
        assert out["trust"] == B.TRUST_STAMPED
        assert out["stamp_matches_source"] is True

    def test_ESKIRGAN_ozgaruvchi_ETIBORGA_OLINMAYDI(self, muhit_toza):
        """Muhr o'zgaruvchidan USTUN — yolg'on SHA `null` dan battar."""
        muhit_toza.setenv("APP_COMMIT_SHA", BOSHQA)
        stamp(muhit_toza, commit=REAL)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        out = B.build_identity()
        assert out["commit"] == REAL, "eskirgan o'zgaruvchi muhrni YENGDI"
        assert out["commit_source"] == "stamp"

    def test_MUHR_MOS_KELMASA_commit_AYTILMAYDI(self, muhit_toza):
        """Artefakt muhrlangandan KEYIN o'zgargan -> taxmin YO'Q."""
        stamp(muhit_toza, digest="sd1:" + "b" * 64)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        out = B.build_identity()
        assert out["commit"] is None
        assert out["commit_source"] is None
        assert out["trust"] == B.TRUST_MISMATCH
        assert out["stamp_matches_source"] is False
        #  Operator sababni ko'rishi uchun ikki digest ham beriladi.
        assert out["stamp_digest"] == "sd1:" + "b" * 64
        assert out["source_digest"] == DIGEST

    def test_muhrsiz_ozgaruvchi_ENV_ONLY(self, muhit_toza):
        muhit_toza.setattr(B, "read_stamp", lambda: None)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        muhit_toza.setenv("RAILWAY_GIT_COMMIT_SHA", REAL)
        out = B.build_identity()
        assert out["commit"] == REAL
        assert out["commit_source"] == "env:RAILWAY_GIT_COMMIT_SHA"
        assert out["trust"] == B.TRUST_ENV_ONLY, "ishonch darajasi ANIQ bo'lsin"

    def test_muhrsiz_ozgaruvchisiz_UNSTAMPED_lekin_digest_BOR(self, muhit_toza):
        muhit_toza.setattr(B, "read_stamp", lambda: None)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        out = B.build_identity()
        assert out["commit"] is None
        assert out["trust"] == B.TRUST_UNSTAMPED
        assert out["source_digest"] == DIGEST, "digest HAR DOIM hisoblanadi"

    def test_digest_XATOSI_identitetni_YIQITMAYDI(self, muhit_toza):
        muhit_toza.setattr(B, "read_stamp", lambda: None)
        muhit_toza.setattr(B, "source_digest", lambda **kw: None)
        muhit_toza.setattr(B, "digest_error", lambda: "OSError")
        out = B.build_identity()
        assert out["source_digest"] is None
        assert out["source_digest_error"] == "OSError"
        assert out["commit"] is None

    def test_digest_XATOSIDA_muhr_ham_ISHONCHSIZ(self, muhit_toza):
        """Digest hisoblanmasa muhr IZCHILLIGINI tekshirib bo'lmaydi."""
        stamp(muhit_toza)
        muhit_toza.setattr(B, "source_digest", lambda **kw: None)
        out = B.build_identity()
        assert out["commit"] is None, "tekshirilmagan muhrga ishonilmasin"
        assert out["trust"] == B.TRUST_MISMATCH

    def test_bosh_commitli_muhr_MUHR_EMAS(self, muhit_toza, monkeypatch):
        """Buzuq muhr (`COMMIT=''`) muhrsiz holatga tushadi."""
        import types
        mod = types.ModuleType("app._build_info")
        mod.COMMIT = "   "
        mod.SOURCE_DIGEST = DIGEST
        monkeypatch.setitem(__import__("sys").modules, "app._build_info", mod)
        assert B.read_stamp() is None

    def test_deployment_identity_ALOHIDA(self, muhit_toza):
        """`deployment_id` — PLATFORMA identiteti, kod identiteti EMAS."""
        muhit_toza.setattr(B, "read_stamp", lambda: None)
        muhit_toza.setattr(B, "source_digest", lambda **kw: DIGEST)
        muhit_toza.setenv("RAILWAY_DEPLOYMENT_ID", "76234c3e-dead-beef")
        out = B.build_identity()
        assert out["deployment_id"] == "76234c3e-dead-beef"
        assert out["commit"] is None, "deployment id commitni ISBOTLAMAYDI"

    def test_ishonch_darajalari_PROVEN_EMAS(self):
        """⚠️  TAHDID MODELI: repo yoki image yozuv huquqi bo'lgan hujumchi
            qayta muhrlashi mumkin, shu bois kriptografik AUTENTIKLIK YO'Q.
            Hech bir daraja `PROVEN` deb nomlanmasligi SHART — nom
            kafolatdan kuchli bo'lib ketmasin."""
        darajalar = {B.TRUST_STAMPED, B.TRUST_MISMATCH, B.TRUST_UNSTAMPED,
                     B.TRUST_ENV_ONLY}
        for d in darajalar:
            assert "PROVEN" not in d.upper()
        assert B.TRUST_STAMPED == "TAMPER_EVIDENT"


# ════════════════════════════════════════════════════════════════════════
#  3. BIR XIL API SIRTI != BIR XIL KOD
# ════════════════════════════════════════════════════════════════════════
class TestSirtIdentitetEmas:

    def test_api_elonidan_kod_identiteti_CHIQMAYDI(self, muhit_toza, tmp_path):
        """O'LCHANGAN DALIL: 192 marshrutli sirt `6ef666bb`, otasi
        `3f76b62e` va `2457b98a` uchun AYNAN bir xil. Ya'ni qobiliyat
        manifesti relizni AJRATMAYDI; manba digesti esa AJRATADI."""
        api1 = api_capabilities.declaration()
        api2 = api_capabilities.declaration()
        assert api1 == api2, "e'lon statik — kodga bog'liq EMAS"

        a = tree(tmp_path / "a", BAZA)
        b = tree(tmp_path / "b", {**BAZA, "app/core/a.py": b"def f():\n    return 99\n"})
        #  Ikki BOSHQA kod, AYNI api e'loni.
        assert B.compute_source_digest(a) != B.compute_source_digest(b)

    def test_digest_api_elonini_qamraydi(self, tmp_path):
        """Teskari tomoni: `api_capabilities.py` manba faylida, demak
        uning o'zgarishi digestda KO'RINADI."""
        a = tree(tmp_path / "a", {"app/core/api_capabilities.py": b"API_LEVEL = 2\n"})
        b = tree(tmp_path / "b", {"app/core/api_capabilities.py": b"API_LEVEL = 3\n"})
        assert B.compute_source_digest(a) != B.compute_source_digest(b)


# ════════════════════════════════════════════════════════════════════════
#  4. `/health` SHARTNOMASI
# ════════════════════════════════════════════════════════════════════════
class TestHealthShartnomasi:

    def test_eski_maydonlar_SAQLANDI(self, client):
        """Orqaga moslik: mijozlar `build.commit` ni o'qishda davom etadi."""
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        b = r.json()["build"]
        for k in ("commit", "environment", "platform_environment"):
            assert k in b, f"eski maydon YO'QOLDI: {k}"

    def test_yangi_maydonlar_BOR(self, client):
        b = client.get("/api/v1/health").json()["build"]
        for k in ("commit_source", "trust", "source_digest",
                  "stamp_matches_source", "sealed_at", "deployment_id"):
            assert k in b, f"yangi maydon yo'q: {k}"
        assert str(b["source_digest"]).startswith("sd1:")

    def test_javobda_FAYL_YOLI_YOQ(self, client):
        """⚠️  `/health` OCHIQ endpoint: ichki yo'llar oshkor bo'lmasin."""
        matn = json.dumps(client.get("/api/v1/health").json(), ensure_ascii=False)
        for yomon in ("C:\\", "/app/", "apps/server", "site-packages",
                      ".py", "Users"):
            assert yomon not in matn, f"javobda yo'l izi: {yomon!r}"

    def test_javobda_SIR_YOQ(self, client):
        matn = json.dumps(client.get("/api/v1/health").json(), ensure_ascii=False)
        for yomon in ("password", "secret", "token", "postgres://",
                      "postgresql://"):
            assert yomon not in matn.lower(), f"javobda sir izi: {yomon!r}"

    def test_health_ARZON_qoladi(self, client):
        """Digest KESHLANADI: ikkinchi so'rov fayl O'QIMAYDI.

        ⚠️  `/health` TIRIKLIK tekshiruvi — u sekin bo'lsa platforma
            healthcheck'i chalg'ib, sog'lom konteynerni o'ldirardi.
        """
        import time
        client.get("/api/v1/health")                 # isitadi
        t0 = time.perf_counter()
        for _ in range(5):
            assert client.get("/api/v1/health").status_code == 200
        o_rtacha = (time.perf_counter() - t0) / 5
        assert o_rtacha < 0.05, f"/health sekin: {o_rtacha*1000:.0f} ms"

    def test_health_ready_ham_identitet_beradi(self, client):
        r = client.get("/api/v1/health/ready")
        assert r.status_code in (200, 503)
        assert "build" in r.json()
