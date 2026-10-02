# -*- coding: utf-8 -*-
"""SOXTA KO'PRIK HARNESSI — DETERMINISTIK soxta ishga tushiruvchi va soxta yig'uvchi.

⚠️⚠️⚠️ BU SOXTA HARNESS. HAQIQIY 1C MUVAFFAQIYATINI ISBOTLAMAYDI.
        Bu faylda 1C ga ULANISH YO'Q, `1cv8.exe` ISHGA TUSHMAYDI, `.epf` BAJARILMAYDI,
        COM ishlatilmaydi, tarmoqqa chiqilmaydi va HAQIQIY Windows reestri o'qilmaydi.
        Bu mashinada 1C:Enterprise umuman o'rnatilmagan. «Ishga tushiruvchi» — bitta
        buyruq ketma-ketligini YOZIB OLADIGAN obyekt; «yig'uvchi» — papkaga uchta hujjat
        va Phase 4 paketini YOZADIGAN funksiya. Shu bois bu harness javob beradigan
        YAGONA savol: «ko'prikning ikkinchi tomoni SHUNDAY yozsa (yoki yozmasa), agent
        TO'G'RI qabul/rad qiladimi va operator NIMA ko'radi?».
        Yig'uvchining haqiqiy 1C dagi xulqi bundan keyin ham `UNVERIFIED_ON_REAL_1C`
        bo'lib QOLADI.

⚠️⚠️ `.epf` IKKILIK FAYLI QURILGAN DEB AYTILMAYDI. Yig'uvchining MANBA matni tayyor
     (`bridge_phase.EPF_SOURCE_READY`), ikkilik `.epf` ni esa 1C konfiguratorida OPERATOR
     yig'adi. Bu fayldagi `.epf` — bir necha baytlik SOXTA fayl.

⚠️⚠️ JARAYON O'LDIRILMAYDI. Soxta ishga tushiruvchi «jarayon»ni (`SoxtaJarayon`) tirik
     qoldiradi va uni TUGATADIGAN usul bu sinfda UMUMAN YO'Q: `taskkill`, jarayon
     daraxtini tugatish, `terminate`/`kill` chaqiruvi yozilmagan. Bekor qilish KOOPERATIV
     va u `launcher.CancelToken` bilan o'lchanadi.

⚠️⚠️ WILDCARD O'CHIRISH YO'Q. Bu harness hech narsani o'chirmaydi (`rmtree` naqshi yo'q);
     to'liq bo'lmagan paket ssenariysi uchun BITTA, NOMI SHARTNOMADAN olingan fayl
     olib tashlanadi (`paket_yarim`) — u ham AYNI papka ichida, `tmp_path` ostida.

⚠️⚠️ KREDENSIAL: bu faylda parol maydoni ham, parol bayrog'i ham YO'Q. Buyruq satriga
     FAQAT `/F<yo'l>` yoki `/S<server>` tushadi va u `bridge_protocol.
     assert_launch_command` darvozasidan o'tadi (mavjud
     `collector_bridge._assert_no_credentials` qayta ishlatiladi).

NUSXA KO'CHIRILMAGAN NARSALAR (ataylab):
  · Phase 4 paket generatorlari — `tests.discovery_1c_runtime_mock`;
  · sintetik reestr/fayl tizimi — `tests.test_agent_detector` dagi `FakeRegistry`/`FakeFiles`;
  · muhit, soat, `sleeper` va `UiModel` fiksturalari — `tests.agent_scenario_mock`.
  ⚠️ Ular IMPORT qilinadi, qayta yozilmaydi: ikki nusxa bir kun bir-biridan ajralib
     ketardi va qaysi biri haqiqat ekani aniqlanmay qolardi.
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass, field

from app.services.discovery_1c import runtime_bundle as rb
from app.services.discovery_agent import BUNDLE_SUBDIR
from app.services.discovery_agent import bridge_protocol as bpr
from app.services.discovery_agent import detector as det
from app.services.discovery_agent import launcher as lch
from app.services.discovery_agent import one_click as oc
from tests import agent_scenario_mock as X
from tests import discovery_1c_runtime_mock as M
from tests.test_agent_detector import ONE_HIVE, FakeFiles

#: ⚠️⚠️ SARLAVHA DA'VOSI — testlar uni AYNAN shu holda qulflaydi (matn yumshatilsa test
#: yiqiladi). Harnessning qiymati aynan shu ogohlantirishda: yashil to'plam «1C da
#: ishladi» degani EMAS.
MATRITSA_OGOHLANTIRISHI = "BU SOXTA HARNESS. HAQIQIY 1C MUVAFFAQIYATINI ISBOTLAMAYDI."

#: Bu harness kutadigan yig'uvchi o'zligi — `one_click` dan OLINADI (ikkinchi haqiqat yo'q).
KUTILGAN_YIGUVCHI: tuple[str, str] = (oc.EXPECTED_COLLECTOR_NAME,
                                      oc.EXPECTED_COLLECTOR_VERSION)

#: Eski yig'uvchining o'zligi — `WRONG_COLLECTOR_VERSION` ssenariysi uchun.
#: ⚠️ ATAYLAB `UNVERIFIED` qo'shimchasi bilan: versiya satri «tasdiqlangan» da'vosini
#: BERMASIN (paketdagi sir/da'vo darvozalari shu so'zni qidiradi).
ESKI_YIGUVCHI: tuple[str, str] = (oc.EXPECTED_COLLECTOR_NAME, "0.1.0-UNVERIFIED")

#: So'rovdan OLDIN yozilgan chiqish uchun vaqt tamg'asi (`OUTPUT_PREDATES_REQUEST`).
#: ⚠️ `agent_scenario_mock.NOW_ISO` dan BIR KUN oldin va AYNI ofset bilan: taqqoslash
#: faqat VAQT bo'yicha bo'lsin, ofset farqi bo'yicha emas.
OLDINGI_KUN_ISO = "2026-09-30T09:00:00+06:00"

#: Boshqa yurishning o'zligi (`STALE_OUTPUT`). ⚠️ `status.RUN_ID_RE` shaklida, lekin
#: ATAYLAB qo'lda yozilgan: u HECH QACHON `secrets.token_hex` bergan qiymatga teng
#: bo'lmasligi kerak, aks holda «eski natija» ssenariysi tasodifan muvaffaqiyat bo'lardi.
BEGONA_RUN_ID = "0f0f0f0f0f0f0f0f"
#: Boshqa so'rovning bir martalik qiymati (`NONCE_MISMATCH`), 32 hex belgi.
BEGONA_NONCE = "0f" * 16

#: Deterministik soat qadami (soniya). ⚠️ HAQIQIY vaqt KUTILMAYDI.
SOAT_QADAMI = 1.0
#: Kutishning qisqa chegarasi — chegara KIRISHDAN keladi, demak uni kichraytirish
#: XULQNI o'zgartirmaydi, faqat to'plamni tez qiladi.
KUTISH_CHEGARASI = 6.0
KUTISH_QADAMI = 2.0


class HarnessError(AssertionError):
    """Harnessning O'Z nuqsoni (fikstura noto'g'ri qurilgan), agentning nuqsoni EMAS.

    ⚠️ NEGA ALOHIDA TUR: fikstura xatosi test yiqilishiga o'xshab ketsa, «agent buzildi»
       degan YOLG'ON xulosa chiqardi. Shu bois harness o'z shartlarini O'ZI tekshiradi.
    """


# ══════════════════════════════════════════════════════════════════════════════════════════
# SOXTA ISHGA TUSHIRUVCHI — buyruqni YOZIB OLADI, jarayonni O'LDIRMAYDI
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class SoxtaJarayon:
    """«Ochilgan 1C» ning SOXTA o'zligi.

    ⚠️⚠️ `tirik` maydoni FAQAT `True` bo'ladi: bu sinfda uni `False` qiladigan usul
         UMUMAN YOZILMAGAN. Bekor qilish ssenariysi (L) aynan shu maydonni o'lchaydi —
         ya'ni «jarayon o'ldirilmadi» da'vosi izoh bilan emas, HOLAT bilan isbotlanadi.
    """

    handle: str
    tirik: bool = True


class SoxtaIshgaTushiruvchi:
    """`launcher.Opener` ning SOXTA amalga oshirilishi: buyruqni yozib oladi.

    ⚠️⚠️ JARAYON OCHMAYDI: `subprocess` ham, `Popen` ham, COM ham ishlatilmaydi. U faqat
         kelgan buyruqni ro'yxatga qo'yadi va `OpenerOutcome` qaytaradi.
    ⚠️⚠️ JARAYONNI TUGATADIGAN USUL YO'Q: `tugatish_chaqirildi` sanog'i HAR DOIM nol
         bo'lib qoladi, chunki uni oshiradigan kod yozilmagan. Bu «bekor qilish
         kooperativ» da'vosining O'LCHOVI.
    ⚠️ DETERMINISTIK: `handle` sanoqdan quriladi (tasodifiy qiymat YO'Q), shu bois bir
       xil ssenariy AYNAN bir xil izni qoldiradi.
    """

    def __init__(self, *, ocha_oladimi: bool = True) -> None:
        #: ⚠️ `False` bo'lsa «1C ochilmadi» yo'li o'lchanadi (`LAUNCH_FAILED`).
        self._ocha_oladimi = bool(ocha_oladimi)
        self.buyruqlar: list[tuple[str, ...]] = []
        self.jarayonlar: list[SoxtaJarayon] = []
        #: ⚠️ HAR DOIM 0: bu sanoqni oshiradigan usul bu sinfda YO'Q.
        self.tugatish_chaqirildi = 0

    def __call__(self, command: tuple[str, ...]) -> lch.OpenerOutcome:
        #: ⚠️ Buyruq SHARTNOMA darvozasidan qayta o'tkaziladi: harness agentga
        #: tekshirilmagan buyruqni «o'tdi» deb ko'rsatmasin.
        bpr.assert_launch_command(command)
        self.buyruqlar.append(tuple(command))
        if not self._ocha_oladimi:
            return lch.OpenerOutcome(
                started=det.TRI_FALSE,
                detail="SOXTA: ishga tushirish BAJARILMADI (harness shunday sozlangan)")
        jarayon = SoxtaJarayon(handle=f"SOXTA-JARAYON-{len(self.jarayonlar) + 1}")
        self.jarayonlar.append(jarayon)
        return lch.OpenerOutcome(started=det.TRI_TRUE, handle=jarayon.handle,
                                 detail="SOXTA: jarayon ochilgan DEB BELGILANDI")

    @property
    def chaqiruvlar(self) -> int:
        """Ishga tushiruvchi NECHA MARTA chaqirilgan (nol — umuman ochilmagan)."""
        return len(self.buyruqlar)

    @property
    def hammasi_tirik(self) -> bool:
        """Ochilgan HAMMA soxta jarayon tirikmi (bekor qilishdan KEYIN ham)."""
        return all(j.tirik for j in self.jarayonlar)


# ══════════════════════════════════════════════════════════════════════════════════════════
# HUJJAT FIKSTURALARI — `response.json` va `bridge_done.json`
# ══════════════════════════════════════════════════════════════════════════════════════════
def yoz_json(yol, doc) -> pathlib.Path:
    """Hujjatni UTF-8 (BOM'SIZ) va `\\n` bilan yozadi.

    ⚠️ Chiqish kodlashi SHARTNOMA: BOM determinizmni buzadi, `\\r\\n` esa baytlarni
       o'zgartiradi (Windows'da bu jimgina sodir bo'ladi).
    """
    p = pathlib.Path(yol)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8",
                 newline="\n")
    return p


def javob_hujjati(req, *, status: str = bpr.STATUS_OK, run_id=None, nonce=None, xesh=None,
                  collector=None, boshlandi=None, tugadi=None, izohlar=()) -> dict:
    """`binos-bridge-response-v1` — YIG'UVCHI yozadigan hujjat (soxta).

    ⚠️ Standart holda HAMMA maydon so'rovdan KO'CHIRILADI: mos kelmaslik ssenariysi
       AYNAN bitta maydonni almashtirib o'lchanadi, ya'ni rad etish sababi BIR MA'NOLI.
    """
    t = X.NOW_ISO
    nom, versiya = (collector if collector is not None
                    else (req["expected_collector"]["name"],
                          req["expected_collector"]["version"]))
    return {
        "response_version": bpr.RESPONSE_VERSION,
        "run_id": req["run_id"] if run_id is None else run_id,
        "nonce": req["nonce"] if nonce is None else nonce,
        "collector": {"name": nom, "version": versiya},
        "target_fingerprint": req["target_fingerprint"] if xesh is None else xesh,
        "status": status,
        "started_at": t if boshlandi is None else boshlandi,
        "finished_at": t if tugadi is None else tugadi,
        "notes": list(izohlar),
    }


def belgi_hujjati(req, *, run_id=None, nonce=None, vaqt=None) -> dict:
    """`binos-bridge-done-v1` — ENG OXIRIDA yoziladigan tugallanish belgisi (soxta)."""
    return {
        "done_version": bpr.DONE_VERSION,
        "run_id": req["run_id"] if run_id is None else run_id,
        "nonce": req["nonce"] if nonce is None else nonce,
        "written_at": X.NOW_ISO if vaqt is None else vaqt,
    }


def paket_yarim(papka) -> str:
    """SOG'LOM Phase 4 paketi, LEKIN majburiy fayllardan BITTASI olib tashlangan.

    ⚠️ Fayl nomi SHARTNOMADAN (`runtime_bundle.REQUIRED_FILES`) olinadi, qo'lda
       yozilmaydi: ikkinchi ro'yxat bir kun birinchisidan ajralib ketardi.
    ⚠️ WILDCARD O'CHIRISH YO'Q: aynan bitta, nomi ma'lum fayl olib tashlanadi va u
       `tmp_path` ostidagi papkada turadi.
    """
    M.paket_sog_lom(str(papka))
    yoq = rb.RUN_SUMMARY_FILE
    if yoq not in rb.REQUIRED_FILES:        # pragma: no cover - shartnoma o'zgarsa tutadi
        raise HarnessError(
            f"{yoq} majburiy fayllar ro'yxatida YO'Q — «to'liq bo'lmagan paket» "
            f"ssenariysi o'lchanmay qolardi")
    os.remove(os.path.join(str(papka), yoq))
    return str(papka)


# ══════════════════════════════════════════════════════════════════════════════════════════
# SOXTA YIG'UVCHI — `request.json` ni O'QIB, uchta hujjatni SHARTNOMA TARTIBIDA yozadi
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class SoxtaYiguvchi:
    """1C ichidagi yig'uvchining O'RNIDA ishlaydigan DETERMINISTIK fikstura.

    Yozish TARTIBI shartnoma bo'yicha va u JURNALGA olinadi (`yozish_tartibi`):
        1. Phase 4 paketi (`bundle/`, ichida `manifest.json` oxirgi — generator ishi);
        2. `response.json`;
        3. `bridge_done.json` — ENG OXIRIDA.
    ⚠️⚠️ NEGA TARTIB O'LCHANADI: tugallanish belgisi oxirgi bo'lmasa, agent yarim
         yozilgan javobni to'liq deb o'qib ketardi. Harness o'z tartibini O'ZI qulflaydi,
         ya'ni ssenariylar «belgi oxirgi» da'vosiga ishonmaydi — uni O'LCHAYDI.
    ⚠️ `paket=None` bo'lsa `bundle/` ga hech narsa yozilmaydi: «yig'uvchi umuman
       boshlanmagan» holati shu bilan taqlid qilinadi.
    """

    paket: object = M.paket_sog_lom
    status: str = bpr.STATUS_OK
    javob: bool = True
    belgi: bool = True
    run_id: str | None = None
    nonce: str | None = None
    xesh: str | None = None
    collector: tuple[str, str] | None = None
    belgi_vaqti: str | None = None
    izohlar: tuple[str, ...] = ()
    yozish_tartibi: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in bpr.RESPONSE_STATUSES:
            raise HarnessError(
                f"noma'lum javob holati: {self.status!r}; ruxsat etilganlari "
                f"{sorted(bpr.RESPONSE_STATUSES)}")

    def yoz(self, run_dir) -> tuple[str, ...]:
        """Yurish papkasiga yozadi va YOZILGAN NOMLARNI tartibida qaytaradi."""
        rd = pathlib.Path(run_dir)
        req = sorov_hujjati(rd)
        if self.paket is not None:
            paket_papkasi = rd / BUNDLE_SUBDIR
            paket_papkasi.mkdir(parents=True, exist_ok=True)
            self.paket(str(paket_papkasi))
            self.yozish_tartibi.append(BUNDLE_SUBDIR)
        if self.javob:
            yoz_json(rd / bpr.RESPONSE_FILE,
                     javob_hujjati(req, status=self.status, run_id=self.run_id,
                                   nonce=self.nonce, xesh=self.xesh,
                                   collector=self.collector, izohlar=self.izohlar))
            self.yozish_tartibi.append(bpr.RESPONSE_FILE)
        if self.belgi:
            yoz_json(rd / bpr.DONE_FILE,
                     belgi_hujjati(req, run_id=self.run_id, nonce=self.nonce,
                                   vaqt=self.belgi_vaqti))
            self.yozish_tartibi.append(bpr.DONE_FILE)
        return tuple(self.yozish_tartibi)

    def sleeper_sifatida(self, runs_root, *, chetla=()):
        """`UiModel.sleeper` o'rnida ishlaydigan funksiya: BIR MARTA yozadi.

        ⚠️⚠️ NEGA `sleeper` ICHIDA: agent yig'uvchining chiqishini KUTADI, demak fayllar
             kutish BOSHLANGANDAN KEYIN paydo bo'lishi kerak — aks holda test kutish
             yo'lini umuman o'lchamagan bo'lardi. `sleeper` KIRISHDAN keladi, ya'ni
             HAQIQIY soniyalar kutilmaydi.
        ⚠️ Yurish papkasi DISKDAN topiladi: uning nomi `run_id`, ya'ni `secrets` bergan
           qiymat — harness uni OLDINDAN bilmaydi.
        ⚠️ `chetla` — ALLAQACHON mavjud papkalar nomi. Ikki yurish BIR ildizda bo'lsa
           («N» ssenariysi) yig'uvchi AYNAN yangi papkaga yozishi kerak: «oxirgi
           o'zgargan papka» kabi taxmin NONDETERMINISTIK bo'lardi.
        """
        holat = {"yozildi": False}

        def uxla(_soniya: float) -> None:
            if holat["yozildi"]:
                return
            holat["yozildi"] = True
            self.yoz(yangi_yurish_papkasi(runs_root, chetla))

        return uxla


# ══════════════════════════════════════════════════════════════════════════════════════════
# YURISH PAPKASI — HAQIQIY protokol bilan tayyorlanadi
# ══════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Yurish:
    """Tayyorlangan yurish: papka + so'rov hujjati + o'zlik."""

    run_dir: pathlib.Path
    request: dict
    identity: object

    @property
    def bundle_dir(self) -> pathlib.Path:
        return self.run_dir / BUNDLE_SUBDIR


def runs_ildizi(tmp_path, nom: str = "runs") -> str:
    """Yurishlar ildizi — MANBA DARAXTIDAN TASHQARIDA (testda `tmp_path`).

    ⚠️ Haqiqiy `%LOCALAPPDATA%` ga YOZILMAYDI: to'plam foydalanuvchining papkasini
       ifloslantirmasligi kerak. Standart ildiz `bridge_protocol` ning O'Z testida
       o'lchanadi, bu yerda esa `--runs-dir` ning TENG HUQUQLI yo'li ishlatiladi.
    """
    p = pathlib.Path(tmp_path) / nom
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def nishon_xeshi(nom: str = "Sintetik soxta baza",
                 locator: str = "SOXTA-LOKATOR") -> str:
    """Nishonning KREDENSIALSIZ xeshi (xom `locator` protokolga YOZILMAYDI)."""
    return bpr.target_fingerprint(det.KIND_FILE, nom, locator)


def yurish_tayyorla(runs_root, *, xesh=None, now: str = X.NOW_ISO,
                    collector: tuple[str, str] = KUTILGAN_YIGUVCHI,
                    mode: str = rb.MODE_METADATA_ONLY) -> Yurish:
    """HAQIQIY protokol bilan yurish papkasini va `request.json` ni tayyorlaydi.

    ⚠️⚠️ SOXTALASHTIRILMAYDI: `new_run`, `prepare_run_dir`, `build_request` va
         `write_request` — AGENTNING O'Z kodi. Harness faqat ikkinchi tomonni (yig'uvchini)
         taqlid qiladi; so'rov tomonini taqlid qilsak, shartnoma O'ZINI tasdiqlagan
         bo'lardi.
    """
    identity = bpr.new_run(now=now)
    run_dir = bpr.prepare_run_dir(identity.run_id, runs_root=runs_root)
    bundle_dir = run_dir / BUNDLE_SUBDIR
    bundle_dir.mkdir()
    req = bpr.build_request(
        identity, output_dir=str(bundle_dir), collector_name=collector[0],
        collector_version=collector[1],
        target_fingerprint=nishon_xeshi() if xesh is None else xesh,
        mode=mode, allowed_probes=(), notes=oc.REQUEST_NOTES,
    )
    bpr.write_request(run_dir, req)
    return Yurish(run_dir=run_dir, request=req, identity=identity)


def sorov_hujjati(run_dir) -> dict:
    """Yurish papkasidagi `request.json` (yig'uvchi AYNAN shuni o'qiydi)."""
    p = pathlib.Path(run_dir) / bpr.REQUEST_FILE
    if not p.is_file():
        raise HarnessError(
            f"{bpr.REQUEST_FILE} yo'q — yig'uvchi o'qiydigan hujjat yozilmagan")
    return json.loads(p.read_text(encoding="utf-8"))


def yurish_papkalari(runs_root) -> tuple[pathlib.Path, ...]:
    """Ildizdagi yurish papkalari (nomi bo'yicha tartiblangan — determinizm)."""
    kok = pathlib.Path(runs_root)
    if not kok.is_dir():
        return ()
    return tuple(p for p in sorted(kok.iterdir()) if p.is_dir())


def yangi_yurish_papkasi(runs_root, chetla=()) -> pathlib.Path:
    """`chetla` dan TASHQARIDAGI AYNAN bitta yurish papkasi.

    ⚠️ Papka nomi `run_id`, ya'ni `secrets` bergan qiymat — harness uni oldindan bilmaydi,
       shu bois u DISKDAN topiladi. Ikkitasi qolsa — HARNESS nuqsoni (test o'z fiksturasi
       haqida yolg'on xulosa chiqarmasin).
    """
    chetlangan = {str(n) for n in chetla}
    papkalar = [p for p in yurish_papkalari(runs_root) if p.name not in chetlangan]
    if len(papkalar) != 1:
        raise HarnessError(f"aynan bitta YANGI yurish papkasi kutilgan, topilgani: "
                           f"{[p.name for p in papkalar]}")
    return papkalar[0]


def yagona_yurish_papkasi(runs_root) -> pathlib.Path:
    """AYNAN bitta yurish papkasi (ildizda boshqa papka YO'Q)."""
    return yangi_yurish_papkasi(runs_root)


def papka_nomlari(papka) -> tuple[str, ...]:
    """Papka ILDIZIDAGI a'zolar nomi (tartiblangan)."""
    p = pathlib.Path(papka)
    if not p.is_dir():
        return ()
    return tuple(sorted(a.name for a in p.iterdir()))


# ══════════════════════════════════════════════════════════════════════════════════════════
# KUTISH — DETERMINISTIK SOAT bilan (haqiqiy soniya KUTILMAYDI)
# ══════════════════════════════════════════════════════════════════════════════════════════
def kutish(yurish: Yurish, *, cancel=None, chegara: float = KUTISH_CHEGARASI,
           qadam: float = KUTISH_QADAMI, soat_qadami: float = SOAT_QADAMI,
           uyqu_jurnali=None) -> lch.WaitOutcome:
    """`launcher.wait_for_collector` ni DETERMINISTIK soat va `sleeper` bilan chaqiradi.

    ⚠️⚠️ HAQIQIY VAQT KUTILMAYDI: soat KIRISHDAN keladi va har chaqiruvda `soat_qadami`
         ga oshadi, `sleeper` esa so'rovni faqat JURNALGA yozadi. Shu bois «cheksiz
         kutish YO'Q» da'vosi matn bilan emas, o'lchov SONI bilan isbotlanadi.
    """
    return lch.wait_for_collector(
        run_dir=yurish.run_dir, request=yurish.request, cancel=cancel,
        timeout_seconds=chegara, poll_seconds=qadam,
        clock=X.oshuvchi_soat(soat_qadami),
        sleeper=X.yozib_oluvchi_uyqu([] if uyqu_jurnali is None else uyqu_jurnali),
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# SINTETIK MUHIT — o'rnatmaning klient fayli ISBOTLANGAN bo'lishi bilan
# ══════════════════════════════════════════════════════════════════════════════════════════
def muhit(root, *bazalar: X.Baza, versiyalar: tuple[str, ...] = (X.YANGI_VERSIYA,)):
    """1C BOR + berilgan bazalar e'lon qilingan SINTETIK muhit.

    ⚠️⚠️ NEGA `agent_scenario_mock.muhit_bazali` YETARLI EMAS: u `FakeFiles` ga exe
         yo'llarini BERMAYDI, ya'ni o'rnatmaning klient yozuvi `present` bo'lmaydi va
         `launcher.choose_exe` `EXE_MISSING` bilan yiqiladi. Ishga tushiruvchi
         ssenariylari (C, K, L) esa AYNAN shu tanlovni o'lchaydi, shu bois bu yerda
         exe yo'llari fayl tizimiga ham E'LON QILINADI.
    ⚠️ `filesystem_roots` BO'SH qoladi: haqiqiy `C:\\Program Files` ga qaramaslik SHART,
       aks holda natija MASHINANING holatiga bog'liq bo'lib qolardi.
    ⚠️ Reestr yozuvlari va exe fayllari AYNI yo'ldan quriladi (`agent_scenario_mock`
       generatorlari), shu bois ikkinchi yo'l lug'ati paydo bo'lmaydi.
    """
    yollar = tuple(X.exe_yoz(root, v) for v in versiyalar)
    ibases_yoli = str(pathlib.Path(root) / "ibases.v8i")
    return X.muhit(
        registry=X.reestr(root, *versiyalar),
        files=FakeFiles(files=yollar,
                        texts={ibases_yoli: X.v8i_matn(*bazalar)}),
        config=det.DetectorConfig(
            registry_install_keys=ONE_HIVE,
            ibases_files=((det.SOURCE_IBASES_USER, ibases_yoli),)),
    )


def baza(nom: str, root, papka: str) -> X.Baza:
    """Nomli sintetik baza e'loni (har biri O'Z `locator` i bilan).

    ⚠️ `locator` lar FARQLI bo'lishi SHART: `detector` bir xil ulanish satrini BITTA baza
       deb o'qiydi, ya'ni ikki e'lon jimgina bitta nishon bo'lib qolardi va «bir nechta
       baza» ssenariysi umuman o'lchanmagan bo'lardi.
    """
    return X.Baza(nom=nom, yol=str(pathlib.Path(root) / papka))


def muhit_bir_baza(root):
    """B ssenariysi: BITTA o'rnatma, BITTA baza."""
    return muhit(root, baza("Sintetik yagona baza", root, "sintetik-baza"))


def muhit_ikki_baza(root):
    """D ssenariysi: IKKI baza — tanlov OPERATORDA."""
    return muhit(root,
                 baza("Birinchi sintetik baza", root, "sintetik-baza-1"),
                 baza("Ikkinchi sintetik baza", root, "sintetik-baza-2"))


def muhit_ikki_versiya(root):
    """C ssenariysi: IKKI platforma versiyasi, BITTA baza."""
    return muhit(root, baza("Sintetik yagona baza", root, "sintetik-baza"),
                 versiyalar=(X.ESKI_VERSIYA, X.YANGI_VERSIYA))


# ══════════════════════════════════════════════════════════════════════════════════════════
# AGENT va BIR BOSISHLI YURISH
# ══════════════════════════════════════════════════════════════════════════════════════════
def agent(tmp_path, *, scan, sleeper=None, chegara: float = 30.0,
          qadam: float = KUTISH_QADAMI, nom: str = "natija", epf_path=None,
          output_dir=None):
    """Sinovga tayyor `UiModel`: oyna OCHMAYDI, soatga QARAMAYDI, 1C ga ULANMAYDI.

    ⚠️ `bundle_dir` BERILMAYDI: bir bosishli oqimda uni `one_click` yurishning O'Z
       papkasiga bog'laydi (operator fayllarni QO'LDA KO'CHIRMAYDI).
    """
    ota = pathlib.Path(tmp_path) / nom
    ota.mkdir(parents=True, exist_ok=True)
    model = X.agent(ota, scan=scan, epf_path=epf_path, output_dir=output_dir)
    model.clock = X.oshuvchi_soat(SOAT_QADAMI)
    model.sleeper = (lambda _s: None) if sleeper is None else sleeper
    model.watch_timeout_seconds = chegara
    model.watch_poll_seconds = qadam
    return model


def bir_bosish(model, *, runs_root, select_index=None, kutish_jurnali=None):
    """`one_click.run_one_click` ni hodisa va kutish jurnali bilan yurgizadi."""
    hodisalar: list = []
    model.on_progress = None
    natija = oc.run_one_click(
        model, runs_root=runs_root, select_index=select_index,
        on_event=hodisalar.append,
        on_wait=None if kutish_jurnali is None else kutish_jurnali.append,
    )
    return natija, hodisalar


# ══════════════════════════════════════════════════════════════════════════════════════════
# IMPORT PAYTIDAGI HARNESS TEKSHIRUVI
# ══════════════════════════════════════════════════════════════════════════════════════════
# ⚠️ Fikstura o'z shartlarini IMPORT paytida tekshiradi: buzilgan harness «agent buzildi»
#    degan yolg'on xulosa bermasin.
assert "SOXTA HARNESS" in MATRITSA_OGOHLANTIRISHI, \
    "sarlavha da'vosi harnessning soxtaligini AYNAN aytishi SHART"
assert KUTILGAN_YIGUVCHI != ESKI_YIGUVCHI, \
    "«noto'g'ri versiya» ssenariysi uchun ikki o'zlik FARQ qilishi SHART"
assert bpr.NONCE_RE.fullmatch(BEGONA_NONCE), "begona `nonce` shartnoma shaklida bo'lsin"
assert rb.RUN_SUMMARY_FILE in rb.REQUIRED_FILES, \
    "«to'liq bo'lmagan paket» uchun olib tashlanadigan fayl MAJBURIY ro'yxatda bo'lsin"
assert not hasattr(SoxtaIshgaTushiruvchi, "tugat"), \
    "soxta ishga tushiruvchida jarayonni TUGATADIGAN usul BO'LMASLIGI SHART"
