# -*- coding: utf-8 -*-
"""VAQTINCHALIK PostgreSQL KLASTERLARINING EGALIK BILAN TOZALANISHI.

Bu modul TEST INFRASTRUKTURASI. Ishlab chiqarish kodi emas va `app/` dan
import qilinmaydi.

═══ NEGA KERAK (o'lchangan, taxmin emas) ════════════════════════════════════
`tests/conftest.py` ning `pytest_sessionfinish` tozalashi ikki holatda ISHLAMAYDI:

  1. PROCESS QATTIQ O'LSA (`taskkill /F`, OOM, tok uzilishi, IDE «stop») —
     `pytest_sessionfinish` ham, `atexit` ham ishga tushmaydi. O'lchangan:
     `os._exit()` bilan chiqqan bola o'z postmaster'ini va uning BOLALARINI
     mashinada qoldiradi. Shu mashinada aynan shu yo'l bilan 45 ta postmaster
     bitta pytest yurishidan qolgan.
  2. TO'XTATISH BLOKLANSA — `pgserver._cleanup()` butun foydalanuvchi uchun
     BITTA global `InterProcessLock` oladi va `pg_ctl -w stop` ni TIMEOUT'SIZ
     chaqiradi. Ya'ni bitta tiqilib qolgan klaster seans oxirini CHEKSIZ
     ushlab turishi mumkin; operator pytest'ni o'ldiradi -> (1) holatiga tushadi.

═══ YECHIM: IKKI QATLAM ═════════════════════════════════════════════════════
  A. OLDINI OLISH — har postmaster (va uning bolalari) Windows JOB OBYEKTIGA
     qo'shiladi, `KILL_ON_JOB_CLOSE` bilan. Pytest processi QANDAY o'lsa ham,
     OS job a'zolarini o'zi tugatadi. Bu BEGONA processga tegishi MUMKIN EMAS:
     job ga faqat biz ANIQ qo'shgan PID'lar kiradi.
  B. BOSHQARILGAN TO'XTATISH — `pytest_sessionfinish` da avval odobli
     `srv.cleanup()`, LEKIN VAQT CHEGARASI bilan (alohida thread + `join`).
     Blokланса kutmaymiz: EGALIGI ISBOTLANGAN process daraxtini o'zimiz
     to'xtatamiz, keyin papkani o'chiramiz.

═══ EGALIK QANDAY ISBOTLANADI (uch mustaqil shart) ══════════════════════════
  1. `pgdata` yo'li BIZ yaratgan yo'l (ro'yxatdan);
  2. `<pgdata>/postmaster.pid` ning BIRINCHI qatori — o'sha PID;
  3. JONLI processning buyruq satri AYNI `pgdata` yo'lini o'z ichiga oladi.

⚠️  3-shart MAJBURIY. Windows PID'larni QAYTA ISHLATADI va `pgserver` ning o'z
    fallback'i buni tekshirmaydi (`utils.PostmasterInfo._init_process_meta` da
    `create_time` solishtiruvi IZOHGA OLINGAN). Ya'ni eskirgan `postmaster.pid`
    bilan `terminate()` qilish BEGONA processni o'ldirishi mumkin edi. Bu yerda
    buyruq satri tekshirilmasa — HECH NARSA to'xtatilmaydi.
⚠️  NOM BO'YICHA QIDIRUV YO'Q. `taskkill /IM postgres.exe` yoki «hamma
    postgres» bo'yicha harakat bu modulда TAQIQ: mashinada boshqa ishlarning
    postgres'lari bo'ladi.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

#: Har yaratilgan klaster uchun bitta yozuv.
_OWNED: list[dict] = []

#: Windows job obyekti (bitta pytest processi uchun bitta job).
_JOB = None
_JOB_FAILED = False

#: Odobli to'xtatishga beriladigan vaqt (soniya). Juda uzun qilib bo'lmaydi:
#: bu seans OXIRIDA kutiladigan vaqt va 40 klaster uchun ko'paytiriladi.
STOP_TIMEOUT = float(os.environ.get("SAVDOOS_PG_STOP_TIMEOUT", "20"))


# ══ 1. EGALIK ═══════════════════════════════════════════════════════════════

def _pid_from_pgdata(pgdata: Path) -> int | None:
    """`postmaster.pid` ning BIRINCHI qatori. Fayl yo'q/buzuq bo'lsa `None`."""
    try:
        birinchi = (pgdata / "postmaster.pid").read_text(
            encoding="utf-8", errors="replace").splitlines()[0].strip()
        return int(birinchi)
    except Exception:      # noqa: BLE001 — fayl yo'q, bo'sh yoki son emas
        return None


def _cmdline_has(pid: int, igna: str) -> bool:
    """Jonli processning buyruq satrida `igna` bormi — EGALIKNING 3-sharti.

    ⚠️  IKKALA TOMON HAM NORMALLASHTIRILADI. Bu qatorning birinchi versiyasida
        faqat IGNA kichik harfga o‘girilgan, buyruq satri esa O‘GIRILMAGAN
        edi — natijada bosh harfli yo‘l (disk nomi, foydalanuvchi papkasi)
        HECH QACHON mos kelmasdi va egalik HAR DOIM «isbotlanmadi» chiqardi.
        Ya’ni ikkinchi himoya qatlami JIM o‘chib turgan edi: uni mutatsiya
        o‘chirganda HECH NARSA o‘zgarmadi (M-2 «TUTILMADI»), job obyektini
        o‘chirganda esa TO‘RTTA holat ham oqdi (M-1b). Buni faqat mutatsiya
        isboti ko‘rsatdi — testlar yashil edi, chunki job obyekti hammasini
        yopib turgandi.
    ⚠️  `postgres` ham, `postgres.exe` ham qabul qilinadi: Windows’da
        `psutil.name()` `.exe` bilan qaytadi. `pgserver` ning o‘z
        eskirgan-klaster tozalash bloki aynan shu yerda xato qiladi
        (`== 'postgres'`), shu bois u Windows’da HECH QACHON ishlamaydi.
    """
    try:
        import psutil
        p = psutil.Process(pid)
        if p.name().lower() not in ("postgres", "postgres.exe"):
            return False
        return igna in _normalize(" ".join(p.cmdline()))
    except Exception:      # noqa: BLE001 — process yo'q yoki ruxsat yo'q
        return False


def _normalize(yol: str) -> str:
    """Yo'lni solishtirish uchun: Postgres `-D` da `/` ishlatadi, Python `\\`."""
    return str(yol).replace("\\", "/").lower()


