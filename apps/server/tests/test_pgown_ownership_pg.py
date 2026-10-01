# -*- coding: utf-8 -*-
"""EGALIK KAFOLATI — HAQIQIY postgres processlari bilan.

NEGA BU FAYL BOR
================
`tests/test_pg_temp_cleanup.py` MEXANIZMNI soxta server bilan sinaydi va o'z
izohida aytadi: «Bu yerda HAQIQIY PostgreSQL ko'tarilmaydi». Ya'ni u PAPKALAR
tozalanishini isbotlaydi, PROCESSLAR o'lishini esa YO'Q.

Bu fayl aynan shu bo'shliqni yopadi va eng xavfli savolga javob beradi:
tozalash FAQAT o'zi yaratgan klasterga tegadimi.

⚠️  BU MASHINADA BEGONA `postgres.exe` LAR BOR (boshqa ishlardan, yuzlab).
    Agar tozalash nom bo'yicha ishlaganda (`taskkill /IM postgres.exe` yoki
    «hamma postgres») u BEGONA ishni o'ldirardi. Shu bois quyidagi test
    «aloqasiz» klaster YONIDA tozalashni bajaradi va aloqasiz klaster
    TIRIK QOLISHINI talab qiladi.
⚠️  IKKI KLASTER ishlatiladi, ko'p emas: mashina resursi cheklangan.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
psutil = pytest.importorskip("psutil")

from tests import pgown  # noqa: E402


def _tirik(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _xom_klaster(yol: Path):
    """Tracker'ni CHETLAB O'TIB klaster ochadi — ya'ni `pgown` uchun «aloqasiz».

    ⚠️  `pgserver.get_server` conftest tomonidan o'ralgan va har chaqiruv
        `pgown.track` ga tushadi. «Aloqasiz» klaster kerak bo'lgani uchun
        sinfning o'zi chaqiriladi.
    """
    from pgserver.postgres_server import PostgresServer
    yol.mkdir(parents=True, exist_ok=True)
    return PostgresServer(yol, cleanup_mode="stop")


# ══ 1. EGALIK: o'zini to'xtatadi, ALOQASIZNI tirik qoldiradi ════════════════

def test_PG_tozalash_FAQAT_oz_klasterini_toxtatadi(tmp_path):
    """⚠️  BU TESTNING MOHIYATI — XAVFSIZLIK, qulaylik emas.

    O'lchanadi: `pgown` ro'yxatidagi klaster o'ladi, ro'yxatda BO'LMAGAN
    klaster esa TIRIK qoladi. Ikkinchi shart buzilsa tozalash begona ishni
    o'ldirishi mumkin degani.
    """
    mening_yol = tmp_path / "mine" / "pgdata"
    aloqasiz_yol = tmp_path / "other" / "pgdata"
    mening_yol.parent.mkdir(parents=True, exist_ok=True)

    #  (a) MENING klasterim — o'ralgan `get_server` orqali, ya'ni ro'yxatda.
    mening = pgserver.get_server(str(mening_yol))
    mening_pid = pgown._pid_from_pgdata(mening_yol)
    #  (b) ALOQASIZ klaster — tracker'dan chetda.
    aloqasiz = _xom_klaster(aloqasiz_yol)
    aloqasiz_pid = pgown._pid_from_pgdata(aloqasiz_yol)

    assert _tirik(mening_pid), "mening klasterim ko'tarilmadi"
    assert _tirik(aloqasiz_pid), "aloqasiz klaster ko'tarilmadi"
    assert mening_pid != aloqasiz_pid

    #  ⚠️  `cleanup_all()` GLOBAL ro'yxatni bo'shatadi. Boshqa testlarning
    #      (masalan `tests/cash` ning seans klasteri) yozuvlariga tegmasligi
    #      uchun ro'yxat VAQTINCHA faqat o'z yozuvimizga qisqartiriladi.
    saqlangan = pgown._OWNED[:]
    mening_yozuv = [r for r in saqlangan
                    if str(r["pgdata"]) == str(mening_yol)]
    assert mening_yozuv, "mening klasterim ro'yxatga TUSHMAGAN (tracker ishlamadi)"
    try:
        pgown._OWNED[:] = mening_yozuv
        pgown.cleanup_all(verbose=True)
    finally:
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening_yozuv]

    assert not _tirik(mening_pid), "o'z klasterim TO'XTAMADI"
    assert _tirik(aloqasiz_pid), (
        "ALOQASIZ klaster O'LDIRILDI — tozalash egalikdan tashqariga chiqdi")

    #  O'zimizdan keyin tozalaymiz: aloqasiz klasterni ham to'xtatamiz.
    try:
        aloqasiz.cleanup()
    except Exception:      # noqa: BLE001
        pass
    qoldi = pgown.owned_tree(aloqasiz_yol)
    if qoldi:
        pgown._stop_tree(qoldi)
    assert not _tirik(aloqasiz_pid), "test o'zidan keyin process qoldirdi"


# ══ 2. EGALIK ISBOTLANMASA — HECH NARSA TO'XTATILMAYDI ═════════════════════

def test_EGALIK_isbotlanmasa_TEGILMAYDI(tmp_path):
    """⚠️  PID QAYTA ISHLATILISHI. Windows PID'larni qayta beradi va eskirgan
        `postmaster.pid` butunlay BOSHQA processni ko'rsatishi mumkin.
        `pgserver` ning o'z fallback'i buni TEKSHIRMAYDI
        (`utils.PostmasterInfo._init_process_meta` da `create_time` solishtiruvi
        IZOHGA OLINGAN), ya'ni u begona processni `terminate()` qilishi mumkin.
        Bu yerda uchinchi shart — JONLI processning buyruq satri — talab
        qilinadi, shu bois quyidagi holatlar BO'SH ro'yxat beradi.
    """
    d = tmp_path / "soxta"
    d.mkdir()

    #  (a) `postmaster.pid` YO'Q -> egalik yo'q
    assert pgown.owned_tree(d) == []

    #  (b) `postmaster.pid` MENING python processimni ko'rsatadi. PID TIRIK,
    #      lekin u postgres EMAS va buyruq satrida bu yo'l YO'Q.
    (d / "postmaster.pid").write_text(f"{os.getpid()}\n{d}\n1\n5432\n\n\n\nready\n")
    assert pgown.owned_tree(d) == [], (
        "tirik, lekin BEGONA process egalik deb sanaldi — bu kill xavfi")

    #  (c) mavjud bo'lmagan PID -> egalik yo'q
    (d / "postmaster.pid").write_text(f"{os.getpid() + 100000}\n{d}\n1\n5432\n\n\n\nready\n")
    assert pgown.owned_tree(d) == []

    #  (d) buzuq fayl -> egalik yo'q (istisno ko'tarilmaydi)
    (d / "postmaster.pid").write_text("bu son emas\n")
    assert pgown.owned_tree(d) == []
    (d / "postmaster.pid").write_text("")
    assert pgown.owned_tree(d) == []


def test_TOZALASH_nom_boyicha_QIDIRMAYDI():
    """⚠️  REGRESSIYA TO'SIG'I: tozalash kodida process NOMI bo'yicha tanlash
        yoki ommaviy o'ldirish PAYDO BO'LMASIN. Bu mashinada yuzlab begona
        `postgres.exe` bor — bitta `taskkill /IM` butun boshqa ishni yo'q qilardi.
    """
    import io as _io
    import tokenize

    #  ⚠️  FAQAT BAJARILADIGAN KOD tekshiriladi. Izohlar va satr literallari
    #      CHIQARIB TASHLANADI, chunki bu modul taqiqlarning O'ZINI izohda
    #      nomma-nom sanaydi (`taskkill /IM ...` TAQIQ deb yozilgan) — xom matn
    #      bo'yicha qidiruv o'z hujjatiga urilib yolg'on qizil berardi.
    kod = []
    with _io.open(pgown.__file__, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kod.append(tok.string)
    kod = " ".join(kod)
    for taqiq in ("/IM", "process_iter", "pkill", "killall", "Get-Process",
                  "taskkill"):
        assert taqiq not in kod, (
            f"tozalash KODIDA nom bo'yicha qidiruv: {taqiq!r} — bu mashinada "
            f"yuzlab begona postgres bor, bitta ommaviy o'ldirish boshqa ishni "
            f"yo'q qilardi")
    #  Egalik uchun uchta shart KODDA bo'lishi shart.
    for shart in ("_cmdline_has", "cmdline", "_pid_from_pgdata", "_normalize"):
        assert shart in kod, shart


# ══ 3. QATLAM 2: `cleanup()` YIQILSA HAM server to'xtatiladi ════════════════

def test_PG_cleanup_YIQILSA_HAM_server_toxtatiladi(tmp_path):
    """⚠️  BU ENG MUHIM FUNKSIONAL TEST. `pgserver._cleanup` refcount yozuvini
        ISH BAJARILISHIDAN OLDIN o'chiradi (`get_and_remove` ni birinchi
        chaqiradi), shu bois u yerdagi HAR QANDAY istisno serverni to'xtatmasdan
        qoldiradi VA `atexit` qayta urinishini ham befoyda qiladi — chiqish kodi
        esa 0 bo'ladi, ya'ni oqish KO'RINMAYDI.
        O'lchangan: shu holatda himoyasiz yurish 1 yetim postmaster qoldiradi.
    """
    import subprocess

    import pgserver.postgres_server as ps

    yol = tmp_path / "boom" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(yol))
    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid)

    asl = ps.pg_ctl

    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pg_ctl stop", timeout=0.1)

    ps.pg_ctl = _boom
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    assert mening, "ro'yxatga tushmagan"
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=True)
    finally:
        ps.pg_ctl = asl
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]

    assert not _tirik(pid), (
        "`cleanup()` istisno bergach server TIRIK qoldi — egalik-stop ishlamadi")


# ══ 4. QATLAM 3: KONSTRUKTOR yiqilsa klaster EGALLANADI ════════════════════

def test_PG_konstruktor_yiqilsa_klaster_EGALLANADI(tmp_path):
    """⚠️  `get_server` QAYTMASA tracker ishlamaydi: postmaster na job obyektiga,
        na tozalash ro'yxatiga tushadi, `pgserver` ning `atexit` handleri ham jim
        qaytadi (pid ro'yxatga ENG OXIRIDA qo'shiladi va unga yetib borilmagan).
        Shu bois `get_server` istisno bergan taqdirda ham klaster EGALLANADI.
    """
    import pgserver.postgres_server as ps

    yol = tmp_path / "ctor" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    asl = ps.PostgresServer.ensure_postgres_running

    def _keyin_yiqil(self):
        asl(self)                       # server HAQIQATAN ko'tariladi
        raise RuntimeError("konstruktor server ko'tarilgandan KEYIN yiqildi")

    ps.PostgresServer.ensure_postgres_running = _keyin_yiqil
    oldin = len(pgown._OWNED)
    try:
        with pytest.raises(RuntimeError):
            pgserver.get_server(str(yol))
    finally:
        ps.PostgresServer.ensure_postgres_running = asl

    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid), "holat yasalmadi: server ko'tarilmagan"
    assert len(pgown._OWNED) == oldin + 1, (
        "konstruktor yiqilgach klaster EGALLANMADI — u hech qayerda kuzatilmaydi")

    #  O'zimizdan keyin tozalaymiz.
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=False)
    finally:
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]
    assert not _tirik(pid), "egallangan klaster to'xtatilmadi"


# ══ 5. QATLAM 1: postmaster HAQIQATAN job obyekti ICHIDAMI ═════════════════

@pytest.mark.skipif(os.name != "nt", reason="job obyekti faqat Windows'da")
def test_PG_postmaster_JOB_ichida_va_job_KILL_ON_CLOSE(tmp_path):
    """⚠️  QATTIQ O'LIMNI TESTDA QAYTA YASAB BO'LMAYDI: `os._exit` yoki
        `taskkill /F` butun pytest seansini o'ldirardi, ya'ni bunday test
        TO'PLAMGA QO'SHILSA har yurishni buzardi (o'lchangan: aynan shu
        sababdan reproduksiya probalari repoda SAQLANMADI).
        Shu bois bu yerda OS KAFOLATINING SHARTI tekshiriladi: postmaster
        `KILL_ON_JOB_CLOSE` bayrog'i o'rnatilgan job ichida bo'lsa, pytest
        processi QANDAY o'lsa ham OS job a'zolarini o'zi tugatadi.
    ⚠️  BOLALAR ALOHIDA QO'SHILADI: `AssignProcessToJobObject` MAVJUD bolalarni
        o'z-o'zidan olmaydi, postmaster esa yordamchi processlarini (checkpointer,
        walwriter, ...) ishga tushishida fork qiladi. Shu bois bu test
        BOLALARNI HAM tekshiradi — aks holda job faqat postmaster'ni o'ldirib,
        bolalari yetim qolardi.
    """
    import ctypes
    from ctypes import wintypes as w

    yol = tmp_path / "job" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(yol))
    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid)

    j = pgown._ensure_job()
    assert j is not None, "job obyekti yaratilmagan — qattiq o'lim himoyasi YO'Q"
    k32, job = j

    #  (a) `KILL_ON_JOB_CLOSE` bayrog'i O'RNATILGANMI (0x2000).
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("r_op", "w_op", "o_op", "r_tx", "w_tx", "o_tx")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", w.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", w.DWORD),
                    ("SchedulingClass", w.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = EXT()
    qaytgan = w.DWORD(0)
    ok = k32.QueryInformationJobObject(job, 9, ctypes.byref(info),
                                       ctypes.sizeof(info), ctypes.byref(qaytgan))
    assert ok, "QueryInformationJobObject yiqildi"
    assert info.BasicLimitInformation.LimitFlags & 0x2000, (
        "KILL_ON_JOB_CLOSE o'rnatilmagan — process o'lsa job a'zolari TIRIK qoladi")

    #  (b) postmaster VA uning bolalari job ICHIDAMI.
    def _jobdami(p: int) -> bool:
        k32.OpenProcess.restype = w.HANDLE
        h = k32.OpenProcess(0x1000, False, int(p))      # PROCESS_QUERY_LIMITED_INFORMATION
        assert h, f"OpenProcess({p}) yiqildi"
        try:
            natija = w.BOOL(0)
            assert k32.IsProcessInJob(h, job, ctypes.byref(natija)), "IsProcessInJob"
            return bool(natija.value)
        finally:
            k32.CloseHandle(h)

    daraxt = pgown.owned_tree(yol)
    assert len(daraxt) >= 2, f"bolalar topilmadi: {daraxt}"
    tashqarida = [p for p in daraxt if not _jobdami(p)]
    assert not tashqarida, (
        f"job'dan TASHQARIDA qolgan processlar {tashqarida} — qattiq o'limda "
        f"ular YETIM qolardi")

    #  O'zimizdan keyin tozalaymiz.
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=False)
    finally:
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]
    assert not _tirik(pid)