def owned_tree(pgdata: Path) -> list[int]:
    """EGALIGI ISBOTLANGAN process daraxti: postmaster + barcha bolalari.

    Uchta shart bajarilmasa BO'SH ro'yxat qaytadi — ya'ni hech narsa
    to'xtatilmaydi. «Ehtimol bizniki» degan holat YO'Q.
    """
    pid = _pid_from_pgdata(pgdata)
    if pid is None:
        return []
    if not _cmdline_has(pid, _normalize(pgdata).rstrip("/")):
        #  Buyruq satrida bizning `pgdata` YO'Q: bu PID qayta ishlatilgan yoki
        #  umuman boshqa server. TEGMAYMIZ.
        return []
    try:
        import psutil
        p = psutil.Process(pid)
        return [pid] + [c.pid for c in p.children(recursive=True)]
    except Exception:      # noqa: BLE001
        return [pid]


# ══ 2. JOB OBYEKTI (Windows) — qattiq o'limga qarshi yagona ishonchli to'siq ══

def _ensure_job():
    """Bitta `KILL_ON_JOB_CLOSE` job yaratadi. Windows'dan tashqarida `None`."""
    global _JOB, _JOB_FAILED
    if _JOB is not None or _JOB_FAILED:
        return _JOB
    if os.name != "nt":
        _JOB_FAILED = True
        return None
    try:
        import ctypes
        from ctypes import wintypes as w

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", w.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", w.DWORD),
                        ("SchedulingClass", w.DWORD)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = w.HANDLE
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        #  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        info.BasicLimitInformation.LimitFlags = 0x00002000
        #  JobObjectExtendedLimitInformation = 9
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                           ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
        _JOB = (k32, job)
        return _JOB
    except Exception as e:      # noqa: BLE001
        #  ⚠️  FAIL-SOFT: job yaratilmasa testlar baribir ishlashi kerak —
        #      bu QO'SHIMCHA to'siq, yakka yechim emas. Sabab jurnalga tushadi.
        print(f"[pgown] job obyekti yaratilmadi ({e}) -> faqat seans oxiridagi "
              f"tozalashga tayanamiz")
        _JOB_FAILED = True
        return None


def _enlist(pid: int) -> bool:
    """PID'ni job'ga qo'shadi. Bolalari KEYIN tug'ilsa — avtomatik job ichida."""
    j = _ensure_job()
    if j is None:
        return False
    k32, job = j
    import ctypes
    from ctypes import wintypes as w
    #  PROCESS_SET_QUOTA | PROCESS_TERMINATE
    k32.OpenProcess.restype = w.HANDLE
    h = k32.OpenProcess(0x0100 | 0x0001, False, int(pid))
    if not h:
        return False
    try:
        return bool(k32.AssignProcessToJobObject(job, h))
    finally:
        k32.CloseHandle(h)


# ══ 3. RO'YXATGA OLISH ══════════════════════════════════════════════════════

def track(srv, pgdata) -> None:
    """Yaratilgan serverni ro'yxatga oladi va job'ga qo'shadi."""
    pgdata = Path(str(pgdata))
    pid = _pid_from_pgdata(pgdata)
    qoshildi = []
    if pid is not None:
        #  Avval POSTMASTER: undan keyin tug'ilgan bolalar avtomatik job ichida.
        if _enlist(pid):
            qoshildi.append(pid)
        #  Mavjud bolalar (checkpointer, walwriter, ...) ALOHIDA qo'shiladi:
        #  `AssignProcessToJobObject` mavjud bolalarni O'Z-O'ZIDAN olmaydi.
        try:
            import psutil
            for c in psutil.Process(pid).children(recursive=True):
                if _enlist(c.pid):
                    qoshildi.append(c.pid)
        except Exception:      # noqa: BLE001
            pass
    _OWNED.append({"srv": srv, "pgdata": pgdata, "pid": pid, "job": qoshildi})


def adopt(pgdata) -> bool:
    """Server ko‘tarilgan, lekin `get_server` QAYTMAGAN holat uchun.

    ⚠️  NEGA KERAK (o‘lchangan). `PostgresServer.__init__` serverni ishga
        tushirgandan KEYIN yiqilishi mumkin (uchta yo‘l: `pg_ctl` timeout’i,
        nolga teng bo‘lmagan chiqish kodi, `postmaster.pid` ning yarim yozilgan
        holati). O‘shanda `get_server` QAYTMAYDI, demak repo tracker’i ham
        ishlamaydi — ya’ni na job obyekti, na egalik-stop qo‘llanadi.
        `pgserver` ning o‘z `atexit` handleri ham yordam bermaydi: u pid’ni
        ro‘yxatga ENG OXIRIDA qo‘shadi va unga yetib borilmagan, shu bois
        handler jim qaytadi.
    ⚠️  EGALIK SHARTLARI AYNI: faqat `<pgdata>/postmaster.pid` bor, PID jonli,
        VA buyruq satrida shu `pgdata` bo‘lsa qabul qilinadi. Aks holda
        `False` qaytadi va HECH NARSA qilinmaydi.
    """
    from pathlib import Path as _P
    pgdata = _P(str(pgdata))
    if not owned_tree(pgdata):
        return False
    track(None, pgdata)
    return True


# ══ 4. BOSHQARILGAN TO'XTATISH ══════════════════════════════════════════════

def _graceful(srv, timeout: float) -> str:
    """`srv.cleanup()` ni VAQT CHEGARASI bilan chaqiradi.

    ⚠️  ALOHIDA THREAD VA `daemon=True`: `pgserver._cleanup()` global
        `InterProcessLock` oladi va `pg_ctl -w stop` ni timeout'siz chaqiradi,
        ya'ni u CHEKSIZ bloklanishi mumkin. Thread'ni tashlab ketish mumkin,
        asosiy oqim esa egalik bilan to'xtatishga o'tadi.
    """
    if srv is None:
        #  ⚠️  `adopt` yo‘lida `srv` obyekti YO‘Q (konstruktor yiqilgan).
        #      Odobli to‘xtatish imkoni yo‘q — to‘g‘ridan-to‘g‘ri egalik
        #      tekshiruviga o‘tiladi.
        return "obyekt yo‘q"
    natija = {"holat": "ishladi"}

    def _ish():
        try:
            srv.cleanup()
            natija["holat"] = "odobli"
        except Exception as e:      # noqa: BLE001
            natija["holat"] = f"istisno:{type(e).__name__}"

    t = threading.Thread(target=_ish, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return "vaqt tugadi"
    return natija["holat"]


def _stop_tree(pids: list[int]) -> int:
    """Berilgan PID'larni to'xtatadi: avval odobli, keyin majburiy. -> qolgan son."""
    try:
        import psutil
    except ImportError:
        return len(pids)
    proclar = []
    for pid in pids:
        try:
            proclar.append(psutil.Process(pid))
        except Exception:      # noqa: BLE001
            pass
    for p in proclar:
        try:
            p.terminate()
        except Exception:      # noqa: BLE001
            pass
    _tirik = psutil.wait_procs(proclar, timeout=5)[1]
    for p in _tirik:
        try:
            p.kill()
        except Exception:      # noqa: BLE001
            pass
    return len(psutil.wait_procs(_tirik, timeout=5)[1])


def cleanup_all(verbose: bool = True) -> dict:
    """HAR ro'yxatga olingan klasterni to'xtatadi va papkasini o'chiradi.

    ⚠️  TARTIB MUHIM: papka FAQAT process o'lgandan KEYIN o'chiriladi. Teskari
        tartibda postmaster o'z `pgdata` si ostidan yo'q qilingan fayllarga
        yozishga urinadi va Windows'da papka «band» bo'lib qoladi.
    """
    hisob = {"odobli": 0, "majburiy": 0, "qolgan": 0, "papka": 0, "tegilmadi": 0}
    while _OWNED:
        rec = _OWNED.pop()
        pgdata = rec["pgdata"]
        holat = _graceful(rec["srv"], STOP_TIMEOUT)
        if holat == "odobli":
            hisob["odobli"] += 1
        #  Odobli yo'l ishlagan bo'lsa ham TEKSHIRAMIZ: `_cleanup` refcount
        #  tufayli JIM erta qaytishi mumkin (`.handle_pids.json` da boshqa pid).
        qoldi = owned_tree(pgdata)
        if qoldi:
            if verbose:
                print(f"[pgown] {holat}: egalik isbotlandi, to'xtatamiz {qoldi} "
                      f"({pgdata.name})")
            qolgan = _stop_tree(qoldi)
            hisob["majburiy"] += 1
            hisob["qolgan"] += qolgan
        elif holat not in ("odobli",):
            #  To'xtamadi, lekin EGALIK ISBOTLANMADI -> TEGMAYMIZ.
            hisob["tegilmadi"] += 1
            if verbose:
                print(f"[pgown] {holat}: egalik ISBOTLANMADI, TEGILMAYDI ({pgdata})")
        try:
            if pgdata.is_dir():
                shutil.rmtree(pgdata, ignore_errors=True)
            ota = pgdata.parent
            if ota.is_dir() and not any(ota.iterdir()):
                ota.rmdir()
            hisob["papka"] += 1
        except Exception as e:      # noqa: BLE001
            if verbose:
                print(f"[pgown] papkani o'chirib bo'lmadi ({pgdata}): {e}")
    return hisob


def owned_snapshot() -> list[dict]:
    """Testlar uchun: hozir ro'yxatda nima bor (process tiriklik holati bilan)."""
    return [{"pgdata": str(r["pgdata"]), "pid": r["pid"],
             "job": r["job"], "tirik": bool(owned_tree(r["pgdata"]))}
            for r in _OWNED]
